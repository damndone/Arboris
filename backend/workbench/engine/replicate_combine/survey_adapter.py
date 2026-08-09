"""Typed bridge from the existing survey design to replicate-and-combine.

This module is deliberately outside ``workbench.survey``.  The v1.8.7 survey
design remains the source of truth for weight construction and lonely-PSU
semantics; this adapter only supplies a typed estimator strategy and a named
survey covariance combiner to the shared P7 execution boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

import numpy as np

from workbench.contracts.model.replicate_combine import (
    MAX_EVIDENCE_SCALARS,
    ReplicatePlan,
)
from workbench.survey import EstimatorSpec, SurveyDesign
from workbench.survey.replicates import build_replicates

from .errors import ReplicateCombineError, ReplicateExecutionError
from .runner import ReplicateRegistry, execute_and_combine
from .types import (
    ReplicateAdapter,
    ReplicateBatch,
    ReplicateCombiner,
    ReplicateEvidence,
    ReplicateStrategy,
)


MAX_SURVEY_REPLICATE_CELLS = 5_000_000
MAX_SURVEY_TERMS = 1_000
_SCALE_KEY = "__survey_scale"
_ESTIMATE_PREFIX = "estimate::"
_STRATEGY_ID = "survey.replicate_weights.v1"
_ADAPTER_ID = "survey.estimator_scalars.v1"


class SurveyPackAdapterError(ValueError):
    """Stable input or aggregate-evidence rejection for the survey bridge."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _reject(reason_code: str, message: str) -> None:
    raise SurveyPackAdapterError(reason_code, message)


def _expected_replicate_count(design: SurveyDesign, replicate_type: str) -> int:
    if replicate_type == "provided":
        return len(design.replicate_weight_columns)
    if replicate_type == "jackknife":
        return int(sum(int(value) for value in design.psu_counts()))
    if replicate_type == "bootstrap":
        return 500
    if replicate_type == "brr":
        if design.hadamard_matrix is not None:
            return len(design.hadamard_matrix)
        order = 1
        while order < design.n_strata + 1:
            order *= 2
        return order
    _reject("SURVEY_ADAPTER_REPLICATE_TYPE_INVALID", "replicate_type is not declared")


def _validate_weight_matrix(
    weights: np.ndarray,
    scales: list[float],
    *,
    expected_rows: int,
    expected_columns: int,
) -> tuple[np.ndarray, tuple[float, ...]]:
    values = np.asarray(weights, dtype=float)
    if values.ndim != 2 or values.shape != (expected_rows, expected_columns):
        _reject(
            "SURVEY_ADAPTER_REPLICATE_SHAPE_INVALID",
            "replicate weights do not match the declared survey design",
        )
    if not np.isfinite(values).all() or np.any(values < 0.0):
        _reject(
            "SURVEY_ADAPTER_WEIGHT_INVALID",
            "replicate weights must be finite and non-negative",
        )
    if len(scales) != expected_columns:
        _reject("SURVEY_ADAPTER_SCALE_INVALID", "replicate scale count is inconsistent")
    normalized_scales = tuple(float(value) for value in scales)
    if any(not math.isfinite(value) or value < 0.0 for value in normalized_scales):
        _reject("SURVEY_ADAPTER_SCALE_INVALID", "replicate scales must be finite and non-negative")
    return values, normalized_scales


