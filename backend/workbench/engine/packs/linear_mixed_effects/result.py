"""Normalize locked LMM result and diagnostic packet facts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_ESTIMATOR_VERSION,
    LMM_INFERENCE_METHOD,
    LMM_MISSING_POLICY,
    LMM_MODEL_TYPE,
    LmmDiagnostic,
    build_lmm_result_identity,
)

from .diagnostics import classify_lmm_diagnostics
from .figures import build_lmm_trajectory_context
from .input import PreparedLmmInput
from .packets import build_lmm_result_packet as build_lmm_result_envelope


LMM_MODEL_ID = "linear_mixed_effects_1"
LMM_OPTIMIZER = "lbfgs"


def _interaction_term(prepared: PreparedLmmInput) -> str:
    return (
        f"C(Q({prepared.input.group!r}), "
        f"Treatment(reference={prepared.reference_group_value!r}))[T."
        f"{prepared.comparison_group}]:Q({prepared.input.time!r})"
    )


def dataset_fingerprint_for_csv(csv_path: Path) -> str:
    return hashlib.sha256(csv_path.read_bytes()).hexdigest()


def _result_identity(
    *,
    dataset_fingerprint: str,
    outcome: str,
    prepared: PreparedLmmInput,
) -> str:
    return build_lmm_result_identity(
        {
            "dataset_fingerprint": dataset_fingerprint,
            "analysis_unit": prepared.input.subject_id,
            "outcome": outcome,
            "fixed_effects": list(prepared.fixed_effects),
            "random_effects": list(prepared.random_effects),
            "group": prepared.input.group,
            "reference_group": prepared.reference_group,
            "fit_method": prepared.input.fit_method,
            "missing_policy": LMM_MISSING_POLICY,
            "estimator_version": LMM_ESTIMATOR_VERSION,
            "contract_version": LMM_CONTRACT_VERSION,
        }
    )


def _random_effects_summary(
    *,
    fitted: Any,
    prepared: PreparedLmmInput,
) -> dict[str, float | None]:
    covariance = fitted.cov_re
    intercept_variance = float(covariance.iloc[0, 0])
    if prepared.input.random_slope:
        covariance_value = float(covariance.iloc[0, 1])
        return {
            "intercept_variance": intercept_variance,
            "slope_variance": float(covariance.iloc[1, 1]),
            "covariance": covariance_value,
            "intercept_slope_covariance": covariance_value,
            "residual_variance": float(fitted.scale),
        }
    return {
        "intercept_variance": intercept_variance,
        "slope_variance": None,
        "covariance": None,
        "intercept_slope_covariance": None,
        "residual_variance": float(fitted.scale),
    }


def _terminal_result_payload(
    *, common: Mapping[str, Any], diagnostics: list[Any]
) -> dict[str, Any]:
    """Keep unsafe or non-converged fits from making substantive result claims."""

    return {
        **common,
        "converged": False,
        "status": "failed",
        "coefficients": {},
        "random_effects": {},
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "figure_context": None,
        "warnings": [],
    }


def _common_result_fields(
    *,
    dataset_fingerprint: str,
    source_row_count: int,
    outcome: str,
    prepared: PreparedLmmInput,
    converged: bool,
    nobs: int,
    execution_binding: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, int]]:
    observation_counts = prepared.frame.groupby(
        prepared.input.subject_id, sort=True
    ).size()
    observations_per_group = {
        str(subject): int(count) for subject, count in observation_counts.items()
    }
    return {
        "schema_version": 1,
        "contract_version": LMM_CONTRACT_VERSION,
        "estimator_version": LMM_ESTIMATOR_VERSION,
        "model_id": LMM_MODEL_ID,
        "model_type": LMM_MODEL_TYPE,
        "engine": "statsmodels",
        "fit_method": prepared.input.fit_method,
        "converged": converged,
        "status": "complete" if converged else "failed",
        "optimizer": LMM_OPTIMIZER,
        "nobs": nobs,
        "n_groups": int(len(observation_counts)),
        "observations_per_group": observations_per_group,
        "excluded_rows": int(source_row_count - len(prepared.frame)),
        "exclusion_counts": dict(prepared.exclusion_counts),
        "fixed_effects_formula": prepared.formula,
        "random_effects_specification": (
            "1 + " + f"Q({prepared.input.time!r})"
            if prepared.input.random_slope
            else "1"
        ),
        "reference_group": prepared.reference_group,
        "comparison_group": prepared.comparison_group,
        "result_identity": _result_identity(
            dataset_fingerprint=dataset_fingerprint,
            outcome=outcome,
            prepared=prepared,
        ),
        "primary_target_id": prepared.primary_result_id,
        "execution_binding": dict(execution_binding),
    }, observations_per_group


def _normalize_lmm_result_payload(
    *,
    dataset_fingerprint: str,
    source_row_count: int,
    outcome: str,
    prepared: PreparedLmmInput,
    fitted: Any,
    execution_binding: Mapping[str, object],
) -> dict[str, Any]:
    """Build pack-private normalized facts before their public envelope boundary."""

    common, observations_per_group = _common_result_fields(
        dataset_fingerprint=dataset_fingerprint,
        source_row_count=source_row_count,
        outcome=outcome,
        prepared=prepared,
        converged=bool(fitted.converged),
        nobs=int(fitted.nobs),
        execution_binding=execution_binding,
    )
    if not bool(fitted.converged):
        diagnostics = classify_lmm_diagnostics(
            converged=False,
            random_slope=prepared.input.random_slope,
            covariance_matrix=[],
            residual_variance=0.0,
        )
        return _terminal_result_payload(common=common, diagnostics=diagnostics)

    try:
        covariance_matrix = fitted.cov_re.to_numpy(dtype=float).tolist()
        residual_variance = float(fitted.scale)
    except (AttributeError, TypeError, ValueError):
        diagnostics = classify_lmm_diagnostics(
            converged=False,
            random_slope=prepared.input.random_slope,
            covariance_matrix=[],
            residual_variance=0.0,
        )
        return _terminal_result_payload(common=common, diagnostics=diagnostics)
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=prepared.input.random_slope,
        covariance_matrix=covariance_matrix,
        residual_variance=residual_variance,
    )
    if any(diagnostic.status == "failed" for diagnostic in diagnostics):
        return _terminal_result_payload(common=common, diagnostics=diagnostics)

    interaction = _interaction_term(prepared)
    interval = fitted.conf_int().loc[interaction]
    primary = {
        "result_id": prepared.primary_result_id,
        "label": "treated group × time",
        "estimate": float(fitted.params[interaction]),
        "std_error": float(fitted.bse[interaction]),
        "p_value": float(fitted.pvalues[interaction]),
        "confidence_interval": [float(interval.iloc[0]), float(interval.iloc[1])],
        "confidence_level": 0.95,
        "inference_method": LMM_INFERENCE_METHOD,
        "source_id": (
            "model_results.linear_mixed_effects_1.coefficients."
            "group_time_interaction"
        ),
    }
    random_effects = {
        **_random_effects_summary(fitted=fitted, prepared=prepared),
        "n_groups": common["n_groups"],
        "observations_per_group": observations_per_group,
    }
    figure_context, unbalanced_evidence = build_lmm_trajectory_context(
        prepared=prepared,
        fitted=fitted,
        outcome=outcome,
    )
    if unbalanced_evidence is not None:
        diagnostics.append(
            LmmDiagnostic(
                code="LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
                severity="warning",
                status="complete",
                evidence=unbalanced_evidence,
                action_candidate=None,
            )
        )
    return {
        **common,
        "coefficients": {prepared.primary_result_id: primary},
        "random_effects": random_effects,
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "figure_context": figure_context,
        "warnings": [
            diagnostic.code
            for diagnostic in diagnostics
            if diagnostic.severity == "warning"
        ],
    }


def build_lmm_result_packet(
    *,
    dataset_fingerprint: str,
    source_row_count: int,
    outcome: str,
    prepared: PreparedLmmInput,
    fitted: Any,
    execution_binding: Mapping[str, object],
) -> dict[str, Any]:
    """Produce the only public result boundary for a fitted LMM recipe."""

    payload = _normalize_lmm_result_payload(
        dataset_fingerprint=dataset_fingerprint,
        source_row_count=source_row_count,
        outcome=outcome,
        prepared=prepared,
        fitted=fitted,
        execution_binding=execution_binding,
    )
    return build_lmm_result_envelope(payload)


def build_unexpected_fit_failure_result_packet(
    *,
    dataset_fingerprint: str,
    source_row_count: int,
    outcome: str,
    prepared: PreparedLmmInput,
    execution_binding: Mapping[str, object],
) -> dict[str, Any]:
    """Produce a terminal result without exposing unexpected exception details."""

    common, _ = _common_result_fields(
        dataset_fingerprint=dataset_fingerprint,
        source_row_count=source_row_count,
        outcome=outcome,
        prepared=prepared,
        converged=False,
        nobs=len(prepared.frame),
        execution_binding=execution_binding,
    )
    payload = _terminal_result_payload(
        common=common,
        diagnostics=[
            LmmDiagnostic(
                code="LMM_UNEXPECTED_FIT_EXCEPTION",
                severity="error",
                status="failed",
                evidence={},
                action_candidate=None,
            )
        ],
    )
    return build_lmm_result_envelope(payload)
