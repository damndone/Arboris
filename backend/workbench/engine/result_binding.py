"""Typed, family-aware binding of model results to persisted run inputs.

The estimation stage is shared by model packs, but a coefficient table is not
the universal result shape.  This module keeps the common identity/digest
binding in one place and lets non-coefficient packs register a validated
adapter.  A new pack therefore adds a result-binding adapter and contract
tests instead of another estimator-specific branch in the workflow stage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from workbench.artifacts import read_json, sha256_file
from workbench.canonical import sha256_canonical


ResultBindingAdapter = Callable[
    [Path, str, str, dict[str, Any], list[str]], dict[str, Any]
]


class ResultBindingError(ValueError):
    """Structured rejection raised before a model result can be persisted."""

    code = "MODEL_RESULT_INVALID"

    def __init__(self, message: str, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{self.code}: {message}")
        self.evidence = dict(evidence or {"reason": message})


_RESULT_BINDING_ADAPTERS: dict[str, ResultBindingAdapter] = {}
COEFFICIENT_RESULT_BINDING_KEY = "coefficient_table_v1"
_ARTIFACT_BACKED_REQUIRED_REFS = frozenset(
    {
        "ts.artifact_manifest",
        "ts.final_model",
        "ts.forecast_metrics",
        "ts.next_forecast",
        "ts.report",
    }
)
_ARMA_GARCH_ACCEPTANCE_STATUSES = frozenset(
    {"accepted", "accepted_with_warnings", "rejected", "inconclusive"}
)
_ARMA_GARCH_ACCEPTANCE_DIMENSIONS = frozenset(
    {
        "data_readiness",
        "mean_adequacy",
        "volatility_adequacy",
        "distribution_adequacy",
        "forecast_validation",
        "volatility_value_added",
    }
)


def register_result_binding_adapter(
    strategy_key: str, adapter: ResultBindingAdapter
) -> None:
    """Register one server-side result adapter for a declared strategy."""

    if type(strategy_key) is not str or not strategy_key.strip():
        raise ValueError("MODEL_RESULT_BINDING_INVALID: strategy_key must be non-empty text")
    if not callable(adapter):
        raise TypeError("MODEL_RESULT_BINDING_INVALID: adapter must be callable")
    existing = _RESULT_BINDING_ADAPTERS.get(strategy_key)
    if existing is not None and existing is not adapter:
        raise ValueError(
            f"MODEL_RESULT_BINDING_INVALID: adapter already registered for {strategy_key}"
        )
    _RESULT_BINDING_ADAPTERS[strategy_key] = adapter


def is_result_binding_adapter_registered(strategy_key: str) -> bool:
    """Return whether a server-side adapter has been registered for a key."""

    return type(strategy_key) is str and strategy_key in _RESULT_BINDING_ADAPTERS


def _invalid(message: str) -> ValueError:
    return ResultBindingError(message)


def _validate_common(
    run_root: Path,
    run_id: str,
    model_id: str,
    primary: object,
    inputs: object,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(primary, dict):
        raise _invalid("result payload must be an object")
    if (
        not isinstance(inputs, list)
        or not inputs
        or not all(isinstance(item, str) and item and len(item) <= 300 for item in inputs)
    ):
        raise _invalid("source artifact binding is invalid")
    for field in ("nobs", "row_count", "n_observations"):
        value = primary.get(field)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 1_000_000
        ):
            raise _invalid(f"{field} must be a bounded integer")
    for field in ("sampling_weight", "frequency_weight", "analysis_weight", "exposure_col"):
        value = primary.get(field)
        if value is not None and (not isinstance(value, str) or not value or len(value) > 128):
            raise _invalid(f"{field} must be a bounded column name")
    if type(run_id) is not str or not run_id or len(run_id) > 300:
        raise _invalid("run_id is invalid")
    if type(model_id) is not str or not model_id or len(model_id) > 300:
        raise _invalid("model_id is invalid")
    return primary, list(inputs)


def _payload_digest(primary: Mapping[str, Any]) -> str:
    unsigned = dict(primary)
    unsigned["result_binding"] = dict(primary["result_binding"])
    return hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _coefficient_binding(
    run_root: Path,
    run_id: str,
    model_id: str,
    primary: dict[str, Any],
    inputs: list[str],
) -> dict[str, Any]:
    coefficients = primary.get("coefficients")
    if not isinstance(coefficients, dict) or not coefficients:
        raise _invalid("result payload has no coefficients")
    source_ids: dict[str, str] = {}
    for term, coefficient in coefficients.items():
        if not isinstance(term, str) or not isinstance(coefficient, dict):
            raise _invalid("coefficient terms must be objects")
        source_id = f"model_results.{model_id}.coefficients.{term}"
        coefficient["source_id"] = source_id
        source_ids[term] = source_id
        if not isinstance(coefficient.get("warnings"), list):
            coefficient["warnings"] = []
    return {
        "strategy": COEFFICIENT_RESULT_BINDING_KEY,
        "project_root": str(run_root.parent.parent.resolve()),
        "run_id": run_id,
        "model_id": model_id,
        "source_artifact_ids": inputs,
        "coefficient_source_ids": source_ids,
    }


def _bounded_relative_artifact_refs(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise _invalid("artifact_refs must be a non-empty object")
    refs: dict[str, str] = {}
    for key, path in value.items():
        if type(key) is not str or not key or len(key) > 200:
            raise _invalid("artifact_refs contains an invalid artifact key")
        if type(path) is not str or not path or len(path) > 500:
            raise _invalid("artifact_refs contains an invalid artifact path")
        path_parts = path.replace("\\", "/").split("/")
        if path.startswith("/") or ".." in path_parts or "\x00" in path:
            raise _invalid("artifact_refs must contain bounded relative paths")
        refs[key] = path
    return refs


def _finite_number(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{label} must be a finite number or null")
    if not math.isfinite(float(value)):
        raise _invalid(f"{label} must be a finite number or null")


def _optional_finite_number(value: object, label: str) -> None:
    if value is not None:
        _finite_number(value, label)


def _bounded_count(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = 1_000_000,
) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid(f"{label} must be a bounded integer")


def _validate_validation_metrics(value: object) -> None:
    if not isinstance(value, Mapping):
        raise _invalid("artifact-backed validation metrics are invalid")
    required = {
        "validation_n",
        "successful_forecast_n",
        "mae",
        "rmse",
        "mean_error",
        "interval_coverage",
        "average_interval_width",
        "coverage_count",
        "coverage_uncertainty",
        "exception_rate",
        "exception_count",
        "pinball_loss",
    }
    if set(value) != required:
        raise _invalid("artifact-backed validation metrics fields are invalid")

    _bounded_count(
        value["validation_n"],
        "validation.metrics.validation_n",
        minimum=1,
    )
    _bounded_count(
        value["successful_forecast_n"],
        "validation.metrics.successful_forecast_n",
    )
    if value["successful_forecast_n"] > value["validation_n"]:
        raise _invalid("validation.metrics forecast counts are inconsistent")
    _bounded_count(value["coverage_count"], "validation.metrics.coverage_count")
    if value["coverage_count"] > value["successful_forecast_n"]:
        raise _invalid("validation.metrics coverage count is inconsistent")
    _bounded_count(value["exception_count"], "validation.metrics.exception_count")
    if value["exception_count"] > value["successful_forecast_n"]:
        raise _invalid("validation.metrics exception count is inconsistent")

    for field in (
        "mae",
        "rmse",
        "mean_error",
        "interval_coverage",
        "average_interval_width",
        "exception_rate",
        "pinball_loss",
    ):
        _optional_finite_number(value[field], f"validation.metrics.{field}")
    for field in ("interval_coverage", "exception_rate"):
        field_value = value[field]
        if field_value is not None and not 0.0 <= float(field_value) <= 1.0:
            raise _invalid(f"validation.metrics.{field} is outside [0, 1]")

    uncertainty = value["coverage_uncertainty"]
    if not isinstance(uncertainty, Mapping):
        raise _invalid("validation.metrics.coverage_uncertainty is invalid")
    if set(uncertainty) != {"method", "lower", "upper"}:
        raise _invalid("validation.metrics.coverage_uncertainty fields are invalid")
    if uncertainty.get("method") != "wilson_95pct":
        raise _invalid("validation.metrics.coverage_uncertainty.method is invalid")
    for field in ("lower", "upper"):
        if field in uncertainty:
            _optional_finite_number(
                uncertainty[field],
                f"validation.metrics.coverage_uncertainty.{field}",
            )
    lower = uncertainty.get("lower")
    upper = uncertainty.get("upper")
    if lower is not None and upper is not None:
        if not 0.0 <= float(lower) <= 1.0 or not 0.0 <= float(upper) <= 1.0:
            raise _invalid("validation.metrics.coverage_uncertainty bounds are outside [0, 1]")
        if float(lower) > float(upper):
            raise _invalid("validation.metrics.coverage_uncertainty bounds are inconsistent")


def _validate_refit_summary(value: object, label: str) -> None:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object")
    for field in ("fit_scope",):
        if type(value.get(field)) is not str or not value[field]:
            raise _invalid(f"{label}.{field} is invalid")
    _bounded_count(value.get("nobs"), f"{label}.nobs", minimum=1)
    _bounded_count(value.get("effective_sample"), f"{label}.effective_sample")
    if value["effective_sample"] > value["nobs"]:
        raise _invalid(f"{label}.effective_sample cannot exceed nobs")
    for field in ("converged", "finite_parameters"):
        if type(value.get(field)) is not bool:
            raise _invalid(f"{label}.{field} is invalid")
    parameters = value.get("parameters")
    _validate_finite_mapping(parameters, f"{label}.parameters", max_depth=2)
    details = value.get("convergence_details")
    if not isinstance(details, Mapping) or not details:
        raise _invalid(f"{label}.convergence_details is invalid")
    if set(details) == {"optimization_flag", "optimization_message"}:
        _bounded_count(
            details.get("optimization_flag"),
            f"{label}.convergence_details.optimization_flag",
            maximum=100,
        )
        if type(details.get("optimization_message")) is not str:
            raise _invalid(f"{label}.convergence_details.optimization_message is invalid")
    elif set(details) == {"mean", "variance_flag"}:
        _validate_finite_mapping(details.get("mean"), f"{label}.convergence_details.mean", max_depth=1)
        _bounded_count(
            details.get("variance_flag"),
            f"{label}.convergence_details.variance_flag",
            maximum=100,
        )
    else:
        raise _invalid(f"{label}.convergence_details fields are invalid")
    if "fit_statistics" in value:
        _validate_finite_mapping(value["fit_statistics"], f"{label}.fit_statistics", max_depth=1)


def _validate_finite_mapping(value: object, label: str, *, max_depth: int) -> None:
    if not isinstance(value, Mapping) or not value:
        raise _invalid(f"{label} is invalid")
    for key, item in value.items():
        if type(key) is not str or not key or len(key) > 200:
            raise _invalid(f"{label} contains an invalid key")
        if isinstance(item, Mapping):
            if max_depth <= 0:
                raise _invalid(f"{label}.{key} is nested too deeply")
            _validate_finite_mapping(item, f"{label}.{key}", max_depth=max_depth - 1)
        else:
            _finite_number(item, f"{label}.{key}")


def _validate_original_scale(value: object, label: str) -> None:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} is invalid")
    required = {
        "transform",
        "backtransform_method",
        "point_statistic",
        "point_or_median",
        "lower_bound",
        "upper_bound",
        "lower_quantile",
        "variance_available",
    }
    if set(value) != required:
        raise _invalid(f"{label} fields are invalid")
    for field in ("transform", "backtransform_method", "point_statistic"):
        if type(value.get(field)) is not str or not value[field]:
            raise _invalid(f"{label}.{field} is invalid")
    for field in ("point_or_median", "lower_bound", "upper_bound", "lower_quantile"):
        _finite_number(value.get(field), f"{label}.{field}")
    if float(value["lower_bound"]) > float(value["upper_bound"]):
        raise _invalid(f"{label} bounds are inconsistent")
    if not float(value["lower_bound"]) <= float(value["lower_quantile"]) <= float(value["upper_bound"]):
        raise _invalid(f"{label}.lower_quantile is outside bounds")
    if type(value.get("variance_available")) is not bool:
        raise _invalid(f"{label}.variance_available is invalid")


def _validate_frozen_spec(value: object, label: str) -> None:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} is invalid")
    required = {
        "mean_candidate_id",
        "mean_order",
        "mean_constant",
        "variance_candidate_id",
        "variance_model",
        "variance_order",
        "innovation_distribution",
        "resolved_strategy",
        "hold_back",
        "transform",
    }
    if set(value) != required:
        raise _invalid(f"{label} fields are invalid")
    for field in (
        "mean_candidate_id",
        "variance_candidate_id",
        "variance_model",
        "innovation_distribution",
        "resolved_strategy",
        "transform",
    ):
        if type(value.get(field)) is not str or not value[field]:
            raise _invalid(f"{label}.{field} is invalid")
    for field in ("mean_order", "variance_order"):
        order = value.get(field)
        if (
            not isinstance(order, list)
            or len(order) != 2
            or any(type(item) is not int or item < 0 or item > 100 for item in order)
        ):
            raise _invalid(f"{label}.{field} is invalid")
    if type(value.get("mean_constant")) is not bool:
        raise _invalid(f"{label}.mean_constant is invalid")
    _bounded_count(value.get("hold_back"), f"{label}.hold_back", maximum=1_000_000)


def _validate_next_forecast(value: object, label: str) -> None:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object")
    origin = value.get("forecast_origin")
    if not isinstance(origin, Mapping):
        raise _invalid(f"{label}.forecast_origin is invalid")
    for field in ("row_id", "time"):
        if type(origin.get(field)) is not str or not origin[field]:
            raise _invalid(f"{label}.forecast_origin.{field} is invalid")
    if value.get("target_label") != "next_observation":
        raise _invalid(f"{label}.target_label is invalid")
    if value.get("target_time") is not None and type(value.get("target_time")) is not str:
        raise _invalid(f"{label}.target_time is invalid")
    for field in (
        "conditional_mean",
        "conditional_variance",
        "conditional_volatility",
        "lower_bound",
        "upper_bound",
        "lower_quantile",
    ):
        _finite_number(value.get(field), f"{label}.{field}")
    if float(value["conditional_variance"]) <= 0.0:
        raise _invalid(f"{label}.conditional_variance must be positive")
    if float(value["conditional_volatility"]) <= 0.0:
        raise _invalid(f"{label}.conditional_volatility must be positive")
    if float(value["lower_bound"]) > float(value["upper_bound"]):
        raise _invalid(f"{label} bounds are inconsistent")
    if not float(value["lower_bound"]) <= float(value["lower_quantile"]) <= float(value["upper_bound"]):
        raise _invalid(f"{label}.lower_quantile is outside bounds")
    if type(value.get("model_scale")) is not str or not value["model_scale"]:
        raise _invalid(f"{label}.model_scale is invalid")
    _validate_original_scale(value.get("original_scale"), f"{label}.original_scale")
    _validate_frozen_spec(value.get("frozen_spec"), f"{label}.frozen_spec")
    _validate_refit_summary(value.get("refit_summary"), f"{label}.refit_summary")
    if value.get("warning") is not None and type(value.get("warning")) is not str:
        raise _invalid(f"{label}.warning is invalid")
    for field, expected in (
        ("fit_method", "full_sample_refit"),
        ("predictive_interval", "plugin_conditional"),
    ):
        if value.get(field) != expected:
            raise _invalid(f"{label}.{field} is invalid")
    if type(value.get("parameter_uncertainty_included")) is not bool:
        raise _invalid(f"{label}.parameter_uncertainty_included is invalid")


def _indexed_artifact_bindings(
    run_root: Path,
    artifact_refs: Mapping[str, str],
) -> dict[str, dict[str, str]]:
    index_path = run_root / "artifacts_index.json"
    if index_path.is_symlink():
        raise _invalid("artifact index path contains a symlink")
    try:
        index = read_json(index_path)
    except (OSError, ValueError, TypeError) as exc:
        raise _invalid("artifact index is unavailable or malformed") from exc
    if not isinstance(index, Mapping) or index.get("schema_version") != 1:
        raise _invalid("artifact index is invalid")
    records = index.get("artifacts")
    if not isinstance(records, list):
        raise _invalid("artifact index records are invalid")
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise _invalid("artifact index contains an invalid record")
        artifact_id = record.get("artifact_id")
        if type(artifact_id) is not str or artifact_id in by_id:
            raise _invalid("artifact index contains duplicate or invalid artifact IDs")
        by_id[artifact_id] = record

    run_root_resolved = run_root.resolve()
    bindings: dict[str, dict[str, str]] = {}
    for artifact_id, declared_path in artifact_refs.items():
        record = by_id.get(artifact_id)
        if record is None:
            raise _invalid(f"artifact {artifact_id} is not indexed")
        indexed_path = record.get("path")
        indexed_sha256 = record.get("sha256")
        if type(indexed_path) is not str or indexed_path != declared_path:
            raise _invalid(f"artifact {artifact_id} path is not index-bound")
        if (
            type(indexed_sha256) is not str
            or len(indexed_sha256) != 64
            or any(char not in "0123456789abcdef" for char in indexed_sha256)
        ):
            raise _invalid(f"artifact {artifact_id} sha256 is invalid")
        indexed_parts = indexed_path.replace("\\", "/").split("/")
        if (
            not indexed_path
            or indexed_path.startswith("/")
            or ".." in indexed_parts
            or "\x00" in indexed_path
        ):
            raise _invalid(f"artifact {artifact_id} path is unsafe")
        candidate = run_root
        for component in indexed_parts:
            candidate = candidate / component
            if candidate.is_symlink():
                raise _invalid(f"artifact {artifact_id} path contains a symlink")
        path = candidate.resolve()
        try:
            path.relative_to(run_root_resolved)
        except ValueError as exc:
            raise _invalid(f"artifact {artifact_id} escapes run root") from exc
        if not path.is_file():
            raise _invalid(f"artifact {artifact_id} file is missing")
        if sha256_file(path) != indexed_sha256:
            raise _invalid(f"artifact {artifact_id} content sha256 does not match index")
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError) as exc:
            raise _invalid(f"artifact {artifact_id} content is not valid JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("artifact_id") != artifact_id:
            raise _invalid(f"artifact {artifact_id} content identity is invalid")
        bindings[artifact_id] = {"path": indexed_path, "sha256": indexed_sha256}
    return bindings


def _artifact_backed_binding(
    run_root: Path,
    run_id: str,
    model_id: str,
    primary: dict[str, Any],
    inputs: list[str],
) -> dict[str, Any]:
    if "coefficients" in primary:
        raise _invalid("artifact-backed result cannot contain coefficients")
    if primary.get("model_type") != "time_series.arma_garch":
        raise _invalid("artifact-backed adapter model identity differs")
    if primary.get("model_id") != model_id or model_id != "arma_garch_1":
        raise _invalid("artifact-backed adapter model_id differs")
    status = primary.get("status")
    if type(status) is not str or not status or len(status) > 64:
        raise _invalid("artifact-backed result status is invalid")

    artifact_refs = _bounded_relative_artifact_refs(primary.get("artifact_refs"))
    missing_refs = sorted(_ARTIFACT_BACKED_REQUIRED_REFS - set(artifact_refs))
    if missing_refs:
        raise _invalid("artifact_refs missing: " + ", ".join(missing_refs))

    validation = primary.get("validation")
    if not isinstance(validation, Mapping):
        raise _invalid("artifact-backed validation must be an object")
    data_role = validation.get("data_role")
    if type(data_role) is not str or not data_role:
        raise _invalid("artifact-backed validation data_role is invalid")
    if type(validation.get("candidate_selection_used_validation")) is not bool:
        raise _invalid("artifact-backed validation selection flag is invalid")
    _validate_validation_metrics(validation.get("metrics"))
    acceptance = validation.get("acceptance")
    if not isinstance(acceptance, Mapping) or not acceptance:
        raise _invalid("artifact-backed validation acceptance is invalid")
    if set(acceptance) != {"overall_status", "model_fit_succeeded", "dimensions"}:
        raise _invalid("artifact-backed validation acceptance fields are invalid")
    overall_status = acceptance.get("overall_status")
    if type(overall_status) is not str or overall_status not in _ARMA_GARCH_ACCEPTANCE_STATUSES:
        raise _invalid("artifact-backed validation acceptance overall_status is invalid")
    if type(acceptance["model_fit_succeeded"]) is not bool:
        raise _invalid("artifact-backed validation acceptance model_fit_succeeded is invalid")
    dimensions = acceptance["dimensions"]
    if not isinstance(dimensions, Mapping) or set(dimensions) != _ARMA_GARCH_ACCEPTANCE_DIMENSIONS:
        raise _invalid("artifact-backed validation acceptance dimensions are invalid")
    for name, dimension in dimensions.items():
        if not isinstance(dimension, Mapping) or set(dimension) != {"status", "reasons", "evidence"}:
            raise _invalid(f"artifact-backed validation acceptance dimension {name} is invalid")
        status = dimension["status"]
        if type(status) is not str or status not in _ARMA_GARCH_ACCEPTANCE_STATUSES:
            raise _invalid(f"artifact-backed validation acceptance dimension {name} status is invalid")
        reasons = dimension["reasons"]
        if (
            not isinstance(reasons, list)
            or len(reasons) > 64
            or any(type(reason) is not str or not reason or len(reason) > 500 for reason in reasons)
        ):
            raise _invalid(f"artifact-backed validation acceptance dimension {name} reasons are invalid")
        if not isinstance(dimension["evidence"], Mapping):
            raise _invalid(f"artifact-backed validation acceptance dimension {name} evidence is invalid")

    child = primary.get("production_child")
    if not isinstance(child, Mapping):
        raise _invalid("artifact-backed production_child must be an object")
    exact_values = {
        "result_id": f"{model_id}:production-final",
        "result_role": "production_final_child",
        "parent_result_id": model_id,
        "does_not_overwrite_parent": True,
        "fit_scope": "all_available_observations",
        "validation_metrics_recomputed": False,
    }
    for key, expected in exact_values.items():
        if child.get(key) != expected:
            raise _invalid(f"artifact-backed production_child {key} is invalid")
    _validate_refit_summary(
        child.get("refit_summary"), "artifact-backed production_child.refit_summary"
    )
    _validate_next_forecast(
        child.get("next_forecast"), "artifact-backed production_child.next_forecast"
    )

    indexed_bindings = _indexed_artifact_bindings(run_root, artifact_refs)
    paths = {key: value["path"] for key, value in indexed_bindings.items()}
    hashes = {key: value["sha256"] for key, value in indexed_bindings.items()}

    return {
        "strategy": "artifact_backed_v1",
        "project_root": str(run_root.parent.parent.resolve()),
        "run_id": run_id,
        "model_id": model_id,
        "source_artifact_ids": inputs,
        "result_artifact_refs": dict(sorted(paths.items())),
        "result_artifact_sha256": dict(sorted(hashes.items())),
        "result_artifact_bindings": dict(sorted(indexed_bindings.items())),
        "result_artifact_refs_digest": sha256_canonical(dict(sorted(indexed_bindings.items()))),
        "production_child_id": child["result_id"],
        "production_child_digest": sha256_canonical(dict(child)),
        "validation_digest": sha256_canonical(dict(validation)),
    }


def _typed_packet_binding(
    run_root: Path,
    run_id: str,
    model_id: str,
    primary: dict[str, Any],
    inputs: list[str],
) -> dict[str, Any]:
    """Bind a pack-owned typed result packet without flattening it to OLS."""

    packet = primary.get("result")
    if not isinstance(packet, Mapping):
        raise _invalid("typed packet result must be an object")
    packet_model_type = packet.get("model_type")
    if type(packet_model_type) is not str or not packet_model_type:
        raise _invalid("typed packet model_type is invalid")
    result_identity = packet.get("result_identity")
    if type(result_identity) is not str or not result_identity:
        raise _invalid("typed packet result_identity is invalid")
    sample_fingerprint = primary.get("sample_fingerprint")
    producer_version = primary.get("producer_version")
    if type(sample_fingerprint) is not str or not sample_fingerprint:
        raise _invalid("typed packet sample_fingerprint is invalid")
    if type(producer_version) is not str or not producer_version:
        raise _invalid("typed packet producer_version is invalid")
    return {
        "strategy": "typed_packet_v1",
        "project_root": str(run_root.parent.parent.resolve()),
        "run_id": run_id,
        "model_id": model_id,
        "source_artifact_ids": inputs,
        "result_payload_ref": f"model_results/{model_id}.json",
        "packet_model_type": packet_model_type,
        "packet_digest": sha256_canonical(dict(packet)),
        "packet_result_identity": result_identity,
        "sample_fingerprint": sample_fingerprint,
        "producer_version": producer_version,
    }


def attach_result_binding(
    run_root: Path,
    run_id: str,
    model_id: str,
    primary: dict[str, Any],
    inputs: list[str],
    *,
    strategy_key: str | None = None,
    expected_model_type: str | tuple[str, ...] | None = None,
) -> None:
    """Attach a validated result binding without changing result semantics."""

    primary, inputs = _validate_common(run_root, run_id, model_id, primary, inputs)
    if strategy_key is None:
        raise _invalid("result family has no declared binding strategy")
    if type(strategy_key) is not str or not strategy_key.strip():
        raise _invalid("result binding strategy identity is invalid")
    if expected_model_type is None:
        raise _invalid("expected model identity is required")
    if type(expected_model_type) is str:
        expected_model_types = (expected_model_type,)
    elif type(expected_model_type) is tuple:
        expected_model_types = expected_model_type
    else:
        expected_model_types = ()
    if (
        not expected_model_types
        or any(type(model_type) is not str or not model_type.strip() for model_type in expected_model_types)
        or len(set(expected_model_types)) != len(expected_model_types)
    ):
        raise _invalid("expected model identity is invalid")
    if strategy_key == "typed_packet_v1":
        packet = primary.get("result")
        if not isinstance(packet, Mapping) or packet.get("model_type") not in expected_model_types:
            raise _invalid("typed packet model identity differs from handler")
    else:
        observed_model_type = primary.get("model_type")
        if observed_model_type not in expected_model_types:
            raise _invalid("result model identity differs from handler")
    adapter = _RESULT_BINDING_ADAPTERS.get(strategy_key)
    if adapter is None:
        raise _invalid("result family has no declared binding strategy")
    try:
        candidate_binding = adapter(run_root, run_id, model_id, primary, inputs)
    except ResultBindingError:
        raise
    except Exception as exc:
        raise _invalid("result binding adapter raised an unexpected exception") from exc
    if (
        not isinstance(candidate_binding, Mapping)
        or not candidate_binding
        or candidate_binding.get("strategy") != strategy_key
    ):
        raise _invalid("result binding adapter returned an invalid binding")
    binding = dict(candidate_binding)
    unsigned = dict(primary)
    unsigned["result_binding"] = binding
    try:
        payload_sha256 = _payload_digest(unsigned)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _invalid("result binding payload is not JSON-safe") from exc
    binding["payload_sha256"] = payload_sha256
    primary["result_binding"] = binding


register_result_binding_adapter(COEFFICIENT_RESULT_BINDING_KEY, _coefficient_binding)
register_result_binding_adapter("artifact_backed_v1", _artifact_backed_binding)
register_result_binding_adapter("typed_packet_v1", _typed_packet_binding)


__all__ = [
    "ResultBindingAdapter",
    "ResultBindingError",
    "COEFFICIENT_RESULT_BINDING_KEY",
    "attach_result_binding",
    "is_result_binding_adapter_registered",
    "register_result_binding_adapter",
]
