"""Pure source, target, cluster and intent validation for v1.7.2."""

from __future__ import annotations

import math
import numbers
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set, Sized
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (
    ClusterPreflightResult,
    ComparisonTarget,
    IntentValidationResult,
    SourceRunContract,
    SourceValidationResult,
)
from .policy import OLSClusterPolicyV1, cluster_runtime_type, ols_cluster_policy_v1
from .recovery import RECOVERY_ACTION_REGISTRY, RecoveryAction, get_recovery_action

RECOVERY_ACTION_ID = "ols.use_clustered_covariance_v1"
_CONTRACT_VERSION_RE = re.compile(r"^ols_result_contract_v(\d+)$")
_NO_SIDE_EFFECTS = {
    "execution_key_created": False,
    "effect_created": False,
    "operation_record_created": False,
    "child_created": False,
}
_INVARIANTS = {
    "covariance_only": True,
    "cluster_field_is_group_vector_only": True,
    "wire_field": "entity_col",
    "formula_unchanged": True,
    "y_unchanged": True,
    "X_unchanged": True,
    "intercept_unchanged": True,
    "weights_unchanged": True,
    "analysis_row_set_unchanged": True,
    "analysis_row_order_unchanged": True,
    "point_estimation_unchanged": True,
    "coefficient_schema_unchanged": True,
}


def _diagnostic_action_id(action_id: Any) -> str:
    if type(action_id) is str and action_id:
        return action_id
    return "invalid_action_id"


def _source_result(
    *,
    valid: bool,
    code: str,
    evidence: Mapping[str, Any] | None = None,
) -> SourceValidationResult:
    return SourceValidationResult(
        valid=valid,
        status="pass" if valid else "fail",
        severity="info" if valid else "error",
        code=code,
        evidence=dict(evidence or {}),
        reason_codes=() if valid else (code,),
    )


def _registered_action() -> RecoveryAction | None:
    action = RECOVERY_ACTION_REGISTRY.get(RECOVERY_ACTION_ID)
    return action if isinstance(action, RecoveryAction) else None


def _default_operation_id() -> str:
    action = _registered_action()
    return action.operation_id if action is not None else "invalid.operation"


def _default_policy_version() -> str:
    action = _registered_action()
    return action.policy_version if action is not None else "invalid.policy"


