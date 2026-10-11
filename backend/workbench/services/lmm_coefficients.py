"""Shared, validated fixed-effect views for manual and Agent consumers."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from workbench.artifacts import read_json

def _lmm_published_results(run_root: Path) -> list[dict[str, Any]]:
    """An LMM result in the shared result shape: its published estimand and,
    from its validated inference kernel, every fixed effect.

    LMM keeps its versioned packet as the only result source, so it has no
    model_results/*.json; without this the coefficient reader had nothing
    exact for it, and the Agent could not see the terms Wald/lincom/nlcom
    accept (it reported time and x as absent from a model that estimated them).
    The kernel's covariance is the GLS form checked against lme4 and Stata.
    """
    from workbench.services.lmm_result_adapter import VersionedResultReadError, read_lmm_public_results

    try:
        records = read_lmm_public_results(run_root)
    except VersionedResultReadError:
        return []
    results = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("status") != "complete":
            continue
        coefficients = {}
        for target, entry in (payload.get("coefficients") or {}).items():
            if not isinstance(entry, dict):
                continue
            interval = entry.get("confidence_interval")
            bounds = interval if isinstance(interval, list) and len(interval) == 2 else [None, None]
            coefficients[target] = {**entry, "ci_lower": bounds[0], "ci_upper": bounds[1]}
        fixed_terms = _kernel_fixed_effects(run_root, payload.get("model_id"))
        for term, entry in fixed_terms.items():
            coefficients.setdefault(term, entry)
        results.append({
            "model_id": payload.get("model_id"), "model_type": payload.get("model_type"),
            "nobs": payload.get("nobs"), "coefficients": coefficients,
            "primary_estimand": {"term": payload.get("primary_target_id")},
            "fit_method": payload.get("fit_method"),
            "x_columns": list(fixed_terms),
            "estimator_version": payload.get("estimator_version"),
        })
    return results


def _kernel_fixed_effects(run_root: Path, model_id: Any) -> dict[str, dict[str, Any]]:
    """Estimate, SE, z-test and 95% interval of every kernel parameter (z reference)."""
    from scipy import stats

    from workbench.contracts.model.inference_kernel import kernel_relative_path, validate_inference_kernel
    from workbench.postestimation.comparison_data import assert_completed_kernel

    if not isinstance(model_id, str) or not model_id:
        return {}
    path = run_root / kernel_relative_path(model_id)
    try:
        if not path.is_file():
            return {}
        kernel = read_json(path)
        validate_inference_kernel(kernel)
        assert_completed_kernel(run_root, kernel)
    except (OSError, ValueError):
        return {}
    if kernel.get("model_id") != model_id or kernel.get("vcov_scope") != "full" or kernel.get("reference_distribution") != "z":
        return {}
    critical = float(stats.norm.ppf(0.975))
    terms: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(kernel.get("param_names") or []):
        estimate = float(kernel["params"][index])
        variance = float(kernel["vcov"][index][index])
        if not variance > 0:
            continue
        std_error = variance ** 0.5
        terms[str(name)] = {
            "estimate": estimate, "std_error": std_error,
            "p_value": float(2 * stats.norm.sf(abs(estimate / std_error))),
            "ci_lower": estimate - critical * std_error, "ci_upper": estimate + critical * std_error,
            "source_id": f"model_results.inference_kernels.{model_id}.params.{name}",
        }
    return terms


