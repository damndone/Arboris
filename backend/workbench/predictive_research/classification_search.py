"""Deterministic, fail-closed bounded search for classification OOF trials."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import itertools
import json
import math
import re
import time
from typing import Any

from .classification_adapters import adapter_registry
from .contracts import ContractError


_HIGHER_IS_BETTER = frozenset({"accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"})
_LOWER_IS_BETTER = frozenset({"log_loss", "brier_score"})
_SEARCH_METRICS = _HIGHER_IS_BETTER | _LOWER_IS_BETTER
_SPLIT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_OOF_METRIC_BUNDLE_MAX_BYTES = 64 * 1024
_OOF_BUNDLE_FIELDS = frozenset(
    {
        "metrics",
        "confusion_matrix",
        "per_class",
        "threshold",
        "positive_class",
        "sample_scope",
        "row_count",
        "weight_sum",
        "averaging",
    }
)
_OOF_METRIC_FIELDS = frozenset(
    {
        "definition_version",
        "name",
        "status",
        "point_estimate",
        "positive_class",
        "threshold",
        "averaging",
        "sample_scope",
        "row_count",
        "weight_sum",
        "unweighted_denominator",
        "weighted_denominator",
        "effective_sample_size",
        "fold_distribution",
        "interval",
        "numerical_method",
        "inference_basis",
        "evaluation_design",
        "validation_level",
        "reason",
    }
)
_OOF_METRIC_RECORD_LIMIT = len(_SEARCH_METRICS)
_OOF_VECTOR_LIMIT = 256


@dataclass(frozen=True)
class BoundedSearchV1:
    candidates: tuple[str, ...]
    search_space: Mapping[str, Any]
    primary_metric: str
    max_trials: int
    max_seconds: int | float
    max_cpu_seconds: int | float
    seed: int
    status: str = "declared"

    def validate(self, *, allowed_parameters: set[str] | frozenset[str]) -> None:
        if not self.candidates or any(type(item) is not str or not item for item in self.candidates):
            raise ContractError("CLASSIFICATION_SEARCH_INVALID", "search candidates must be non-empty model identifiers")
        if len(set(self.candidates)) != len(self.candidates):
            raise ContractError("CLASSIFICATION_SEARCH_INVALID", "search candidates must be unique")
        if not isinstance(self.search_space, Mapping):
            raise ContractError("CLASSIFICATION_SEARCH_INVALID", "search_space must be a mapping")
        if type(self.max_trials) is not int or self.max_trials < 1:
            raise ContractError("CLASSIFICATION_SEARCH_BUDGET_INVALID", "max_trials must be a positive integer")
        for name, value in (("max_seconds", self.max_seconds), ("max_cpu_seconds", self.max_cpu_seconds)):
            if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ContractError("CLASSIFICATION_SEARCH_BUDGET_INVALID", f"{name} must be a positive finite number")
        if type(self.seed) is not int or self.seed < 0:
            raise ContractError("CLASSIFICATION_SEARCH_SEED_INVALID", "seed must be a non-negative integer")
        if self.primary_metric not in _SEARCH_METRICS:
            raise ContractError("CLASSIFICATION_SEARCH_METRIC_INVALID", self.primary_metric)
        unknown = set(self.search_space) - set(allowed_parameters)
        if unknown:
            raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN", f"unknown search parameters: {sorted(unknown)}")

    def validate_candidate(self, candidate: Mapping[str, Any], *, allowed_parameters: set[str] | frozenset[str]) -> None:
        if not isinstance(candidate, Mapping):
            raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_INVALID", "candidate parameters must be a mapping")
        unknown = set(candidate) - set(allowed_parameters)
        if unknown:
            raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN", f"unknown candidate parameters: {sorted(unknown)}")


EvaluateTrial = Callable[[str, dict[str, Any], int], Mapping[str, Any]]
Clock = Callable[[], float]


def _canonical_parameters(parameters: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        encoded = json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_INVALID", "trial parameters must be JSON-serializable and finite") from exc
    return dict(parameters), "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_parameter_value(name: str, value: Any, schema: Mapping[str, Any]) -> None:
    kind = schema.get("type")
    if kind == "integer":
        valid_type = type(value) is int
    elif kind == "number":
        valid_type = type(value) in {int, float} and not isinstance(value, bool)
    else:
        valid_type = True
    if not valid_type:
        raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_INVALID", f"parameter {name!r} has invalid type")
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_INVALID", f"parameter {name!r} must be finite")
    if ("minimum" in schema and value < schema["minimum"]) or ("maximum" in schema and value > schema["maximum"]):
        raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_OUT_OF_RANGE", f"parameter {name!r} is outside its adapter bounds")


def _validate_model_parameters(model_id: str, parameters: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    declaration = adapter_registry().get(model_id)
    if declaration is None:
        raise ContractError("CLASSIFICATION_ADAPTER_UNKNOWN", f"unknown classification adapter {model_id!r}")
    schema = declaration.parameter_schema
    unknown = set(parameters) - set(schema)
    if unknown:
        raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN", f"unknown parameters for {model_id!r}: {sorted(unknown)}")
    for name, value in parameters.items():
        _validate_parameter_value(name, value, schema[name])
    return _canonical_parameters(parameters)


def _prepare_parameter_space(search: BoundedSearchV1) -> tuple[tuple[str, ...], tuple[Sequence[Any], ...], int]:
    if not search.search_space:
        return (), (), 1
    keys = tuple(sorted(search.search_space))
    values: list[Sequence[Any]] = []
    combination_count = 1
    for key in keys:
        raw = search.search_space[key]
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise ContractError("CLASSIFICATION_SEARCH_SPACE_INVALID", f"search values for {key!r} must be a finite sequence")
        try:
            option_count = len(raw)
        except TypeError as exc:
            raise ContractError("CLASSIFICATION_SEARCH_SPACE_INVALID", f"search values for {key!r} must have a finite length") from exc
        if option_count < 1:
            raise ContractError("CLASSIFICATION_SEARCH_SPACE_INVALID", f"search values for {key!r} cannot be empty")
        combination_count *= option_count
        values.append(raw)
    return keys, tuple(values), combination_count


def _expand_parameters(search: BoundedSearchV1):
    keys, values, _ = _prepare_parameter_space(search)
    if not values:
        yield {}
        return
    for combination in itertools.product(*values):
        yield {key: value for key, value in zip(keys, combination, strict=True)}


def _validate_finite_metric(value: Any, *, metric: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_INVALID", f"OOF metric {metric!r} must be finite")
    return float(value)


def _json_bytes(value: Any, *, code: str, label: str) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(code, f"{label} must be JSON-serializable and finite") from exc


def _validate_metric_record(name: str, record: Mapping[str, Any], *, sample_scope: str) -> float | None:
    unknown = set(record) - _OOF_METRIC_FIELDS
    if unknown:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric record contains unknown fields")
    if "name" in record and record["name"] != name:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric record name does not match its key")
    if "status" in record and record["status"] not in {"computed", "undefined"}:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric record status is invalid")
    if "sample_scope" in record and record["sample_scope"] != sample_scope:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric record scope is invalid")
    if "evaluation_design" in record and record["evaluation_design"] != "cross_fitted_oof":
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric record design is invalid")
    for field in (
        "point_estimate",
        "threshold",
        "weight_sum",
        "unweighted_denominator",
        "weighted_denominator",
        "effective_sample_size",
    ):
        if field in record and record[field] is not None:
            if type(record[field]) not in {int, float} or isinstance(record[field], bool) or not math.isfinite(float(record[field])):
                raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", f"OOF metric field {field!r} is invalid")
    if "threshold" in record and record["threshold"] is not None and not 0 <= float(record["threshold"]) <= 1:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric threshold is invalid")
    for field in ("row_count",):
        if field in record and (type(record[field]) is not int or record[field] < 0):
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", f"OOF metric field {field!r} is invalid")
    for field in ("definition_version", "averaging", "numerical_method", "inference_basis", "validation_level"):
        if field in record and type(record[field]) is not str:
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", f"OOF metric field {field!r} is invalid")
    if "reason" in record and (type(record["reason"]) is not str or len(record["reason"]) > 512):
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric reason is invalid")
    if "fold_distribution" in record:
        folds = record["fold_distribution"]
        if not isinstance(folds, list) or len(folds) > _OOF_VECTOR_LIMIT:
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF fold distribution is invalid")
    if "interval" in record and record["interval"] is not None:
        interval = record["interval"]
        if not isinstance(interval, Mapping) or not set(interval).issubset({"lower", "upper", "level", "method"}):
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric interval is invalid")
    value = record.get("point_estimate")
    return None if value is None else _validate_finite_metric(value, metric=name)


def _validate_oof_metric_bundle(bundle: Any, *, metric: str) -> float:
    if not isinstance(bundle, Mapping):
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metrics must be a typed mapping")
    encoded = _json_bytes(bundle, code="CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", label="oof_metrics")
    if len(encoded) > _OOF_METRIC_BUNDLE_MAX_BYTES:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle exceeds the size limit")
    unknown = set(bundle) - _OOF_BUNDLE_FIELDS
    if unknown:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle contains unknown fields")
    if bundle.get("sample_scope", "development_oof") != "development_oof":
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle scope is invalid")
    if "threshold" in bundle and (type(bundle["threshold"]) not in {int, float} or isinstance(bundle["threshold"], bool) or not math.isfinite(float(bundle["threshold"])) or not 0 <= float(bundle["threshold"]) <= 1):
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle threshold is invalid")
    if "row_count" in bundle and (type(bundle["row_count"]) is not int or bundle["row_count"] < 0):
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle row count is invalid")
    if "weight_sum" in bundle and (type(bundle["weight_sum"]) not in {int, float} or isinstance(bundle["weight_sum"], bool) or not math.isfinite(float(bundle["weight_sum"])) or float(bundle["weight_sum"]) < 0):
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle weight sum is invalid")
    for field in ("positive_class", "averaging"):
        if field in bundle and field == "averaging" and type(bundle[field]) is not str:
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle averaging is invalid")

    metrics = bundle.get("metrics")
    if not isinstance(metrics, Mapping) or len(metrics) > _OOF_METRIC_RECORD_LIMIT or metric not in metrics:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle has no valid primary metric")
    primary_value: float | None = None
    for name, record in metrics.items():
        if type(name) is not str or name not in _SEARCH_METRICS or not isinstance(record, Mapping):
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF metric bundle contains an unknown metric")
        value = _validate_metric_record(name, record, sample_scope="development_oof")
        if name == metric:
            primary_value = value
    if primary_value is None:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_MISSING", f"OOF metric {metric!r} is missing")

    if "confusion_matrix" in bundle:
        matrix = bundle["confusion_matrix"]
        if not isinstance(matrix, Mapping) or not set(matrix).issubset({"labels", "values"}):
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF confusion matrix is invalid")
        labels = matrix.get("labels")
        values = matrix.get("values")
        if not isinstance(labels, list) or len(labels) > _OOF_VECTOR_LIMIT or not isinstance(values, list) or len(values) > _OOF_VECTOR_LIMIT:
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF confusion matrix dimensions are invalid")
        if any(not isinstance(row, list) or len(row) > _OOF_VECTOR_LIMIT for row in values):
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF confusion matrix rows are invalid")
    if "per_class" in bundle:
        per_class = bundle["per_class"]
        if not isinstance(per_class, Mapping) or len(per_class) > _OOF_VECTOR_LIMIT:
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF per-class metrics are invalid")
        for support in per_class.values():
            if not isinstance(support, Mapping) or set(support) != {"support", "predicted_support"} or any(type(support[field]) is not int or support[field] < 0 for field in support):
                raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID", "OOF per-class support is invalid")
    return primary_value


def _metric_value(result: Mapping[str, Any], metric: str) -> float:
    if "oof_metrics" in result:
        value = _validate_oof_metric_bundle(result["oof_metrics"], metric=metric)
        if "metric" in result and _validate_finite_metric(result["metric"], metric=metric) != value:
            raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_MISMATCH", "OOF metric sources disagree")
        return value
    if "metric" not in result:
        raise ContractError("CLASSIFICATION_SEARCH_OOF_METRIC_MISSING", f"OOF metric {metric!r} is missing")
    return _validate_finite_metric(result["metric"], metric=metric)


def _validate_oof_result(result: Mapping[str, Any], *, metric: str) -> float:
    if not isinstance(result, Mapping):
        raise ContractError("CLASSIFICATION_SEARCH_TRIAL_RESULT_INVALID", "trial result must be a mapping")
    if result.get("sample_scope") != "development_oof" or result.get("evaluation_design") != "cross_fitted_oof":
        raise ContractError("CLASSIFICATION_SEARCH_OOF_SCOPE_INVALID", "search trials must report cross-fitted development OOF")
    holdout_accessed = result.get("holdout_accessed", False)
    if type(holdout_accessed) is not bool:
        raise ContractError("CLASSIFICATION_SEARCH_HOLDOUT_FLAG_INVALID", "holdout_accessed must be a boolean")
    if holdout_accessed:
        raise ContractError("CLASSIFICATION_SEARCH_HOLDOUT_ACCESS", "search trials cannot access final holdout")
    split_hash = result.get("split_hash")
    if type(split_hash) is not str or _SPLIT_HASH_PATTERN.fullmatch(split_hash) is None:
        raise ContractError("CLASSIFICATION_SEARCH_SPLIT_IDENTITY_INVALID", "search trials must report a canonical sha256 split hash")
    return _metric_value(result, metric)


def _failure_reason(exc: Exception) -> dict[str, str]:
    if isinstance(exc, ContractError):
        return {
            "code": exc.code,
            "message": "typed classification search contract rejected the trial",
        }
    return {
        "code": "CLASSIFICATION_SEARCH_TRIAL_FAILED",
        "message": "classification search trial executor failed",
    }


def _base_receipt(search: BoundedSearchV1, *, trial_count: int) -> dict[str, Any]:
    return {
        "schema_version": "classification-search-receipt.v1",
        "status": "blocked",
        "selection_scope": "development_oof",
        "primary_metric": search.primary_metric,
        "max_trials": search.max_trials,
        "max_seconds": float(search.max_seconds),
        "max_cpu_seconds": float(search.max_cpu_seconds),
        "trials_declared": trial_count,
        "trials": [],
        "selected": None,
    }


def run_bounded_search(
    search: BoundedSearchV1,
    *,
    evaluate_trial: EvaluateTrial,
    monotonic_clock: Clock = time.monotonic,
    cpu_clock: Clock = time.process_time,
) -> dict[str, Any]:
    """Execute bounded parameter trials using a caller-supplied OOF evaluator."""

    if not callable(evaluate_trial):
        raise ContractError("CLASSIFICATION_SEARCH_EXECUTOR_INVALID", "evaluate_trial must be callable")
    model_schemas = {model_id: adapter_registry().get(model_id) for model_id in search.candidates}
    for model_id, declaration in model_schemas.items():
        if declaration is None:
            raise ContractError("CLASSIFICATION_ADAPTER_UNKNOWN", f"unknown classification adapter {model_id!r}")
    allowed = set().union(*(set(declaration.parameter_schema) for declaration in model_schemas.values() if declaration is not None))
    search.validate(allowed_parameters=allowed)
    _, _, parameter_count = _prepare_parameter_space(search)
    trial_count = parameter_count * len(search.candidates)
    receipt = _base_receipt(search, trial_count=trial_count)
    if trial_count > search.max_trials:
        receipt["reason_code"] = "CLASSIFICATION_SEARCH_TRIAL_BUDGET_EXCEEDED"
        return receipt

    # Validate every option before fitting, without materializing the Cartesian
    # product. The actual product is regenerated as a lazy iterator below.
    for model_id in search.candidates:
        declaration = model_schemas[model_id]
        assert declaration is not None
        if not search.search_space:
            search.validate_candidate({}, allowed_parameters=set(declaration.parameter_schema))
            _validate_model_parameters(model_id, {})
        else:
            for key in sorted(search.search_space):
                values = search.search_space[key]
                for value in values:
                    option = {key: value}
                    search.validate_candidate(option, allowed_parameters=set(declaration.parameter_schema))
                    _validate_model_parameters(model_id, option)

    started_wall = monotonic_clock()
    started_cpu = cpu_clock()
    split_hash: str | None = None
    successful: list[dict[str, Any]] = []
    trial_index = 0
    for model_id in search.candidates:
        for raw_parameters in _expand_parameters(search):
            elapsed_wall = monotonic_clock() - started_wall
            elapsed_cpu = cpu_clock() - started_cpu
            if elapsed_wall > float(search.max_seconds) or elapsed_cpu > float(search.max_cpu_seconds):
                receipt["reason_code"] = "CLASSIFICATION_SEARCH_BUDGET_EXCEEDED"
                receipt["elapsed_seconds"] = max(0.0, float(elapsed_wall))
                receipt["cpu_seconds"] = max(0.0, float(elapsed_cpu))
                return receipt
            parameters, parameter_hash = _validate_model_parameters(model_id, raw_parameters)
            trial: dict[str, Any] = {
                "trial_index": trial_index,
                "model_id": model_id,
                "parameters": parameters,
                "parameter_hash": parameter_hash,
                "seed": search.seed + trial_index,
                "sample_scope": "development_oof",
                "status": "failed",
                "failure_reason": None,
            }
            try:
                result = evaluate_trial(model_id, parameters, search.seed + trial_index)
                score = _validate_oof_result(result, metric=search.primary_metric)
                current_split_hash = result["split_hash"]
                if split_hash is None:
                    split_hash = current_split_hash
                elif split_hash != current_split_hash:
                    raise ContractError("CLASSIFICATION_SEARCH_SPLIT_MISMATCH", "all trials must use one immutable split")
                trial.update(
                    {
                        "status": "completed",
                        "failure_reason": None,
                        "metric": score,
                        "primary_metric": {
                            "name": search.primary_metric,
                            "status": "computed",
                            "point_estimate": score,
                        },
                        "split_hash": current_split_hash,
                        "evaluation_design": "cross_fitted_oof",
                    }
                )
                successful.append(trial)
            except Exception as exc:
                trial["failure_reason"] = _failure_reason(exc)
            receipt["trials"].append(trial)
            trial_index += 1
            elapsed_wall = monotonic_clock() - started_wall
            elapsed_cpu = cpu_clock() - started_cpu
            if trial["status"] != "completed":
                receipt["reason_code"] = "CLASSIFICATION_SEARCH_TRIAL_FAILED"
                return receipt
            if elapsed_wall > float(search.max_seconds) or elapsed_cpu > float(search.max_cpu_seconds):
                receipt["reason_code"] = "CLASSIFICATION_SEARCH_BUDGET_EXCEEDED"
                receipt["elapsed_seconds"] = max(0.0, float(elapsed_wall))
                receipt["cpu_seconds"] = max(0.0, float(elapsed_cpu))
                return receipt

    if not successful:
        receipt["reason_code"] = "CLASSIFICATION_SEARCH_NO_COMPLETED_TRIALS"
        return receipt
    ranked = sorted(
        successful,
        key=lambda trial: (
            -float(trial["metric"]) if search.primary_metric in _HIGHER_IS_BETTER else float(trial["metric"]),
            int(trial["trial_index"]),
        ),
    )
    best_by_model: dict[str, dict[str, Any]] = {}
    for trial in ranked:
        best_by_model.setdefault(str(trial["model_id"]), trial)
    receipt.update(
        {
            "status": "selected",
            "selected": ranked[0],
            "best_parameters_by_model": {
                model_id: dict(trial["parameters"])
                for model_id, trial in best_by_model.items()
            },
            "split_hash": split_hash,
            "trials_completed": len(successful),
            "elapsed_seconds": max(0.0, float(monotonic_clock() - started_wall)),
            "cpu_seconds": max(0.0, float(cpu_clock() - started_cpu)),
        }
    )
    return receipt


__all__ = ["BoundedSearchV1", "run_bounded_search"]