def validate_source_contract(source: SourceRunContract) -> SourceValidationResult:
    """Validate source facts without reading or modifying any run state."""

    if not isinstance(source, SourceRunContract):
        return _source_result(valid=False, code="SOURCE_CONTRACT_UNSUPPORTED")
    if source.status != "completed":
        return _source_result(
            valid=False,
            code="SOURCE_NOT_COMPLETED",
            evidence={"status": source.status},
        )
    if (
        not source.analysis_row_ids
        or any(type(row_id) is not str or not row_id for row_id in source.analysis_row_ids)
        or len(set(source.analysis_row_ids)) != len(source.analysis_row_ids)
    ):
        return _source_result(valid=False, code="SOURCE_ANALYSIS_ROWS_UNSTABLE")
    if source.model != "ols":
        return _source_result(
            valid=False,
            code="SOURCE_MODEL_UNSUPPORTED",
            evidence={"model": source.model},
        )
    if source.covariance != "unadjusted":
        return _source_result(
            valid=False,
            code="SOURCE_COVARIANCE_UNSUPPORTED",
            evidence={"covariance": source.covariance},
        )
    if not source.result_artifact:
        return _source_result(valid=False, code="SOURCE_RESULT_ARTIFACT_MISSING")
    if not source.run_inputs:
        return _source_result(valid=False, code="SOURCE_RUN_INPUTS_MISSING")
    form = source.run_inputs.get("form")
    payload_model = form.get("model_type") if isinstance(form, Mapping) else None
    if payload_model != "ols":
        return _source_result(
            valid=False,
            code="SOURCE_MODEL_MISMATCH",
            evidence={"payload_model_type": payload_model},
        )
    form_has_covariance = isinstance(form, Mapping) and "covariance" in form
    form_covariance = form.get("covariance") if form_has_covariance else None
    top_level_present = "covariance" in source.run_inputs
    top_level_covariance = source.run_inputs.get("covariance")
    if form_has_covariance and form_covariance is None:
        if top_level_present and top_level_covariance is not None:
            return _source_result(
                valid=False,
                code="SOURCE_WIRE_COVARIANCE_CONFLICT",
                evidence={
                    "form_covariance": form_covariance,
                    "top_level_covariance": top_level_covariance,
                },
            )
        return _source_result(
            valid=False,
            code="SOURCE_WIRE_COVARIANCE_UNSUPPORTED",
            evidence={"wire_covariance": form_covariance},
        )
    if not form_has_covariance and not top_level_present:
        return _source_result(valid=False, code="SOURCE_WIRE_COVARIANCE_MISSING")
    if (
        form_has_covariance
        and top_level_present
        and form_covariance != top_level_covariance
    ):
        return _source_result(
            valid=False,
            code="SOURCE_WIRE_COVARIANCE_CONFLICT",
            evidence={
                "form_covariance": form_covariance,
                "top_level_covariance": top_level_covariance,
            },
        )
    wire_covariance = form_covariance if form_has_covariance else top_level_covariance
    if wire_covariance != "unadjusted":
        return _source_result(
            valid=False,
            code="SOURCE_WIRE_COVARIANCE_UNSUPPORTED",
            evidence={"wire_covariance": wire_covariance},
        )
    if not source.lineage:
        return _source_result(valid=False, code="SOURCE_LINEAGE_MISSING")
    if not source.contract_version:
        return _source_result(valid=False, code="SOURCE_CONTRACT_UNSUPPORTED")
    match = _CONTRACT_VERSION_RE.fullmatch(source.contract_version)
    if match is None or int(match.group(1)) < 1:
        return _source_result(
            valid=False,
            code="SOURCE_CONTRACT_UNSUPPORTED",
            evidence={"contract_version": source.contract_version},
        )
    if not source.result_ids:
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_MISSING")
    if any(type(result_id) is not str or not result_id for result_id in source.result_ids):
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_UNSTABLE")
    if len(set(source.result_ids)) != len(source.result_ids):
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_UNSTABLE")
    if "stable_result_ids" not in source.result_artifact:
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_MISSING")
    artifact_ids = source.result_artifact["stable_result_ids"]
    if not isinstance(artifact_ids, (list, tuple)):
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_UNSTABLE")
    if any(type(result_id) is not str or not result_id for result_id in artifact_ids):
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_UNSTABLE")
    if len(set(artifact_ids)) != len(artifact_ids):
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_UNSTABLE")
    if tuple(artifact_ids) != source.result_ids:
        return _source_result(valid=False, code="SOURCE_RESULT_IDS_UNSTABLE")
    return _source_result(
        valid=True,
        code="SOURCE_CONTRACT_SUPPORTED",
        evidence={
            "run_id": source.run_id,
            "model": source.model,
            "covariance": source.covariance,
            "wire_covariance": wire_covariance,
            "contract_version": source.contract_version,
            "result_ids": list(source.result_ids),
        },
    )


def _intent_result(
    *,
    valid: bool,
    code: str,
    action_id: str = RECOVERY_ACTION_ID,
    operation_id: str | None = None,
    source_validation: SourceValidationResult | None = None,
    cluster_preflight: ClusterPreflightResult | None = None,
    comparison_target: ComparisonTarget | None = None,
    canonical_patch: Mapping[str, Any] | None = None,
    wire_patch: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    invariants: Mapping[str, Any] | None = None,
    message: str = "",
    status: str | None = None,
    severity: str | None = None,
    reason_codes: Sequence[str] | None = None,
) -> IntentValidationResult:
    return IntentValidationResult(
        valid=valid,
        status=status if status is not None else ("pass" if valid else "fail"),
        severity=severity if severity is not None else ("info" if valid else "error"),
        code=code,
        action_id=action_id,
        operation_id=operation_id if operation_id is not None else _default_operation_id(),
        canonical_patch=dict(canonical_patch or {}),
        wire_patch=dict(wire_patch or {}),
        comparison_target=comparison_target,
        source_validation=source_validation,
        cluster_preflight=cluster_preflight,
        evidence=dict(evidence or {}),
        invariants=dict(invariants or {}),
        side_effects=dict(_NO_SIDE_EFFECTS),
        reason_codes=(
            tuple(reason_codes)
            if reason_codes is not None
            else (() if valid else (code,))
        ),
        message=message,
    )