def _normalize_terms(point: Mapping[str, Any]) -> tuple[list[str], dict[str, float]]:
    if not isinstance(point, Mapping) or not point:
        _reject("SURVEY_ADAPTER_ESTIMATE_INVALID", "the base estimator must return named estimates")
    terms: list[str] = []
    normalized: dict[str, float] = {}
    for term, value in point.items():
        if type(term) is not str or not term:
            _reject("SURVEY_ADAPTER_ESTIMATE_INVALID", "estimate terms must be non-empty names")
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise SurveyPackAdapterError(
                "SURVEY_ADAPTER_ESTIMATE_INVALID", f"estimate {term!r} is not numeric"
            ) from exc
        if not math.isfinite(numeric):
            _reject("SURVEY_ADAPTER_ESTIMATE_INVALID", f"estimate {term!r} is not finite")
        terms.append(term)
        normalized[term] = numeric
    if len(set(terms)) != len(terms):
        _reject("SURVEY_ADAPTER_ESTIMATE_INVALID", "estimate terms must be unique")
    if len(terms) > MAX_SURVEY_TERMS:
        _reject("SURVEY_ADAPTER_ESTIMATE_TOO_LARGE", "estimate term count exceeds the hard bound")
    return terms, normalized


def _fit_base(
    design: SurveyDesign, estimator: EstimatorSpec
) -> tuple[np.ndarray, dict[str, float], list[str]]:
    try:
        mask = np.asarray(design.subpop_mask(), dtype=bool)
    except Exception as exc:  # noqa: BLE001 - boundary converts private detail
        raise SurveyPackAdapterError(
            "SURVEY_ADAPTER_SUBPOP_INVALID", "the declared survey subpopulation is invalid"
        ) from exc
    if mask.ndim != 1 or mask.shape[0] != design.n_obs or not mask.any():
        _reject("SURVEY_ADAPTER_NO_OBSERVATIONS", "the survey design has no retained observations")
    base_weights = np.asarray(design.weights, dtype=float)
    if base_weights.shape != (design.n_obs,) or not np.isfinite(base_weights).all():
        _reject("SURVEY_ADAPTER_WEIGHT_INVALID", "base weights must be finite")
    if np.any(base_weights < 0.0) or float(base_weights[mask].sum()) <= 0.0:
        _reject("SURVEY_ADAPTER_WEIGHT_INVALID", "retained base weights must be non-negative and positive in total")
    frame = design.frame.loc[mask]
    try:
        point_raw = estimator.refit(frame, base_weights[mask])
    except Exception as exc:  # noqa: BLE001 - boundary converts private detail
        raise SurveyPackAdapterError(
            "SURVEY_ADAPTER_BASE_ESTIMATE_FAILED", "the base estimator failed"
        ) from exc
    terms, point = _normalize_terms(point_raw)
    return mask, point, terms


class SurveyReplicateStrategy(ReplicateStrategy):
    """Refit one typed estimator under one already-built survey replicate."""

    strategy_id = _STRATEGY_ID

    def __init__(
        self,
        *,
        frame: Any,
        replicate_weights: np.ndarray,
        scales: tuple[float, ...],
        estimator: EstimatorSpec,
        terms: list[str],
    ) -> None:
        self.frame = frame
        self.replicate_weights = replicate_weights
        self.scales = scales
        self.estimator = estimator
        self.terms = tuple(terms)

    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        del seed
        if (
            plan.kind != "survey_replicate"
            or replicate_index < 0
            or replicate_index >= self.replicate_weights.shape[1]
        ):
            raise ReplicateExecutionError(
                "REPLICATE_STRATEGY_FAILED", "survey replicate index is outside the prepared weight set"
            )
        try:
            point_raw = self.estimator.refit(
                self.frame, self.replicate_weights[:, replicate_index]
            )
            terms, point = _normalize_terms(point_raw)
        except SurveyPackAdapterError as exc:
            raise ReplicateExecutionError("REPLICATE_STRATEGY_FAILED", "survey estimate is invalid") from exc
        except Exception as exc:  # noqa: BLE001 - runner records only stable reason
            raise ReplicateExecutionError("REPLICATE_STRATEGY_EXCEPTION", "survey replicate refit failed") from exc
        if terms != list(self.terms):
            raise ReplicateExecutionError(
                "REPLICATE_STRATEGY_FAILED", "survey replicate terms do not match the base estimate"
            )
        scalars = {_SCALE_KEY: self.scales[replicate_index]}
        scalars.update({_ESTIMATE_PREFIX + term: value for term, value in point.items()})
        return ReplicateEvidence(scalars=scalars)


