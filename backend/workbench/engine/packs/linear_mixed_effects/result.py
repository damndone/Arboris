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
    build_lmm_result_identity,
)

from .diagnostics import classify_lmm_diagnostics
from .figures import build_lmm_trajectory_context
from .input import PreparedLmmInput


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


def normalize_lmm_result(
    *,
    dataset_fingerprint: str,
    source_row_count: int,
    outcome: str,
    prepared: PreparedLmmInput,
    fitted: Any,
) -> dict[str, Any]:
    """Convert a fitted MixedLM object into JSON-safe, declared LMM facts."""

    observation_counts = prepared.frame.groupby(
        prepared.input.subject_id, sort=True
    ).size()
    observations_per_group = {
        str(subject): int(count) for subject, count in observation_counts.items()
    }
    common: dict[str, Any] = {
        "schema_version": 1,
        "contract_version": LMM_CONTRACT_VERSION,
        "estimator_version": LMM_ESTIMATOR_VERSION,
        "model_id": LMM_MODEL_ID,
        "model_type": LMM_MODEL_TYPE,
        "engine": "statsmodels",
        "fit_method": prepared.input.fit_method,
        "converged": bool(fitted.converged),
        "status": "complete" if bool(fitted.converged) else "failed",
        "optimizer": LMM_OPTIMIZER,
        "nobs": int(fitted.nobs),
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
    }
    if not bool(fitted.converged):
        diagnostics = classify_lmm_diagnostics(
            converged=False,
            random_slope=prepared.input.random_slope,
            covariance_matrix=[],
            residual_variance=0.0,
        )
        return {
            **common,
            "coefficients": {},
            "random_effects": {},
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
            "figure_context": None,
            "warnings": [],
        }

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
        "n_groups": int(len(observation_counts)),
        "observations_per_group": observations_per_group,
    }
    covariance_matrix = fitted.cov_re.to_numpy(dtype=float).tolist()
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=prepared.input.random_slope,
        covariance_matrix=covariance_matrix,
        residual_variance=random_effects["residual_variance"] or 0.0,
    )
    return {
        **common,
        "coefficients": {prepared.primary_result_id: primary},
        "random_effects": random_effects,
        "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "figure_context": build_lmm_trajectory_context(
            prepared=prepared,
            fitted=fitted,
            outcome=outcome,
        ),
        "warnings": [
            diagnostic.code
            for diagnostic in diagnostics
            if diagnostic.severity == "warning"
        ],
    }