def _safe_action_operation_id(action: Any) -> str:
    if isinstance(action, RecoveryAction) and type(action.operation_id) is str and action.operation_id:
        return action.operation_id
    return _default_operation_id()


def _action_metadata_is_supported(action_id: str, action: Any) -> bool:
    registered = _registered_action() if action_id == RECOVERY_ACTION_ID else None
    if not isinstance(action, RecoveryAction) or registered is None or action != registered:
        return False
    if not action.covariance_only:
        return False
    if type(action.required_fields) is not tuple or len(action.required_fields) != 1:
        return False
    required_field = action.required_fields[0]
    if required_field == "covariance":
        return False
    if not isinstance(action.field_mapping, Mapping) or not action.field_mapping:
        return False
    wire_field = action.field_mapping.get(required_field)
    return type(wire_field) is str and bool(wire_field) and wire_field != "covariance"


def resolve_comparison_target(
    source: SourceRunContract,
    requested_result_id: str | None,
) -> ComparisonTarget | IntentValidationResult:
    """Resolve exactly one stable result ID; labels never participate in lookup."""

    source_validation = validate_source_contract(source)
    if not source_validation.valid:
        return _intent_result(
            valid=False,
            code=source_validation.code,
            source_validation=source_validation,
        )

    primary = source.primary_estimand
    if primary is not None:
        result_id = primary.get("result_id")
        if type(result_id) is str and result_id in source.result_ids:
            label = primary.get("label", source.result_labels.get(result_id))
            role = primary.get("role", "primary")
            if type(role) is str and role:
                return ComparisonTarget(
                    result_id=result_id,
                    role=role,
                    label=label if isinstance(label, str) else None,
                    resolution_source="source_primary_estimand",
                )
        return _intent_result(
            valid=False,
            code="COMPARISON_TARGET_UNKNOWN",
            source_validation=source_validation,
            evidence={"primary_estimand": dict(primary)},
        )

    if requested_result_id is None:
        return _intent_result(
            valid=False,
            code="COMPARISON_TARGET_REQUIRED",
            source_validation=source_validation,
        )
    if type(requested_result_id) is not str or requested_result_id not in source.result_ids:
        return _intent_result(
            valid=False,
            code="COMPARISON_TARGET_UNKNOWN",
            source_validation=source_validation,
            evidence={"requested_result_id": requested_result_id},
        )
    return ComparisonTarget(
        result_id=requested_result_id,
        role="coefficient",
        label=source.result_labels.get(requested_result_id),
        resolution_source="user_exact_result_id",
    )