class SurveyEstimatorAdapter(ReplicateAdapter):
    """Keep only the typed scalar estimates and design scale for combining."""

    adapter_id = _ADAPTER_ID

    def __init__(self, terms: list[str]) -> None:
        self.terms = tuple(terms)

    def adapt(
        self,
        evidence: ReplicateEvidence,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
    ) -> ReplicateEvidence:
        del plan, replicate_index
        expected = {_SCALE_KEY} | {
            _ESTIMATE_PREFIX + term for term in self.terms
        }
        if set(evidence.scalars) != expected:
            raise ReplicateExecutionError(
                "REPLICATE_ADAPTER_FAILED", "survey evidence does not match the base term schema"
            )
        return ReplicateEvidence(
            scalars={key: evidence.scalars[key] for key in sorted(expected)}
        )


class SurveyCovarianceCombiner(ReplicateCombiner):
    """Combine survey replicate estimates with their design-specific scales."""

    combiner_id = "replicate_covariance"

    def __init__(
        self,
        *,
        terms: list[str],
        point: dict[str, float],
        replicate_type: str,
        design: SurveyDesign,
    ) -> None:
        self.terms = tuple(terms)
        self.point = dict(point)
        self.replicate_type = replicate_type
        self.design = design

    def combine(
        self,
        evidence: tuple[ReplicateEvidence, ...],
        *,
        plan: ReplicatePlan,
        batch: ReplicateBatch,
    ) -> dict[str, Any]:
        if len(evidence) < 2:
            raise ReplicateCombineError(
                "REPLICATE_COMBINER_FAILED", "survey covariance needs at least two successful replicates"
            )
        values = np.array(
            [
                [float(item.scalars[_ESTIMATE_PREFIX + term]) for term in self.terms]
                for item in evidence
            ],
            dtype=float,
        )
        scales = np.array([float(item.scalars[_SCALE_KEY]) for item in evidence])
        if not np.isfinite(values).all() or not np.isfinite(scales).all() or np.any(scales < 0.0):
            raise ReplicateCombineError(
                "REPLICATE_COMBINER_FAILED", "survey covariance evidence is not finite"
            )
        centered = values - values.mean(axis=0)
        covariance = np.einsum("i,ij,ik->jk", scales, centered, centered)
        covariance = np.asarray(covariance, dtype=float)
        diagonal = np.diag(covariance)
        if np.any(diagonal < -1.0e-10) or not np.isfinite(covariance).all():
            raise ReplicateCombineError(
                "REPLICATE_COMBINER_FAILED", "survey covariance is not positive semidefinite"
            )
        diagonal = np.maximum(diagonal, 0.0)
        return {
            "method": "survey_replicate",
            "replicate_type": self.replicate_type,
            "replicate_count": len(evidence),
            "terms": list(self.terms),
            "estimates": dict(self.point),
            "standard_errors": {
                term: float(math.sqrt(diagonal[index]))
                for index, term in enumerate(self.terms)
            },
            "covariance": covariance.tolist(),
            "design_degrees_of_freedom": self.design.degf,
            "design_structure": {
                "observations": self.design.n_obs,
                "strata": self.design.n_strata,
                "psu": self.design.n_psu,
            },
            "replicate_summary": {
                "attempted": batch.requested_count,
                "succeeded": batch.succeeded_count,
                "failed": batch.failed_count,
                "failure_reasons": batch.failure_reasons,
            },
            "scale_semantics": "design_specific_replicate_scale_centered_on_replicate_mean",
            "plan_seed": plan.seed,
        }


