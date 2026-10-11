"""Coefficients: bounded read-only context projection."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from ...artifacts import read_json
from ..bounds import _public_positive_int, _public_stat_number
from .requests import (
    _MAX_PUBLIC_MODEL_PREDICTORS,
)
from .summaries import (
    _bounded_by_group,
    _bounded_inference,
    _bounded_multiple_imputation,
    _fit_statistics,
    _pooled_coefficient_fields,
)

def _lmm_published_results(run_root: Path) -> list[dict[str, Any]]:
    """An LMM result in the shared result shape: its published estimand and,
    from its validated inference kernel, every fixed effect.

    LMM keeps its versioned packet as the only result source, so it has no
    model_results/*.json; without this the coefficient reader had nothing
    exact for it, and the Agent could not see the terms Wald/lincom/nlcom
    accept (it reported time and x as absent from a model that estimated them).
    The kernel's covariance is the GLS form checked against lme4 and Stata.
    """
    from ...services.lmm_result_adapter import VersionedResultReadError, read_lmm_public_results

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
            "x_columns": list(fixed_terms),
            "estimator_version": payload.get("estimator_version"),
        })
    return results


def _kernel_fixed_effects(run_root: Path, model_id: Any) -> dict[str, dict[str, Any]]:
    """Estimate, SE, z-test and 95% interval of every kernel parameter (z reference)."""
    from scipy import stats

    from ...contracts.model.inference_kernel import kernel_relative_path, validate_inference_kernel
    from ...postestimation.comparison_data import assert_completed_kernel

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


def _public_requested_model_coefficients(
    *,
    run_id: str,
    result: dict[str, Any],
    requested_terms: tuple[str, ...],
    labeler: Any = None,
) -> dict[str, Any] | None:
    """Project one stored result into term-specific, non-row evidence."""

    model_id = result.get("model_id")
    coefficients = result.get("coefficients")
    if not isinstance(model_id, str) or not model_id or not isinstance(coefficients, dict):
        return None

    public_coefficients: list[dict[str, Any]] = []
    missing_terms: list[str] = []
    for term in requested_terms:
        coefficient = coefficients.get(term)
        if not isinstance(coefficient, dict):
            missing_terms.append(term)
            continue
        label = labeler.label(term) if labeler is not None else term
        public_coefficients.append(
            {
                "term": term,
                **({"label": label} if label != term else {}),
                "estimate": _public_stat_number(coefficient.get("estimate")),
                "std_error": _public_stat_number(coefficient.get("std_error")),
                "p_value": _public_stat_number(coefficient.get("p_value")),
                "ci_lower": _public_stat_number(coefficient.get("ci_lower")),
                "ci_upper": _public_stat_number(coefficient.get("ci_upper")),
                "source_id": (
                    coefficient.get("source_id")
                    if isinstance(coefficient.get("source_id"), str)
                    else None
                ),
                **_pooled_coefficient_fields(coefficient),
            }
        )

    predictors = result.get("x_columns")
    public_predictors = (
        [item for item in predictors if isinstance(item, str)][:_MAX_PUBLIC_MODEL_PREDICTORS]
        if isinstance(predictors, list)
        else []
    )
    predictor_count = (
        len([item for item in predictors if isinstance(item, str)])
        if isinstance(predictors, list)
        else 0
    )
    covariance_evidence = result.get("covariance_evidence")
    covariance_evidence = (
        covariance_evidence if isinstance(covariance_evidence, dict) else {}
    )
    confidence_level = _public_probability(covariance_evidence.get("confidence_level"))
    cluster_variable = covariance_evidence.get("cluster_variable")
    cluster_count = _public_positive_int(covariance_evidence.get("cluster_count"))
    return {
        "run_id": run_id,
        "model_id": model_id,
        "model_type": result.get("model_type") if isinstance(result.get("model_type"), str) else None,
        "nobs": _public_positive_int(result.get("nobs")),
        **_fit_statistics(result),
        "df_model": _public_stat_number(result.get("df_model")),
        "df_resid": _public_stat_number(result.get("df_resid")),
        "inference": _bounded_inference(result),
        "outcome": result.get("y_column") if isinstance(result.get("y_column"), str) else None,
        "predictors": public_predictors,
        "predictors_omitted": max(predictor_count - len(public_predictors), 0),
        "entity_col": result.get("entity_col") if isinstance(result.get("entity_col"), str) else None,
        "time_col": result.get("time_col") if isinstance(result.get("time_col"), str) else None,
        "covariance": result.get("covariance") if isinstance(result.get("covariance"), str) else None,
        "covariance_estimator": (
            result.get("covariance_estimator")
            if isinstance(result.get("covariance_estimator"), str)
            else None
        ),
        "confidence_interval": {
            "level": confidence_level,
            "method": (
                covariance_evidence.get("confidence_interval_method")
                if isinstance(covariance_evidence.get("confidence_interval_method"), str)
                else None
            ),
        },
        "covariance_details": {
            "cluster_variable": cluster_variable if isinstance(cluster_variable, str) else None,
            "cluster_count": cluster_count,
            "cluster_entity": (
                covariance_evidence.get("cluster_entity")
                if isinstance(covariance_evidence.get("cluster_entity"), bool)
                else None
            ),
            # Newey-West: kernel, lag, the rule that chose it, and the time order.
            **(
                {"hac": {key: covariance_evidence["hac"].get(key)
                         for key in ("kernel", "lags", "lag_rule", "time_order")}}
                if isinstance(covariance_evidence.get("hac"), dict) else {}
            ),
        },
        "multiple_imputation": _bounded_multiple_imputation(result),
        "by_group": _bounded_by_group(result),
        "coefficients": public_coefficients,
        "missing_terms": missing_terms,
        # When a requested term is absent, name the terms that do exist, so a
        # request for `region` can find C(Q('region'))[T.2] instead of guessing.
        **(
            {
                "available_terms": [
                    {"term": str(term), "label": labeler.label(str(term)) if labeler is not None else str(term)}
                    for term in list(coefficients)[:_MAX_AVAILABLE_TERMS]
                ]
            }
            if missing_terms
            else {}
        ),
        "evidence_ref": {
            "run_id": run_id,
            "model_id": model_id,
            "result_ref": f"model_results:{model_id}",
        },
    }


_MAX_METADATA_COLUMNS = 64


_MAX_VALUE_LABELS_PER_COLUMN = 32


_MAX_AVAILABLE_TERMS = 48


def _run_declared_labels(run_root: Path) -> dict[str, Any]:
    """The labels a run was executed with, as recorded in its inputs."""

    try:
        form = (read_json(run_root / "run_inputs.json") or {}).get("form") or {}
    except (FileNotFoundError, OSError, ValueError):
        return {}
    labels = form.get("labels") if isinstance(form, dict) else None
    return labels if isinstance(labels, dict) else {}


def _bounded_declared_metadata(labels: dict[str, Any]) -> dict[str, Any] | None:
    """Declared metadata trimmed to a size an Agent turn can carry."""

    out: dict[str, Any] = {}
    omitted: list[str] = []
    for field in ("variable_labels", "measurement_level", "user_missing_values"):
        mapping = labels.get(field)
        if isinstance(mapping, dict) and mapping:
            keys = sorted(mapping)[:_MAX_METADATA_COLUMNS]
            if len(mapping) > len(keys):
                omitted.append(field)
            out[field] = {key: mapping[key] for key in keys}
    value_labels = labels.get("value_labels")
    if isinstance(value_labels, dict) and value_labels:
        bounded: dict[str, Any] = {}
        for column in sorted(value_labels)[:_MAX_METADATA_COLUMNS]:
            mapping = value_labels[column]
            if not isinstance(mapping, dict):
                continue
            keys = sorted(mapping)[:_MAX_VALUE_LABELS_PER_COLUMN]
            if len(mapping) > len(keys):
                omitted.append(f"value_labels.{column}")
            bounded[column] = {key: mapping[key] for key in keys}
        if bounded:
            out["value_labels"] = bounded
    if not out:
        return None
    if omitted:
        out["omitted"] = omitted
    return out


def _run_term_labeler(run_root: Path) -> Any:
    from ...term_labels import TermLabeler

    labels = _run_declared_labels(run_root)
    return TermLabeler(
        variable_labels=labels.get("variable_labels") if isinstance(labels.get("variable_labels"), dict) else {},
        value_labels=labels.get("value_labels") if isinstance(labels.get("value_labels"), dict) else {},
    )


def _public_probability(value: Any) -> float | None:
    number = _public_stat_number(value)
    if number is None or not 0 < float(number) < 1:
        return None
    return float(number)