def _schema_columns(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    columns = schema.get("columns")
    if isinstance(columns, Mapping):
        return columns
    if isinstance(columns, (list, tuple)):
        return {name: {} for name in columns if isinstance(name, str)}
    fields = schema.get("fields")
    if isinstance(fields, Mapping):
        return fields
    if isinstance(fields, (list, tuple)):
        return {name: {} for name in fields if isinstance(name, str)}
    return schema


def _declared_dtype(metadata: Any) -> str | None:
    if isinstance(metadata, Mapping):
        for key in ("dtype", "data_type", "type", "kind"):
            if key in metadata:
                metadata = metadata[key]
                break
    if not isinstance(metadata, str):
        return None
    value = metadata.strip().lower()
    if value in {"category", "categorical"}:
        return "category"
    if value in {"bool", "boolean"}:
        return "bool"
    if value in {"float", "float16", "float32", "float64", "double", "decimal"}:
        return "float"
    if value.startswith(("int", "uint")) or value in {"integer", "long"}:
        return "integer"
    if value in {"str", "string", "unicode", "object"}:
        return "string"
    return value


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        pandas_missing = pd.isna(value)
        if type(pandas_missing) is bool:
            return pandas_missing
        if getattr(pandas_missing, "ndim", 1) == 0:
            return bool(pandas_missing)
    except (TypeError, ValueError):
        pass
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False


def _runtime_dtype(value: Any) -> str | None:
    return cluster_runtime_type(value)


def _canonical_cluster_identity(value: Any) -> tuple[str, Any]:
    runtime_type = _runtime_dtype(value)
    if runtime_type == "integer":
        return ("integer", int(value))
    if runtime_type == "string":
        return ("string", unicodedata.normalize("NFC", value))
    return (runtime_type or type(value).__name__, value)


def _is_vector_container(value: Any) -> bool:
    """Accept ordered one-dimensional containers without splitting scalar text."""

    try:
        if value is None or isinstance(value, (str, bytes, bytearray, Mapping, Set)):
            return False
        if not isinstance(value, Sized) or not isinstance(value, Iterable):
            return False
        len(value)
        iter(value)
        ndim = getattr(value, "ndim", None)
        if ndim is not None and ndim != 1:
            return False
        shape = getattr(value, "shape", None)
        if shape is not None and len(shape) != 1:
            return False
    except Exception:
        return False
    return True


def _vector_values(value: Any) -> tuple[Any, ...] | None:
    if not _is_vector_container(value):
        return None
    try:
        return tuple(value)
    except Exception:
        return None


def _safe_sequence_length(value: Any) -> int:
    values = _vector_values(value)
    return len(values) if values is not None else 0


def _cluster_result(
    *,
    source: SourceRunContract,
    cluster_variable: str,
    valid: bool,
    status: str,
    severity: str,
    code: str,
    row_count: int,
    missing_count: int = 0,
    cluster_count: int = 0,
    singleton_cluster_count: int = 0,
    all_singleton_clusters: bool = False,
    value_type: str | None = None,
    reason_codes: Sequence[str] = (),
    evidence: Mapping[str, Any] | None = None,
) -> ClusterPreflightResult:
    return ClusterPreflightResult(
        valid=valid,
        status=status,
        severity=severity,
        code=code,
        cluster_variable=cluster_variable if cluster_variable else "<empty>",
        wire_field="entity_col",
        cluster_count=cluster_count,
        row_count=row_count,
        missing_count=missing_count,
        singleton_cluster_count=singleton_cluster_count,
        all_singleton_clusters=all_singleton_clusters,
        value_type=value_type,
        reason_codes=tuple(reason_codes) if reason_codes else ((code,) if not valid else ()),
        evidence={
            "cluster_variable": cluster_variable,
            "wire_field": "entity_col",
            "row_count": row_count,
                "source_run_id": source.run_id if isinstance(source, SourceRunContract) else None,
            **dict(evidence or {}),
        },
        invariants=dict(_INVARIANTS),
    )


def preflight_cluster_variable(
    source: SourceRunContract,
    *,
    cluster_variable: str,
    cluster_values: Sequence[Any],
    model_row_ids: Sequence[str],
    policy: OLSClusterPolicyV1 = ols_cluster_policy_v1,
) -> ClusterPreflightResult:
    """Check an exact, row-aligned one-way covariance group vector."""

    source_validation = validate_source_contract(source)
    if not source_validation.valid:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable if isinstance(cluster_variable, str) else "<invalid>",
            valid=False,
            status="fail",
            severity="error",
            code=source_validation.code,
            row_count=_safe_sequence_length(model_row_ids),
        )
    cluster_value_vector = _vector_values(cluster_values)
    if cluster_value_vector is None:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable if isinstance(cluster_variable, str) else "<invalid>",
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_VALUES_INVALID",
            row_count=_safe_sequence_length(model_row_ids),
            evidence={"received_type": type(cluster_values).__name__},
        )
    model_row_id_vector = _vector_values(model_row_ids)
    if model_row_id_vector is None:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable if isinstance(cluster_variable, str) else "<invalid>",
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_ROW_IDS_INVALID",
            row_count=0,
            evidence={"received_type": type(model_row_ids).__name__},
        )
    cluster_values = cluster_value_vector
    normalized_row_ids: list[str] = []
    for index, row_id in enumerate(model_row_id_vector):
        invalid_element = False
        try:
            invalid_element = not isinstance(row_id, str) or not bool(row_id)
            normalized_row_id = str(row_id) if not invalid_element else ""
            invalid_element = invalid_element or not normalized_row_id
        except Exception:
            invalid_element = True
            normalized_row_id = ""
        if invalid_element:
            return _cluster_result(
                source=source,
                cluster_variable=cluster_variable if isinstance(cluster_variable, str) else "<invalid>",
                valid=False,
                status="fail",
                severity="error",
                code="CLUSTER_ROW_IDS_INVALID",
                row_count=len(model_row_id_vector),
                evidence={
                    "row_count": len(model_row_id_vector),
                    "invalid_position": index,
                    "invalid_element_type": type(row_id).__name__,
                    "received_type": type(model_row_ids).__name__,
                },
            )
        normalized_row_ids.append(normalized_row_id)
    model_row_ids = tuple(normalized_row_ids)
    if not isinstance(policy, OLSClusterPolicyV1):
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable if isinstance(cluster_variable, str) else "<invalid>",
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_POLICY_INVALID",
            row_count=len(model_row_ids),
            evidence={"policy_error": "expected OLSClusterPolicyV1"},
        )
    if type(cluster_variable) is not str or not cluster_variable:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable if isinstance(cluster_variable, str) else "<invalid>",
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_VARIABLE_REQUIRED",
            row_count=len(model_row_ids),
        )
    columns = _schema_columns(source.dataset_schema)
    if cluster_variable not in columns:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_VARIABLE_NOT_FOUND",
            row_count=len(model_row_ids),
            evidence={"schema_columns": list(columns)},
        )
    expected_rows = tuple(source.analysis_row_ids)
    actual_rows = tuple(model_row_ids)
    if not expected_rows or actual_rows != expected_rows or len(cluster_values) != len(actual_rows):
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code=("SOURCE_ANALYSIS_ROWS_MISSING" if not expected_rows else "CLUSTER_ROW_ALIGNMENT_MISMATCH"),
            row_count=len(actual_rows),
            evidence={"expected_row_ids": list(expected_rows), "actual_row_ids": list(actual_rows)},
        )
    missing_positions: list[int] = []
    for index, value in enumerate(cluster_values):
        try:
            is_missing = _is_missing(value)
        except Exception as exc:
            return _cluster_result(
                source=source,
                cluster_variable=cluster_variable,
                valid=False,
                status="fail",
                severity="error",
                code="CLUSTER_VALUES_UNINSPECTABLE",
                row_count=len(actual_rows),
                evidence={
                    "position": index,
                    "error_type": type(exc).__name__,
                },
            )
        if is_missing:
            missing_positions.append(index)
    if missing_positions:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_VARIABLE_MISSING_VALUES",
            row_count=len(actual_rows),
            missing_count=len(missing_positions),
            evidence={"missing_positions": missing_positions},
        )
    declared = _declared_dtype(columns[cluster_variable])
    runtime_types: set[str | None] = set()
    for index, value in enumerate(cluster_values):
        try:
            runtime_types.add(_runtime_dtype(value))
        except Exception as exc:
            return _cluster_result(
                source=source,
                cluster_variable=cluster_variable,
                valid=False,
                status="fail",
                severity="error",
                code="CLUSTER_VALUES_UNINSPECTABLE",
                row_count=len(actual_rows),
                evidence={
                    "position": index,
                    "error_type": type(exc).__name__,
                    "inspection_stage": "runtime_dtype",
                },
            )
    if None in runtime_types or "bool" in runtime_types or "float" in runtime_types:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_TYPE_UNSUPPORTED",
            row_count=len(actual_rows),
            value_type=declared,
            evidence={"declared_dtype": declared, "runtime_types": sorted(str(item) for item in runtime_types)},
        )
    if len(runtime_types) > 1:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_TYPE_MIXED",
            row_count=len(actual_rows),
            value_type=declared,
            evidence={"declared_dtype": declared, "runtime_types": sorted(runtime_types)},
        )
    runtime = next(iter(runtime_types))
    if declared in {"bool", "float"} or declared not in {None, "integer", "string", "category"}:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_TYPE_UNSUPPORTED",
            row_count=len(actual_rows),
            value_type=declared,
            evidence={"declared_dtype": declared, "runtime_type": runtime},
        )
    if declared in {"integer", "string"} and runtime != declared:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_TYPE_UNSUPPORTED",
            row_count=len(actual_rows),
            value_type=declared,
            evidence={"declared_dtype": declared, "runtime_type": runtime},
        )
    value_type = "category" if declared == "category" else runtime
    counts: Counter[tuple[str, Any]] = Counter()
    for index, value in enumerate(cluster_values):
        try:
            identity = _canonical_cluster_identity(value)
            counts[identity] += 1
        except Exception as exc:
            return _cluster_result(
                source=source,
                cluster_variable=cluster_variable,
                valid=False,
                status="fail",
                severity="error",
                code="CLUSTER_VALUES_UNINSPECTABLE",
                row_count=len(actual_rows),
                evidence={
                    "position": index,
                    "error_type": type(exc).__name__,
                    "inspection_stage": "cluster_identity",
                },
            )
    cluster_count = len(counts)
    singleton_count = sum(count == 1 for count in counts.values())
    all_singleton = cluster_count > 0 and singleton_count == cluster_count
    if cluster_count < policy.hard_min_cluster_count:
        return _cluster_result(
            source=source,
            cluster_variable=cluster_variable,
            valid=False,
            status="fail",
            severity="error",
            code="CLUSTER_COUNT_TOO_LOW",
            row_count=len(actual_rows),
            cluster_count=cluster_count,
            singleton_cluster_count=singleton_count,
            all_singleton_clusters=all_singleton,
            value_type=value_type,
            evidence={"hard_min_cluster_count": policy.hard_min_cluster_count},
        )
    reason_codes: list[str] = []
    if cluster_count < policy.warning_cluster_count_below:
        reason_codes.append("CLUSTER_COUNT_WARNING")
    if all_singleton and policy.all_singleton_clusters == "warning":
        reason_codes.append("CLUSTER_ALL_SINGLETONS")
    if reason_codes:
        status = "warning"
        severity = "warning"
        code = reason_codes[-1] if all_singleton and len(reason_codes) == 1 else "CLUSTER_PREFLIGHT_WARNING"
    else:
        status = "pass"
        severity = "info"
        code = "CLUSTER_PREFLIGHT_PASS"
    return _cluster_result(
        source=source,
        cluster_variable=cluster_variable,
        valid=True,
        status=status,
        severity=severity,
        code=code,
        row_count=len(actual_rows),
        cluster_count=cluster_count,
        singleton_cluster_count=singleton_count,
        all_singleton_clusters=all_singleton,
        value_type=value_type,
        reason_codes=reason_codes,
        evidence={
            "declared_dtype": declared,
            "runtime_type": runtime,
            "singleton_cluster_count": singleton_count,
            "all_singleton_clusters": all_singleton,
            "policy_version": _default_policy_version(),
            "one_way_only": policy.one_way_only,
        },
    )