def run_survey_replicate_covariance(
    design: SurveyDesign,
    estimator: EstimatorSpec,
    *,
    replicate_type: str | None = None,
    seed: int = 0,
    max_failures: int = 0,
) -> dict[str, Any]:
    """Run a new pack's typed estimator through the existing survey weights."""

    if not isinstance(design, SurveyDesign):
        _reject("SURVEY_ADAPTER_DESIGN_INVALID", "design must be a SurveyDesign")
    if not isinstance(estimator, EstimatorSpec):
        _reject("SURVEY_ADAPTER_ESTIMATOR_INVALID", "estimator must be an EstimatorSpec")
    if replicate_type is None:
        replicate_type = design.replicate_type
    if type(replicate_type) is not str or not replicate_type:
        _reject("SURVEY_ADAPTER_REPLICATE_TYPE_REQUIRED", "replicate_type must be declared")
    expected_count = _expected_replicate_count(design, replicate_type)
    if expected_count < 2:
        _reject("SURVEY_ADAPTER_TOO_FEW_REPLICATES", "at least two survey replicates are required")
    if design.n_obs * expected_count > MAX_SURVEY_REPLICATE_CELLS:
        _reject("SURVEY_ADAPTER_ALLOCATION_EXCEEDED", "replicate weight allocation exceeds the hard bound")
    if type(seed) is not int or isinstance(seed, bool) or seed < 0:
        _reject("SURVEY_ADAPTER_SEED_INVALID", "seed must be a non-negative integer")
    if type(max_failures) is not int or isinstance(max_failures, bool) or not 0 <= max_failures < expected_count:
        _reject("SURVEY_ADAPTER_FAILURE_BUDGET_INVALID", "max_failures must be in [0, replicate_count)")

    mask, point, terms = _fit_base(design, estimator)
    try:
        replicate_weights_raw, scales_raw = build_replicates(design, replicate_type)
    except Exception as exc:  # noqa: BLE001 - survey private details stay bounded
        raise SurveyPackAdapterError(
            "SURVEY_ADAPTER_REPLICATE_BUILD_FAILED", "the existing survey design could not build replicates"
        ) from exc
    replicate_weights, scales = _validate_weight_matrix(
        replicate_weights_raw,
        scales_raw,
        expected_rows=design.n_obs,
        expected_columns=expected_count,
    )
    # The strategy sees only the retained design frame and corresponding
    # weights.  Rows outside a subpopulation remain in the design's replicate
    # construction, preserving the existing survey semantics.
    frame = design.frame.loc[mask]
    strategy = SurveyReplicateStrategy(
        frame=frame,
        replicate_weights=replicate_weights[mask, :],
        scales=scales,
        estimator=estimator,
        terms=terms,
    )
    registry = ReplicateRegistry()
    registry.register_strategy(strategy)
    registry.register_adapter(SurveyEstimatorAdapter(terms))
    registry.register_combiner(
        SurveyCovarianceCombiner(
            terms=terms,
            point=point,
            replicate_type=replicate_type,
            design=design,
        )
    )
    scalar_budget = expected_count * (len(terms) + 1)
    if scalar_budget > MAX_EVIDENCE_SCALARS:
        _reject("SURVEY_ADAPTER_EVIDENCE_EXCEEDED", "survey scalar evidence exceeds the hard bound")
    plan = ReplicatePlan(
        kind="survey_replicate",
        requested_replicates=expected_count,
        seed=seed,
        strategy_id=_STRATEGY_ID,
        adapter_id=_ADAPTER_ID,
        combiner_id="replicate_covariance",
        max_failures=max_failures,
        max_evidence_scalars=scalar_budget,
    )
    combined = execute_and_combine(plan, registry=registry)
    return combined.to_dict()


__all__ = [
    "MAX_SURVEY_REPLICATE_CELLS",
    "MAX_SURVEY_TERMS",
    "SurveyCovarianceCombiner",
    "SurveyEstimatorAdapter",
    "SurveyPackAdapterError",
    "SurveyReplicateStrategy",
    "run_survey_replicate_covariance",
]