def validate_clustered_intent(
    source: SourceRunContract,
    *,
    action_id: str,
    patch: Mapping[str, Any],
    requested_result_id: str | None,
    cluster_values: Sequence[Any],
    model_row_ids: Sequence[str],
    policy: OLSClusterPolicyV1 = ols_cluster_policy_v1,
) -> IntentValidationResult:
    """Validate and canonicalize one untrusted covariance-only intent."""

    diagnostic_action_id = _diagnostic_action_id(action_id)
    action = get_recovery_action(action_id)
    if action is None:
        return _intent_result(
            valid=False,
            code="RECOVERY_ACTION_UNSUPPORTED",
            action_id=diagnostic_action_id,
        )
    if not _action_metadata_is_supported(action_id, action):
        return _intent_result(
            valid=False,
            code="RECOVERY_ACTION_METADATA_INVALID",
            action_id=diagnostic_action_id,
            operation_id=_safe_action_operation_id(action),
        )
    operation_id = action.operation_id
    required_field = action.required_fields[0]
    wire_field = action.field_mapping[required_field]
    if not isinstance(patch, Mapping):
        return _intent_result(
            valid=False,
            code="INTENT_PATCH_NOT_COVARIANCE_ONLY",
            action_id=action_id,
            operation_id=operation_id,
        )
    allowed_fields = {"covariance", required_field}
    if set(patch) != allowed_fields:
        return _intent_result(
            valid=False,
            code="INTENT_PATCH_NOT_COVARIANCE_ONLY",
            action_id=action_id,
            operation_id=operation_id,
            evidence={"received_fields": sorted(str(field) for field in patch)},
        )
    covariance_patch = patch.get("covariance")
    if covariance_patch != action.target_covariance:
        return _intent_result(
            valid=False,
            code="COVARIANCE_DIRECTION_UNSUPPORTED",
            action_id=action_id,
            operation_id=operation_id,
            evidence={"requested_covariance": covariance_patch, "target_covariance": action.target_covariance},
        )
    source_validation = validate_source_contract(source)
    if not source_validation.valid:
        return _intent_result(
            valid=False,
            code=source_validation.code,
            action_id=action_id,
            operation_id=operation_id,
            source_validation=source_validation,
        )
    if source.model != action.allowed_model or source.covariance != action.source_covariance:
        return _intent_result(
            valid=False,
            code="RECOVERY_ACTION_SOURCE_MISMATCH",
            action_id=action_id,
            operation_id=operation_id,
            source_validation=source_validation,
            evidence={"model": source.model, "covariance": source.covariance},
        )
    target = resolve_comparison_target(source, requested_result_id)
    if isinstance(target, IntentValidationResult):
        return replace(target, action_id=action_id, operation_id=operation_id)
    cluster_variable = patch.get(required_field)
    if type(cluster_variable) is not str or not cluster_variable:
        return _intent_result(
            valid=False,
            code="CLUSTER_VARIABLE_REQUIRED",
            action_id=action_id,
            operation_id=operation_id,
            source_validation=source_validation,
            comparison_target=target,
        )
    cluster = preflight_cluster_variable(
        source,
        cluster_variable=cluster_variable,
        cluster_values=cluster_values,
        model_row_ids=model_row_ids,
        policy=policy,
    )
    if not cluster.valid:
        return _intent_result(
            valid=False,
            code=cluster.code,
            action_id=action_id,
            operation_id=operation_id,
            source_validation=source_validation,
            comparison_target=target,
            cluster_preflight=cluster,
        )
    canonical_patch = {"covariance": action.target_covariance, required_field: cluster_variable}
    wire_patch = {
        "covariance": action.target_covariance,
        wire_field: cluster_variable,
    }
    return _intent_result(
        valid=True,
        code="INTENT_VALID",
        action_id=action_id,
        operation_id=operation_id,
        source_validation=source_validation,
        comparison_target=target,
        cluster_preflight=cluster,
        canonical_patch=canonical_patch,
        wire_patch=wire_patch,
        invariants=cluster.invariants,
        evidence={
            "policy_version": action.policy_version,
            "field_mapping": dict(action.field_mapping),
        },
        status=cluster.status,
        severity=cluster.severity,
        reason_codes=cluster.reason_codes,
    )
