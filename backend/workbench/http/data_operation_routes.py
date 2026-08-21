"""Manual typed data-operation endpoints for the V11 cast vertical slice."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
import pandas as pd
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..artifacts import read_json

from ..agent.chains import ChainHeadConflict, ensure_chain_root
from ..agent.events import AgentEventStream
from ..agent.operations import (
    OperationRecordStore,
    OperationRecordTransitionError,
    OperationRegistry,
    OperationValidationError,
)
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..agent.risk import (
    RiskAuthorizationError,
    RiskAuthorizationExpired,
    RiskAuthorizationReplay,
    RiskAuthorizationRequired,
    RiskAuthorizationStore,
    RiskAuthorizationStale,
)
from ..agent.session import JsonlSessionRepository
from ..api_errors import WorkbenchAPIError
from ..data_operations import (
    DataCastItem,
    DataColumnCastSpecV1,
    DataColumnCastValidationError,
    DataMetadataUnavailableError,
    DataColumnsCastSpecV1,
    FeatureRecipeOperationSpecV1,
    DataTransformSpecV1,
    apply_data_column_cast,
    apply_data_columns_cast,
    apply_metadata_mutation,
    apply_data_transform,
    apply_feature_recipe_operation,
    data_operation_transaction,
    preflight_data_operation,
    preview_data_column_cast,
    preview_data_columns_cast,
    preview_feature_recipe,
    preview_data_transform,
    preview_metadata_mutation,
    read_metadata_mutation_record,
    resolve_data_column_cast_context,
    resolve_metadata_registry,
    _read_frame,
    _resolve_source,
)
from ..data_profile import DatasetRefV1, build_data_profile
from ..metadata import build_metadata_loss_manifest
from ..metadata import MetadataMutationSpecV1
from ..code_execution import (
    MAX_CODE_CHARS,
    CodeExecuteSpecV1,
    CodeExecuteValidationError,
    NondeterministicCodeError,
    preview_code_execute,
)
from ..figure_context import FigureContextError, resolve_figure_ai_context
from ..sandbox import SandboxUnavailableError

router = APIRouter()


def _public_data_operation_manifest() -> dict[str, Any]:
    """Return the package-owned descriptor projection without executing code."""

    from ..data_operation_manifest import build_data_operation_manifest

    manifest = build_data_operation_manifest()
    if hasattr(manifest, "to_dict"):
        payload = manifest.to_dict()
    elif isinstance(manifest, dict):
        payload = dict(manifest)
    else:
        raise TypeError("data operation manifest must expose a JSON projection")
    if not isinstance(payload.get("operations"), list):
        raise ValueError("data operation manifest has no bounded operations projection")
    return payload


def _request_sha256(body: BaseModel, *, exclude: set[str] | None = None) -> str:
    payload = body.model_dump(
        mode="json",
        exclude_none=True,
        exclude_unset=True,
        exclude=exclude or set(),
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _options_sha256(body: BaseModel, *, exclude: set[str] | None = None) -> str:
    return _request_sha256(
        body,
        exclude={
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
            "preview_fingerprint",
            "session_id",
            *(exclude or set()),
        },
    )


def _data_consumer_catalog_digest() -> str:
    from ..data_operation_manifest import build_data_consumer_runtime_adapter

    try:
        return build_data_consumer_runtime_adapter().catalog_digest
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_CONSUMER_RUNTIME_UNAVAILABLE",
            message="The server-owned data-consumer catalog is unavailable.",
            details={"reason": str(exc)},
        ) from exc


def _preview_payload(body: BaseModel, preview: Any) -> dict[str, Any]:
    payload = _bounded_data_consumer_value(preview.to_dict())
    if not isinstance(payload, dict):  # pragma: no cover - typed preview invariant
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_PREVIEW_UNAVAILABLE",
            message="The data operation preview is not a typed object.",
            details={},
        )
    payload["request_sha256"] = _request_sha256(body)
    payload["options_sha256"] = _options_sha256(body)
    payload["catalog_digest"] = _data_consumer_catalog_digest()
    operation_id = payload.get("operation_id")
    if operation_id == "code.execute" and payload.get("status") == "blocked":
        payload.pop("error", None)
        payload["reason_code"] = "CODE_EXECUTION_BLOCKED"
    if isinstance(payload.get("method"), str) and payload["method"]:
        payload["evidence_method"] = payload["method"]
    elif operation_id == "data.metadata.update":
        payload["evidence_method"] = "metadata_update"
    elif operation_id == "data.feature_recipe":
        payload["evidence_method"] = "feature_recipe"
    elif isinstance(operation_id, str) and operation_id.startswith("data."):
        payload["evidence_method"] = operation_id
    return payload


def _confirm_preview_payload(body: BaseModel, preview: Any) -> dict[str, Any]:
    payload = _bounded_data_consumer_value(preview.to_dict())
    if not isinstance(payload, dict):  # pragma: no cover - typed preview invariant
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_PREVIEW_UNAVAILABLE",
            message="The data operation preview is not a typed object.",
            details={},
        )
    payload["request_sha256"] = _request_sha256(
        body,
        exclude={"preview_fingerprint", "session_id"},
    )
    payload["options_sha256"] = _options_sha256(body)
    payload["catalog_digest"] = _data_consumer_catalog_digest()
    operation_id = payload.get("operation_id")
    if isinstance(payload.get("method"), str) and payload["method"]:
        payload["evidence_method"] = payload["method"]
    elif operation_id == "data.metadata.update":
        payload["evidence_method"] = "metadata_update"
    elif operation_id == "data.feature_recipe":
        payload["evidence_method"] = "feature_recipe"
    elif isinstance(operation_id, str) and operation_id.startswith("data."):
        payload["evidence_method"] = operation_id
    return payload


_DATA_CONSUMER_SAFE_EFFECT_FIELDS = frozenset(
    {
        "execution_key",
        "operation_id",
        "record_id",
        "artifact_id",
        "metadata_artifact_id",
        "recipe_artifact_id",
        "child_node_id",
        "group_manifest_id",
    }
)
_DATA_CONSUMER_GROUP_ARTIFACT_FIELDS = frozenset(
    {
        "execution_key",
        "artifact_id",
        "metadata_artifact_id",
        "recipe_artifact_id",
        "child_node_id",
        "group_manifest_id",
    }
)


def _is_bounded_data_consumer_key(key: object) -> bool:
    normalized = "".join(character.lower() for character in str(key) if character.isalnum())
    return not (
        normalized
        in {
            "path",
            "file",
            "files",
            "rows",
            "rawrows",
            "filename",
            "filenames",
            "rawdata",
            "rawpayload",
            "stdout",
            "stderr",
        }
        or normalized.endswith("path")
        or normalized.endswith("filename")
        or normalized.endswith("rows")
        or normalized.startswith("raw")
    )


def _bounded_data_consumer_value(value: Any) -> Any:
    """Strip filesystem/raw-data fields before a value crosses the central API."""

    if isinstance(value, dict):
        return {
            str(key): _bounded_data_consumer_value(nested)
            for key, nested in value.items()
            if _is_bounded_data_consumer_key(key)
        }
    if isinstance(value, list):
        return [_bounded_data_consumer_value(nested) for nested in value]
    return value


_DATA_CONSUMER_SPEC_FIELDS = frozenset(
    {
        "operation_id",
        "operation_version",
        "source_run_id",
        "source_node_id",
        "source_artifact_id",
        "secondary_run_id",
        "secondary_node_id",
        "secondary_artifact_id",
        "column",
        "target_dtype",
        "output_format",
    }
)
_DATA_CONSUMER_RECIPE_FIELDS = frozenset(
    {
        "recipe_id",
        "operation_id",
        "operation_version",
        "inputs",
        "outputs",
        "output_types",
        "fit_scope",
        "missing_policy",
        "outlier_policy",
    }
)
_DATA_CONSUMER_CAST_FIELDS = frozenset({"column", "target_dtype"})
_DATA_CONSUMER_PROPOSAL_FIELDS = frozenset(
    {
        "record_type",
        "proposal_id",
        "operation_id",
        "operation_version",
        "revision",
        "fingerprint",
        "status",
    }
)
_DATA_CONSUMER_CONFIRMATION_FIELDS = frozenset(
    {
        "record_type",
        "proposal_id",
        "operation_id",
        "operation_version",
        "revision",
        "fingerprint",
        "actor_type",
        "status",
    }
)
_DATA_CONSUMER_EVIDENCE_FIELDS = frozenset(
    {
        "method",
        "record_id",
        "operation_id",
        "execution_key",
        "child_node_id",
        "artifact_id",
        "metadata_artifact_id",
        "recipe_artifact_id",
        "group_manifest_id",
        "source_sha256",
        "secondary_source_sha256",
        "preview_fingerprint",
        "metadata_revision",
        "weight",
        "weight_consumed",
        "weight_sum",
        "group_count",
    }
)
_DATA_CONSUMER_WEIGHT_FIELDS = frozenset({"column", "kind"})
_DATA_CONSUMER_RECORD_FIELDS = frozenset(
    {
        "record_type",
        "record_id",
        "operation_id",
        "operation_version",
        "proposal_id",
        "proposal_revision",
        "proposal_fingerprint",
        "actor_type",
        "status",
        "target",
        "execution",
        "outputs",
        "diff_ref",
        "verification",
        "effect_status",
        "projection_status",
        "created_at",
        "updated_at",
    }
)
_DATA_CONSUMER_TARGET_FIELDS = frozenset(
    {
        "run_id",
        "node_ref",
        "artifact_id",
        "workflow_id",
        "step_id",
        "operation",
        "recipe_id",
        "recipe_operation_id",
        "column",
        "target_dtype",
        "output",
        "secondary_run_id",
        "secondary_node_id",
        "secondary_artifact_id",
    }
)
_DATA_CONSUMER_EXECUTION_FIELDS = frozenset(
    {"execution_key", "bindings"}
)
_DATA_CONSUMER_BINDING_FIELDS = frozenset(
    {
        "execution_key",
        "artifact_id",
        "metadata_artifact_id",
        "recipe_artifact_id",
        "child_node_id",
        "group_manifest_id",
        "operation_id",
        "record_id",
        "data_artifact_id",
        "data_metadata_artifact_id",
        "data_recipe_artifact_id",
        "data_child_node_id",
    }
)


def _bounded_data_consumer_evidence(value: Any) -> dict[str, Any]:
    payload = _bounded_data_consumer_value(value)
    if (
        not isinstance(payload, dict)
        or payload != value
        or not set(payload).issubset(_DATA_CONSUMER_EVIDENCE_FIELDS)
    ):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation evidence contains undeclared fields.",
            details={},
        )
    if not all(
        isinstance(payload.get(key), str) and payload[key]
        for key in ("method", "record_id", "operation_id", "execution_key", "child_node_id")
    ):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation evidence identity is incomplete.",
            details={},
        )
    weight = payload.get("weight")
    if weight is not None:
        if not isinstance(weight, dict) or not set(weight).issubset(_DATA_CONSUMER_WEIGHT_FIELDS):
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The data operation weight evidence is not exact.",
                details={},
            )
        if any(not isinstance(item, str) or not item for item in weight.values()):
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The data operation weight evidence is not typed.",
                details={},
            )
    if "weight_consumed" in payload and type(payload["weight_consumed"]) is not bool:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation weight evidence is not typed.",
            details={},
        )
    for key in ("weight_sum", "group_count"):
        if key in payload and type(payload[key]) not in (int, float):
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The data operation aggregate evidence is not typed.",
                details={},
            )
    scalar_string_fields = set(payload) - {
        "weight",
        "weight_consumed",
        "weight_sum",
        "group_count",
    }
    if any(
        not isinstance(payload[key], str) or not payload[key]
        for key in scalar_string_fields
    ):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation evidence scalar fields are not typed.",
            details={},
        )
    return payload


def _bounded_data_consumer_spec(spec: Any) -> dict[str, Any]:
    """Return only the typed identity summary of a preview specification."""

    payload = _bounded_data_consumer_value(spec.to_dict())
    if not isinstance(payload, dict):  # pragma: no cover - typed spec invariant
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_SPEC_UNAVAILABLE",
            message="The data operation specification is not a typed object.",
            details={},
        )
    bounded = {
        key: payload[key]
        for key in _DATA_CONSUMER_SPEC_FIELDS
        if key in payload
    }
    casts = payload.get("casts")
    if isinstance(casts, list):
        bounded["casts"] = [
            {
                key: item[key]
                for key in _DATA_CONSUMER_CAST_FIELDS
                if key in item
            }
            for item in casts
            if isinstance(item, dict)
        ]
    recipe = payload.get("recipe")
    if isinstance(recipe, dict):
        bounded["recipe"] = {
            key: recipe[key]
            for key in _DATA_CONSUMER_RECIPE_FIELDS
            if key in recipe
        }
    return bounded


def _bounded_data_consumer_projection(
    value: Any,
    fields: frozenset[str],
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    payload = _bounded_data_consumer_value(value)
    if not isinstance(payload, dict):
        raise WorkbenchAPIError(status_code=500, code=code, message=message, details={})
    return {key: payload[key] for key in fields if key in payload}


def _bounded_data_consumer_proposal(value: Any) -> dict[str, Any]:
    return _bounded_data_consumer_projection(
        value,
        _DATA_CONSUMER_PROPOSAL_FIELDS,
        code="DATA_OPERATION_PROPOSAL_UNAVAILABLE",
        message="The data operation proposal is not a bounded typed object.",
    )


def _bounded_data_consumer_confirmation(value: Any) -> dict[str, Any]:
    return _bounded_data_consumer_projection(
        value,
        _DATA_CONSUMER_CONFIRMATION_FIELDS,
        code="DATA_OPERATION_CONFIRMATION_UNAVAILABLE",
        message="The data operation confirmation is not a bounded typed object.",
    )


def _bounded_data_consumer_effect(effect: Any) -> dict[str, Any]:
    """Project a server-owned effect to identity-only central output fields."""

    payload = effect.to_dict()
    if not isinstance(payload, dict):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_EFFECT_UNAVAILABLE",
            message="The data operation effect is not a typed object.",
            details={},
        )
    safe: dict[str, Any] = {}
    for key in _DATA_CONSUMER_SAFE_EFFECT_FIELDS:
        if key not in payload or payload[key] is None:
            continue
        value = payload[key]
        if type(value) is not str or not value:
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_EFFECT_UNAVAILABLE",
                message="The data operation effect identity is not a non-empty string.",
                details={"field": key},
            )
        safe[key] = value
    if "group_artifacts" in payload:
        group_artifacts = payload["group_artifacts"]
        if not isinstance(group_artifacts, list) or any(
            not isinstance(item, dict) for item in group_artifacts
        ):
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_EFFECT_UNAVAILABLE",
                message="The data operation group effect is not a typed identity list.",
                details={},
            )
        bounded_groups: list[dict[str, str]] = []
        for item in group_artifacts:
            bounded_item: dict[str, str] = {}
            for key in _DATA_CONSUMER_GROUP_ARTIFACT_FIELDS:
                if key not in item or item[key] is None:
                    continue
                value = item[key]
                if type(value) is not str or not value:
                    raise WorkbenchAPIError(
                        status_code=500,
                        code="DATA_OPERATION_EFFECT_UNAVAILABLE",
                        message="The data operation group identity is not a non-empty string.",
                        details={"field": key},
                    )
                bounded_item[key] = value
            if not bounded_item:
                raise WorkbenchAPIError(
                    status_code=500,
                    code="DATA_OPERATION_EFFECT_UNAVAILABLE",
                    message="The data operation group identity is empty.",
                    details={},
                )
            bounded_groups.append(bounded_item)
        safe["group_artifacts"] = bounded_groups
    return safe


def _bounded_data_consumer_output_ports(
    output_ports: Any,
    *,
    effect: Any,
    catalog_digest: str,
) -> dict[str, Any]:
    """Project typed ports to the exact central persistence schema."""

    payload = output_ports.to_dict(catalog_digest=catalog_digest)
    if not isinstance(payload, dict) or set(payload) != {
        "ports",
        "consumer_slots",
        "catalog_digest",
    }:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation output ports have an invalid top-level schema.",
            details={},
        )
    raw_ports = payload.get("ports")
    raw_slots = payload.get("consumer_slots")
    raw_catalog_digest = payload.get("catalog_digest")
    if (
        type(raw_catalog_digest) is not str
        or not raw_catalog_digest
        or raw_catalog_digest != catalog_digest
    ):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation catalog identity is not exact.",
            details={},
        )
    if not isinstance(raw_ports, dict) or set(raw_ports) != {
        "derived",
        "operation_record",
        "evidence",
    }:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation output ports have an invalid port schema.",
            details={},
        )
    raw_operation = raw_ports.get("operation_record")
    raw_evidence = raw_ports.get("evidence")
    if not isinstance(raw_operation, dict) or set(raw_operation) != {
        "record_id",
        "operation_id",
        "operation_version",
    } or any(not isinstance(raw_operation[key], str) or not raw_operation[key] for key in raw_operation):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation OperationRecord port is not exact.",
            details={},
        )
    evidence = _bounded_data_consumer_evidence(raw_evidence)
    if not isinstance(raw_slots, dict) or set(raw_slots) != {
        "data.agent",
        "data.notebook",
        "data.report",
    }:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The data operation consumer slots are not exact.",
            details={},
        )
    slots: dict[str, dict[str, str]] = {}
    for slot in ("data.agent", "data.notebook", "data.report"):
        item = raw_slots[slot]
        if not isinstance(item, dict) or set(item) != {"record_id", "port"}:
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The data operation consumer slot is not exact.",
                details={"slot": slot},
            )
        if any(not isinstance(item[key], str) or not item[key] for key in item):
            raise WorkbenchAPIError(
                status_code=500,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The data operation consumer slot identity is not typed.",
                details={"slot": slot},
            )
        slots[slot] = {"record_id": item["record_id"], "port": item["port"]}
    safe_derived = {
        key: value
        for key, value in _bounded_data_consumer_effect(effect).items()
        if key in _DATA_CONSUMER_SAFE_EFFECT_FIELDS
    }
    return {
        "ports": {
            "derived": safe_derived,
            "operation_record": {
                key: raw_operation[key]
                for key in ("record_id", "operation_id", "operation_version")
            },
            "evidence": evidence,
        },
        "consumer_slots": slots,
        "catalog_digest": raw_catalog_digest,
    }


def _bounded_data_consumer_operation_record(value: Any) -> dict[str, Any]:
    """Project a completed OperationRecord without echoing request dictionaries."""

    payload = _bounded_data_consumer_value(value)
    if not isinstance(payload, dict) or payload != value:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation record is not a typed object.",
            details={},
        )
    required = {"record_id", "operation_id", "operation_version", "status", "target", "execution", "outputs"}
    if not required.issubset(payload):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation record is incomplete.",
            details={},
        )
    target = payload.get("target")
    if not isinstance(target, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation target is not typed.",
            details={},
        )
    target_projection = {
        key: target[key]
        for key in _DATA_CONSUMER_TARGET_FIELDS
        if key in target and isinstance(target[key], (str, int, float, bool, type(None)))
    }
    if not all(
        isinstance(target_projection.get(key), str) and target_projection[key]
        for key in ("run_id", "node_ref", "artifact_id")
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation target has no source identity.",
            details={},
        )
    execution = payload.get("execution")
    if not isinstance(execution, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation execution is not typed.",
            details={},
        )
    execution_key = execution.get("execution_key")
    bindings = execution.get("bindings")
    if not isinstance(execution_key, str) or not execution_key or not isinstance(bindings, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation execution has no identity binding.",
            details={},
        )
    if not set(bindings).issubset(_DATA_CONSUMER_BINDING_FIELDS):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation execution has undeclared bindings.",
            details={},
        )
    binding_projection = {}
    for key, item in bindings.items():
        if not isinstance(item, str) or not item:
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The completed data operation execution binding is not typed.",
                details={},
            )
        binding_projection[key] = item
    execution_projection = {
        key: execution[key]
        for key in _DATA_CONSUMER_EXECUTION_FIELDS
        if key in execution and key not in {"bindings", "execution_key"}
    }
    execution_projection.update(
        {"execution_key": execution_key, "bindings": binding_projection}
    )

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"ports", "consumer_slots", "catalog_digest"}:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation outputs are not exact.",
            details={},
        )
    ports = outputs.get("ports")
    slots = outputs.get("consumer_slots")
    if not isinstance(ports, dict) or set(ports) != {"derived", "operation_record", "evidence"}:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation ports are not exact.",
            details={},
        )
    derived = ports.get("derived")
    operation_port = ports.get("operation_record")
    if not isinstance(derived, dict) or not set(derived).issubset(_DATA_CONSUMER_SAFE_EFFECT_FIELDS):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation derived port is not exact.",
            details={},
        )
    if any(not isinstance(item, str) or not item for item in derived.values()):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation derived identity is not typed.",
            details={},
        )
    if not isinstance(operation_port, dict) or set(operation_port) != {
        "record_id",
        "operation_id",
        "operation_version",
    } or any(
        not isinstance(operation_port[key], str) or not operation_port[key]
        for key in operation_port
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation record port is not exact.",
            details={},
        )
    evidence = _bounded_data_consumer_evidence(ports.get("evidence"))
    if not isinstance(slots, dict) or set(slots) != {
        "data.agent",
        "data.notebook",
        "data.report",
    }:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation consumer slots are not exact.",
            details={},
        )
    slot_projection: dict[str, dict[str, str]] = {}
    for slot in ("data.agent", "data.notebook", "data.report"):
        item = slots[slot]
        if not isinstance(item, dict) or set(item) != {"record_id", "port"}:
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The completed data operation consumer slot is not exact.",
                details={"slot": slot},
            )
        if any(not isinstance(item[key], str) or not item[key] for key in item):
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The completed data operation consumer slot identity is not typed.",
                details={"slot": slot},
            )
        slot_projection[slot] = {"record_id": item["record_id"], "port": item["port"]}
    catalog_digest = outputs.get("catalog_digest")
    if type(catalog_digest) is not str or not catalog_digest:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation catalog identity is not typed.",
            details={},
        )
    output_projection = {
        "ports": {
            "derived": dict(derived),
            "operation_record": dict(operation_port),
            "evidence": evidence,
        },
        "consumer_slots": slot_projection,
        "catalog_digest": catalog_digest,
    }
    diff_projection = _bounded_data_consumer_diff_ref(payload.get("diff_ref"))
    verification_projection = _bounded_data_consumer_verification(payload.get("verification"))
    projection = {
        key: payload[key]
        for key in _DATA_CONSUMER_RECORD_FIELDS
        if key in payload
        and key not in {"target", "execution", "outputs", "diff_ref", "verification"}
    }
    projection.update(
        {
            "target": target_projection,
            "execution": execution_projection,
            "outputs": output_projection,
            "diff_ref": diff_projection,
            "verification": verification_projection,
        }
    )
    return projection


def _bounded_code_operation_record(value: Any) -> dict[str, Any]:
    """Project code-execute history without returning code, stdout, or paths."""

    payload = _bounded_data_consumer_value(value)
    if not isinstance(payload, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The code operation record is not a typed object.",
            details={},
        )
    target = payload.get("target")
    execution = payload.get("execution")
    outputs = payload.get("outputs")
    verification = payload.get("verification")
    if not all(isinstance(item, dict) for item in (target, execution, outputs, verification)):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The code operation record is incomplete.",
            details={},
        )
    target_projection = {
        key: target[key]
        for key in (
            "run_id",
            "node_ref",
            "artifact_id",
            "workflow_id",
            "step_id",
            "language",
            "output_format",
        )
        if key in target and isinstance(target[key], (str, int, float, bool, type(None)))
    }
    execution_projection = {
        key: execution[key]
        for key in ("execution_key", "source_run_id", "source_node_ref", "source_artifact_id", "language", "code_sha256", "data_preview_fingerprint", "source_sha256")
        if key in execution and isinstance(execution[key], (str, int, float, bool, type(None)))
    }
    bindings = execution.get("bindings")
    if isinstance(bindings, dict):
        execution_projection["bindings"] = {
            key: item
            for key, item in bindings.items()
            if key in _DATA_CONSUMER_BINDING_FIELDS and isinstance(item, str)
        }
    output_projection = {
        key: outputs[key]
        for key in (
            "status",
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
            "artifact_id",
            "recipe_artifact_id",
            "child_node_id",
            "preview_fingerprint",
        )
        if key in outputs and isinstance(outputs[key], (str, int, float, bool, type(None)))
    }
    diff_ref = payload.get("diff_ref")
    diff_projection = None
    if isinstance(diff_ref, dict):
        diff_projection = {
            key: diff_ref[key]
            for key in (
                "kind",
                "source_fingerprint",
                "result_fingerprint",
                "columns_added",
                "columns_removed",
                "dtype_changes",
                "row_count_before",
                "row_count_after",
            )
            if key in diff_ref
        }
        for key in ("columns_added", "columns_removed"):
            if key in diff_projection and (
                not isinstance(diff_projection[key], list)
                or any(not isinstance(item, str) or not item for item in diff_projection[key])
            ):
                raise WorkbenchAPIError(
                    status_code=409,
                    code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                    message="The code operation diff columns are not typed.",
                    details={},
                )
        if "dtype_changes" in diff_projection:
            changes = diff_projection["dtype_changes"]
            if not isinstance(changes, list) or any(
                not isinstance(item, dict)
                or set(item) != {"column", "before_dtype", "after_dtype"}
                or any(not isinstance(item[field], str) or not item[field] for field in item)
                for item in changes
            ):
                raise WorkbenchAPIError(
                    status_code=409,
                    code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                    message="The code operation dtype diff is not typed.",
                    details={},
                )
        for key in ("row_count_before", "row_count_after"):
            if key in diff_projection and type(diff_projection[key]) is not int:
                raise WorkbenchAPIError(
                    status_code=409,
                    code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                    message="The code operation row-count diff is not typed.",
                    details={},
                )
    checks = verification.get("checks")
    verification_projection = {
        key: verification[key]
        for key in ("passed", "status")
        if key in verification and isinstance(verification[key], (str, int, float, bool, type(None)))
    }
    if isinstance(checks, dict):
        verification_projection["checks"] = {
            key: checks[key]
            for key in (
                "source_immutable",
                "artifact_registered",
                "graph_child",
                "preview_matches_effect",
                "sandboxed",
                "deterministic",
                "downstream_rerun_required",
            )
            if key in checks
        }
        for key in (
            "source_immutable",
            "artifact_registered",
            "graph_child",
            "preview_matches_effect",
            "sandboxed",
            "deterministic",
        ):
            if key in verification_projection["checks"] and type(verification_projection["checks"][key]) is not bool:
                raise WorkbenchAPIError(
                    status_code=409,
                    code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                    message="The code operation verification check is not typed.",
                    details={},
                )
        reruns = verification_projection["checks"].get("downstream_rerun_required")
        if reruns is not None and (
            not isinstance(reruns, list)
            or any(not isinstance(item, str) or not item for item in reruns)
        ):
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The code operation downstream identities are not typed.",
                details={},
            )
    projection = {
        key: payload[key]
        for key in _DATA_CONSUMER_RECORD_FIELDS
        if key in payload and key not in {"target", "execution", "outputs", "diff_ref", "verification"}
    }
    projection.update(
        {
            "target": target_projection,
            "execution": execution_projection,
            "outputs": output_projection,
            "verification": verification_projection,
        }
    )
    if diff_projection is not None:
        projection["diff_ref"] = diff_projection
    return projection


def _bounded_metadata_operation_record(value: Any) -> dict[str, Any]:
    """Return metadata history identity without returning its indexed path."""

    if not isinstance(value, dict):
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The metadata mutation record is not a typed object.",
            details={},
        )
    source = value.get("source")
    artifact = value.get("metadata_artifact")
    if not isinstance(source, dict) or not isinstance(artifact, dict):
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The metadata mutation record has no typed identity.",
            details={},
        )
    source_projection = {
        key: source[key]
        for key in ("run_id", "node_id", "artifact_id", "sha256")
        if key in source and isinstance(source[key], str)
    }
    artifact_projection = {
        key: artifact[key]
        for key in ("artifact_id", "sha256")
        if key in artifact and isinstance(artifact[key], str)
    }
    required = ("run_id", "node_id", "artifact_id")
    if not all(isinstance(source_projection.get(key), str) for key in required):
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The metadata mutation source identity is incomplete.",
            details={},
        )
    return {
        key: value[key]
        for key in (
            "record_id",
            "operation_id",
            "operation_version",
            "status",
            "metadata_fingerprint",
            "child_node_id",
        )
        if key in value and isinstance(value[key], (str, int, float, bool, type(None)))
    } | {
        "source": source_projection,
        "metadata_artifact": artifact_projection,
    }


def _bounded_data_consumer_diff_ref(value: Any) -> dict[str, Any] | None:
    if value is None:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation has no diff reference.",
            details={},
        )
    if not isinstance(value, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation diff reference is not typed.",
            details={},
        )
    allowed = {
        "kind",
        "artifact_id",
        "metadata_artifact_id",
        "recipe_artifact_id",
        "group_manifest_id",
        "child_node_id",
    }
    if not set(value).issubset(allowed) or any(
        not isinstance(value[key], str) or not value[key] for key in value
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation diff reference contains undeclared fields.",
            details={},
        )
    if not isinstance(value.get("kind"), str) or not value["kind"] or not any(
        key in value
        for key in ("artifact_id", "metadata_artifact_id", "recipe_artifact_id", "group_manifest_id")
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation diff reference is incomplete.",
            details={},
        )
    return dict(value)


def _bounded_data_consumer_verification(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation verification is not typed.",
            details={},
        )
    allowed = {"passed", "mode", "child_node_id"}
    if not set(value).issubset(allowed) or "passed" not in value or "mode" not in value:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation verification contains undeclared fields.",
            details={},
        )
    if "passed" in value and type(value["passed"]) is not bool:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation verification is not typed.",
            details={},
        )
    for key in set(value) - {"passed"}:
        if not isinstance(value[key], str) or not value[key]:
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
                message="The completed data operation verification is not typed.",
                details={},
            )
    return dict(value)


def _require_live_data_operation_descriptor(
    operation_id: str,
    *,
    preview_ref: str | None = None,
    confirm_ref: str | None = None,
):
    """Resolve route authority from the one server-owned live manifest."""

    from .. import data_operation_manifest

    manifest = data_operation_manifest.build_data_operation_manifest()
    descriptor = next(
        (item for item in manifest.operations if item.operation_id == operation_id),
        None,
    )
    if descriptor is None:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_NOT_ADVERTISED",
            message="The requested data operation is not advertised by the live server manifest.",
            details={"operation_id": operation_id},
        )
    if preview_ref is not None and descriptor.preview_ref != preview_ref:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_ROUTE_IDENTITY_MISMATCH",
            message="The route does not match the live data-operation descriptor.",
            details={"operation_id": operation_id, "expected": descriptor.preview_ref},
        )
    if confirm_ref is not None and descriptor.confirm_ref != confirm_ref:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_ROUTE_IDENTITY_MISMATCH",
            message="The route does not match the live data-operation descriptor.",
            details={"operation_id": operation_id, "expected": descriptor.confirm_ref},
        )
    return descriptor


def _live_data_operation_ids() -> frozenset[str]:
    """Return the record lookup allowlist from the live manifest projection."""

    payload = _public_data_operation_manifest()
    return frozenset(
        str(item["operation_id"])
        for item in payload["operations"]
        if isinstance(item, dict) and isinstance(item.get("operation_id"), str)
    )


def _require_live_metadata_loss_unavailable() -> None:
    """Keep the legacy read-only preview behind the server-owned manifest."""

    from .. import data_operation_manifest

    manifest = data_operation_manifest.build_data_operation_manifest()
    unavailable = next(
        (
            item
            for item in manifest.unavailable
            if item.operation_id == "data.metadata.loss"
        ),
        None,
    )
    if unavailable is None or unavailable.reason_code != "not_executable":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_NOT_ADVERTISED",
            message="The metadata-loss preview is not available on the live server surface.",
            details={"operation_id": "data.metadata.loss"},
        )


def _preflight_or_error(root: Path, spec: Any, preview: Any) -> None:
    """Keep complete write-free preflight failures inside the HTTP error boundary."""

    try:
        preflight_data_operation(root, spec, preview)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The data operation could not be preflighted against the current source.",
            details={"reason": str(exc)},
        ) from exc


def _resolve_profile(
    root: Path,
    *,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> dict[str, Any]:
    probe = DataColumnCastSpecV1(
        source_run_id=source_run_id,
        source_node_id=source_node_id,
        source_artifact_id=source_artifact_id,
        column="__profile_source__",
        target_dtype="string",
    )
    _run_root, _graph, _node, artifact, source_path = _resolve_source(root, probe)
    frame = _read_frame(source_path)
    content_sha256 = artifact.get("sha256")
    if not isinstance(content_sha256, str) or not content_sha256:
        content_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    registry = resolve_metadata_registry(
        root,
        source_run_id=source_run_id,
        source_node_id=source_node_id,
        source_artifact_id=source_artifact_id,
    )
    if registry is None:
        raise DataMetadataUnavailableError(
            "profile requires a confirmed server-owned metadata artifact"
        )
    declared_metadata = registry.to_profile_metadata(
        tuple(str(column) for column in frame.columns)
    )
    profile = build_data_profile(
        frame=frame,
        dataset_ref=DatasetRefV1(
            run_id=source_run_id,
            node_id=source_node_id,
            artifact_id=source_artifact_id,
            content_sha256=content_sha256,
            schema_revision=registry.schema_revision,
            metadata_revision=registry.metadata_revision,
        ),
        declared_metadata=declared_metadata,
    )
    if not hasattr(profile, "to_dict"):
        raise TypeError("data profile must expose a JSON projection")
    return profile.to_dict()


def _bounded_data_profile_projection(value: Any) -> dict[str, Any]:
    """Project DataProfileV1 to the fields safe for the direct data surface."""

    payload = _bounded_data_consumer_value(value)
    if not isinstance(payload, dict):
        raise ValueError("data profile projection is not an object")
    source = payload.get("source") or payload.get("dataset_ref") or payload.get("dataset")
    if not isinstance(source, dict):
        source = payload
    source_fields = {
        "run_id": source.get("run_id", source.get("source_run_id")),
        "node_id": source.get("node_id", source.get("source_node_id")),
        "artifact_id": source.get("artifact_id", source.get("source_artifact_id")),
    }
    if not all(isinstance(item, str) and item for item in source_fields.values()):
        raise ValueError("data profile source identity is incomplete")
    variables = payload.get("variables")
    if not isinstance(variables, list):
        variables = payload.get("columns")
    if not isinstance(variables, list):
        raise ValueError("data profile variables are unavailable")

    def _scalar(value: Any) -> bool:
        return type(value) in {str, int, float, bool, type(None)}

    def _scalar_list(value: Any, field_name: str) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError(f"data profile {field_name} is not a list")
        if any(not _scalar(item) for item in value):
            raise ValueError(f"data profile {field_name} values are not scalar")
        return list(value)

    def _value_labels(value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("data profile value labels are not a mapping")
        if any(type(key) is not str or type(item) is not str for key, item in value.items()):
            raise ValueError("data profile value labels are not string keyed")
        return dict(value)

    projected_variables: list[dict[str, Any]] = []
    for variable in variables:
        if not isinstance(variable, dict):
            raise ValueError("data profile variable is not an object")
        is_canonical = any(
            field_name in variable for field_name in ("observed", "declared", "inferred")
        )
        if is_canonical:
            observed = variable.get("observed")
            declared = variable.get("declared")
            inferred = variable.get("inferred")
            if not isinstance(observed, dict) or not isinstance(declared, dict) or not isinstance(inferred, dict):
                raise ValueError("data profile nested observed, declared, and inferred metadata are required")
            name = variable.get("name")
            label = declared.get("variable_label", "unknown")
            measurement_level = declared.get("measurement_level", "unknown")
            count = observed.get("missing_count")
            rate = observed.get("missing_rate")
            user_missing_values = declared.get("user_missing_values", [])
            value_labels = declared.get("value_labels")
            sample_values = observed.get("sample_values", [])
        else:
            name = variable.get("name", variable.get("variable_name", variable.get("column")))
            label = variable.get("label", variable.get("variable_label"))
            measurement_level = variable.get(
                "measurement_level",
                variable.get("measure", variable.get("measurement")),
            )
            missingness = variable.get("missingness")
            if not isinstance(missingness, dict):
                missingness = {
                    "count": variable.get("missing_count"),
                    "rate": variable.get("missing_rate"),
                }
            count = missingness.get("count")
            rate = missingness.get("rate")
            user_missing_values = variable.get("user_missing_values")
            value_labels = variable.get("value_labels")
            sample_values = variable.get("sample_values")
        if (
            type(name) is not str
            or not name
            or not isinstance(label, (str, type(None)))
            or not isinstance(measurement_level, (str, type(None)))
            or type(count) not in (int, float)
            or type(rate) not in (int, float)
            or not isinstance(user_missing_values, list)
            or not isinstance(sample_values, list)
        ):
            raise ValueError("data profile variable is not a bounded typed projection")
        if not isinstance(label, (str, type(None))) or not isinstance(measurement_level, (str, type(None))):
            raise ValueError("data profile labels are not scalar")
        user_missing_values = _scalar_list(user_missing_values, "user-missing")
        value_labels = _value_labels(value_labels)
        sample_values = _scalar_list(sample_values, "sample")
        projected_variables.append(
            {
                "name": name,
                "label": label,
                "measurement_level": measurement_level,
                "missingness": {"count": count, "rate": rate},
                "user_missing_values": user_missing_values,
                "value_labels": value_labels,
                "sample_values": sample_values,
            }
        )
    return {
        "schema_version": "data-profile.v1",
        "source": source_fields,
        "variables": projected_variables,
    }


class DataColumnCastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    column: str = Field(min_length=1, max_length=200)
    target_dtype: Literal["numeric", "string", "datetime"]


class DataColumnCastConfirmRequest(DataColumnCastRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class DataColumnsCastItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=200)
    target_dtype: Literal["numeric", "string", "datetime"]


class DataColumnsCastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    casts: list[DataColumnsCastItem] = Field(min_length=1, max_length=200)
    output_format: Literal["csv", "xlsx"] = "csv"


class DataColumnsCastConfirmRequest(DataColumnsCastRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class FeatureRecipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    recipe_id: str = Field(min_length=1, max_length=200)
    # The manifest calls this field recipe_operation_id so it cannot be
    # confused with the outer operation identity (data.feature_recipe).  Keep
    # operation_id as an input alias for existing clients.
    operation_id: Literal["derived_variable", "recode", "interaction", "log", "ratio"] = Field(
        validation_alias=AliasChoices("operation_id", "recipe_operation_id")
    )
    inputs: list[str] = Field(min_length=1, max_length=2)
    output: str = Field(min_length=1, max_length=200)
    output_type: str = Field(default="numeric", min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    fit_scope: Literal["stateless", "date_local", "period_fitted"] = "stateless"
    missing_policy: str = Field(default="fail_closed", min_length=1, max_length=40)
    outlier_policy: str = Field(default="preserve", min_length=1, max_length=40)


class FeatureRecipeConfirmRequest(FeatureRecipeRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class DataTransformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    operation: Literal[
        "merge",
        "append",
        "reshape",
        "subset",
        "dedupe",
        "rename",
        "aggregate",
        "fill_missing",
        "tsset",
        "lag",
        "sort",
        "split",
        "recode",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    secondary_run_id: str | None = Field(default=None, max_length=200)
    secondary_node_id: str | None = Field(default=None, max_length=300)
    secondary_artifact_id: str | None = Field(default=None, max_length=200)


class DataTransformConfirmRequest(DataTransformRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class MetadataMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    weight: dict[str, Any] | None = None
    split: dict[str, Any] | None = None
    group: dict[str, Any] | None = None


class MetadataMutationConfirmRequest(MetadataMutationRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class MetadataLossPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_format: str = Field(min_length=1, max_length=40)
    target_format: str = Field(min_length=1, max_length=40)
    metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DataModelRunRequest(BaseModel):
    """Start the existing OLS lifecycle from a materialized data-operation node."""

    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    model_type: Literal["ols"] = "ols"
    y: str = Field(min_length=1, max_length=200)
    x: list[str] = Field(min_length=1, max_length=200)
    covariance: Literal["", "unadjusted", "robust", "clustered"] = "robust"


class CodeExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    language: Literal["python"] = "python"
    output_format: Literal["csv", "xlsx"] = "csv"


class CodeExecuteConfirmRequest(CodeExecuteRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)
    risk_authorization_id: str | None = Field(default=None, min_length=1, max_length=200)
    risk_authorization_token: str | None = Field(default=None, min_length=1, max_length=500)


class CodeExecuteRiskAuthorizationRequest(CodeExecuteRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)
    acknowledge_risk: Literal[True]


def _root(project_root: str):
    from pathlib import Path

    requested = Path(project_root).expanduser()
    root = requested.resolve()
    if requested.is_symlink() or not root.is_dir() or not (root / "runs").is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _spec(body: DataColumnCastRequest) -> DataColumnCastSpecV1:
    return DataColumnCastSpecV1(
        source_run_id=body.source_run_id,
        source_node_id=body.source_node_id,
        source_artifact_id=body.source_artifact_id,
        column=body.column,
        target_dtype=body.target_dtype,
    )


def _preview_or_error(root, spec: DataColumnCastSpecV1, *, confirm: bool):
    try:
        return preview_data_column_cast(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The source data context changed before confirmation."
                if confirm
                else "The typed data operation cannot be previewed."
            ),
            details={"operation_id": "data.column.cast", "reason": str(exc)},
        ) from exc


def _batch_spec(body: DataColumnsCastRequest) -> DataColumnsCastSpecV1:
    try:
        return DataColumnsCastSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            casts=tuple(DataCastItem(item.column, item.target_dtype) for item in body.casts),
            output_format=body.output_format,
        )
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed batch cast specification is invalid.",
            details={"operation_id": "data.columns.cast", "reason": str(exc)},
        ) from exc


def _batch_preview_or_error(root, spec: DataColumnsCastSpecV1, *, confirm: bool):
    try:
        return preview_data_columns_cast(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The source data context changed before confirmation."
                if confirm
                else "The typed data operation cannot be previewed."
            ),
            details={"operation_id": "data.columns.cast", "reason": str(exc)},
        ) from exc


async def _confirm_cast_operation(
    root: Path,
    body: Any,
    spec: DataColumnCastSpecV1 | DataColumnsCastSpecV1,
    preview: Any,
    *,
    operation_id: str,
    proposal_id: str,
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Confirm a cast and publish its complete central consumer output ports.

    Casts historically used the generic Agent orchestrator route, which
    materialized the child correctly but returned only its legacy Operation
    payload. The central data-consumer contract requires the same server-issued
    derived/evidence ports as the other package-owned operations, so the route
    uses the shared direct confirmation seam and the package effect hook in one
    transaction.
    """

    try:
        with data_operation_transaction(root, spec, preview):
            confirmation = _confirm_direct_data_operation(
                root,
                operation_id=operation_id,
                source_run_id=spec.source_run_id,
                source_node_id=spec.source_node_id,
                source_artifact_id=spec.source_artifact_id,
                preview_fingerprint=preview.fingerprint,
                source_sha256=preview.source_sha256,
                secondary_source_sha256=None,
                session_id=body.session_id,
                target_fields={},
                changes=changes,
                target_override=target,
                preconditions_override=preconditions,
                proposal_id_override=proposal_id,
            )
            pending = confirmation["operation_record"]
            execution = pending.get("execution") if isinstance(pending, dict) else None
            execution_key = execution.get("execution_key") if isinstance(execution, dict) else None
            if not isinstance(execution_key, str) or not execution_key:
                raise WorkbenchAPIError(
                    status_code=500,
                    code="DATA_OPERATION_RECORD_UNAVAILABLE",
                    message="The cast OperationRecord has no server-issued execution key.",
                    details={"operation_id": operation_id},
                )
            if operation_id == "data.column.cast":
                effect = apply_data_column_cast(
                    root,
                    spec,
                    preview,
                    execution_key_value=execution_key,
                )
            elif operation_id == "data.columns.cast":
                effect = apply_data_columns_cast(
                    root,
                    spec,
                    preview,
                    execution_key_value=execution_key,
                )
            else:  # pragma: no cover - the caller owns this closed operation set
                raise WorkbenchAPIError(
                    status_code=500,
                    code="DATA_OPERATION_INVALID",
                    message="The cast route received an unsupported operation identity.",
                    details={"operation_id": operation_id},
                )
            operation = _complete_direct_data_operation(
                root,
                confirmation,
                effect,
                method=operation_id,
                evidence={
                    "source_sha256": preview.source_sha256,
                    "preview_fingerprint": preview.fingerprint,
                },
            )
    except (DataColumnCastValidationError, FileNotFoundError, KeyError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before execution.",
            details={"proposal_id": proposal_id, "reason": str(exc)},
        ) from exc

    return _bounded_data_consumer_value({
        "status": "completed",
        "effect": _bounded_data_consumer_effect(effect),
        "preview": _confirm_preview_payload(body, preview),
        "operation": _legacy_cast_operation_view(operation),
        "operation_record": operation,
        "proposal": _bounded_data_consumer_proposal(confirmation["proposal"]),
        "confirmation": _bounded_data_consumer_confirmation(confirmation["confirmation"]),
    })


def _feature_recipe_spec(body: FeatureRecipeRequest) -> FeatureRecipeOperationSpecV1:
    from ..predictive_research.contracts import FeatureRecipeV1

    try:
        recipe = FeatureRecipeV1(
            recipe_id=body.recipe_id,
            operation_id=body.operation_id,
            operation_version=1,
            inputs=tuple(body.inputs),
            outputs=(body.output,),
            output_types=(body.output_type,),
            parameters=body.parameters,
            fit_scope=body.fit_scope,
            source_artifact=body.source_artifact_id,
            lineage_parent=body.source_node_id,
            missing_policy=body.missing_policy,
            outlier_policy=body.outlier_policy,
        )
        return FeatureRecipeOperationSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            recipe=recipe,
        )
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed FeatureRecipe specification is invalid.",
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc


def _feature_recipe_preview_or_error(root, spec: FeatureRecipeOperationSpecV1, *, confirm: bool):
    try:
        return preview_feature_recipe(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The FeatureRecipe source changed before confirmation."
                if confirm
                else "The typed FeatureRecipe cannot be previewed."
            ),
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc


def _data_transform_spec(body: DataTransformRequest) -> DataTransformSpecV1:
    try:
        return DataTransformSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            operation=body.operation,
            parameters=body.parameters,
            secondary_run_id=body.secondary_run_id,
            secondary_node_id=body.secondary_node_id,
            secondary_artifact_id=body.secondary_artifact_id,
        )
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed data transform specification is invalid.",
            details={"operation_id": f"data.{body.operation}", "reason": str(exc)},
        ) from exc


def _data_transform_preview_or_error(root, spec: DataTransformSpecV1, *, confirm: bool):
    try:
        return preview_data_transform(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The data transform source changed before confirmation."
                if confirm
                else "The typed data transform cannot be previewed."
            ),
            details={"operation_id": f"data.{spec.operation}", "reason": str(exc)},
        ) from exc


def _metadata_mutation_spec(body: MetadataMutationRequest) -> MetadataMutationSpecV1:
    try:
        return MetadataMutationSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            metadata=body.metadata,
            weight=body.weight,
            split=body.split,
            group=body.group,
        )
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed metadata mutation specification is invalid.",
            details={"operation_id": "data.metadata.update", "reason": str(exc)},
        ) from exc


def _metadata_mutation_preview_or_error(
    root,
    spec: MetadataMutationSpecV1,
    *,
    confirm: bool,
):
    try:
        return preview_metadata_mutation(root, spec)
    except DataMetadataUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_METADATA_UNAVAILABLE",
            message="The selected data artifact has no confirmed server-owned metadata registry.",
            details={},
        ) from exc
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The metadata source changed before confirmation."
                if confirm
                else "The typed metadata mutation cannot be previewed."
            ),
            details={"operation_id": "data.metadata.update", "reason": str(exc)},
        ) from exc


def _model_source_or_error(root, body: DataModelRunRequest) -> tuple[Path, dict[str, Any], str | None]:
    """Resolve and fingerprint a materialized data node before dispatch."""

    if len(set(body.x)) != len(body.x):
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The model predictors must be unique.",
            details={"source_node_id": body.source_node_id},
        )
    if body.y in body.x:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The outcome cannot also be a predictor.",
            details={"outcome": body.y},
        )
    probe = DataColumnCastSpecV1(
        source_run_id=body.source_run_id,
        source_node_id=body.source_node_id,
        source_artifact_id=body.source_artifact_id,
        column="__model_source__",
        target_dtype="string",
    )
    try:
        run_root, _graph, node, artifact, source_path = _resolve_source(root, probe)
        frame = _read_frame(source_path)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The selected graph node is not a usable materialized dataset.",
            details={"source_node_id": body.source_node_id, "reason": str(exc)},
        ) from exc
    missing = [column for column in [body.y, *body.x] if column not in frame.columns]
    if missing:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The model columns are not present in the selected data node.",
            details={"missing_columns": missing},
        )
    non_numeric = [
        column
        for column in [body.y, *body.x]
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    if non_numeric:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The v1.8.6 data-node model entry currently requires numeric OLS columns.",
            details={"non_numeric_columns": non_numeric},
        )
    node_hash: str | None = getattr(node, "node_hash", None)
    index_path = run_root / "node_index.json"
    if index_path.is_file():
        try:
            indexed = read_json(index_path).get(body.source_node_id) or {}
            if indexed.get("node_hash"):
                node_hash = str(indexed["node_hash"])
        except (OSError, ValueError, AttributeError):
            pass
    return source_path, {"artifact": artifact, "node_hash": node_hash}, body.source_node_id


def _code_spec(body: CodeExecuteRequest) -> CodeExecuteSpecV1:
    try:
        return CodeExecuteSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            code=body.code,
            language=body.language,
            output_format=body.output_format,
        )
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The code.execute specification is invalid.",
            details={"operation_id": "code.execute", "reason": str(exc)},
        ) from exc


def _code_preview_or_error(root, spec: CodeExecuteSpecV1, *, confirm: bool):
    """Preview really runs the code in the sandbox; a missing sandbox is a 503.

    Sandbox absence is not the user's mistake and not a stale context — the
    capability does not exist on this host, and we never run the code without it.
    """

    try:
        return preview_code_execute(root, spec)
    except SandboxUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=503,
            code="SANDBOX_UNAVAILABLE",
            message=(
                "Running code requires an OS sandbox, which is unavailable on this host. "
                "The code was not run."
            ),
            details={"operation_id": "code.execute", "reason": str(exc)},
        ) from exc
    except (CodeExecuteValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The source data context changed before confirmation."
                if confirm
                else "The typed data operation cannot be previewed."
            ),
            details={"operation_id": "code.execute", "reason_code": "CODE_EXECUTION_PREVIEW_INVALID"},
        ) from exc


def _require_ready_code_preview(
    body: CodeExecuteConfirmRequest | CodeExecuteRiskAuthorizationRequest,
    preview,
) -> None:
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The code failed when it was run in the sandbox.",
            details={"operation_id": "code.execute", "reason_code": "CODE_EXECUTION_BLOCKED"},
        )
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message=(
                "The preview fingerprint no longer matches. Either the source data "
                "changed, or the code does not produce the same result every run."
            ),
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )


def _code_operation_context(
    root,
    body: CodeExecuteConfirmRequest | CodeExecuteRiskAuthorizationRequest,
    spec,
    preview,
) -> dict[str, Any]:
    """Build the same canonical typed proposal context for authorize and confirm."""

    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    events = AgentEventStream(workbench_root)
    chain_id = f"data_chain:{body.source_run_id}"
    _ensure_data_chain_scope(
        root,
        repository,
        session_id=body.session_id,
        chain_id=chain_id,
        active_head_run_id=body.source_run_id,
    )
    main_session_id = _ensure_main_session(repository, root)
    proposal_store = ProposalStore(workbench_root)
    registry = OperationRegistry()
    definition = registry.require("code.execute", "v1")
    target = {
        "run_id": spec.source_run_id,
        "node_ref": spec.source_node_id,
        "artifact_id": spec.source_artifact_id,
        "code": spec.code,
        "language": spec.language,
        "output_format": spec.output_format,
    }
    preconditions = {
        "context_version": "code-execute.v1",
        "context_fingerprint": preview.fingerprint,
        "active_head_run_id": spec.source_run_id,
        "owner_resolution": "typed_data_node",
        "source_sha256": preview.source_sha256,
    }
    changes = {
        "code": spec.code,
        "language": spec.language,
        "output_format": spec.output_format,
    }
    definition.validate(target=target, preconditions=preconditions, changes=changes)
    proposal_id = f"proposal_code_exec_{preview.fingerprint[:24]}"
    try:
        proposal = proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = proposal_store.create(
            session_id=body.session_id,
            chain_id=chain_id,
            operation_id="code.execute",
            operation_version="v1",
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=["code-execute-preview"],
            expected_effect=["create one immutable child data artifact"],
            risks=[
                "arbitrary user code, run sandboxed against a copy of the source",
                "sandboxed does not mean low risk; downstream model rerun required",
            ],
            proposal_id=proposal_id,
        )
        events.emit(body.session_id, "proposal_ready", proposal.to_dict())
        events.emit(
            body.session_id,
            "needs_confirmation",
            {"proposal_id": proposal_id, "revision": proposal.revision},
        )
    if proposal.target != target or proposal.preconditions != preconditions:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="A different typed proposal already owns this preview fingerprint.",
            details={"proposal_id": proposal_id},
        )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=main_session_id,
        proposal_store=proposal_store,
        operation_store=OperationRecordStore(workbench_root),
        operation_registry=registry,
        risk_authorization_store=RiskAuthorizationStore(workbench_root),
    )
    return {
        "workbench_root": workbench_root,
        "repository": repository,
        "events": events,
        "chain_id": chain_id,
        "proposal_store": proposal_store,
        "registry": registry,
        "definition": definition,
        "proposal": proposal,
        "orchestrator": orchestrator,
    }


def _ensure_session(repository: JsonlSessionRepository, session_id: str, chain_id: str) -> None:
    try:
        metadata = repository.get_metadata(session_id)
    except (KeyError, ValueError):
        repository.create_session(session_id, chain_id=chain_id, role="chain")
        return
    if metadata.get("role") != "chain" or metadata.get("chain_id") != chain_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_SCOPE_INVALID",
            message="The manual data operation session is outside this Chain scope.",
            details={"session_id": session_id, "chain_id": chain_id},
        )


def _ensure_data_chain_scope(
    root,
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    chain_id: str,
    active_head_run_id: str,
) -> None:
    _ensure_session(repository, session_id, chain_id)
    try:
        ensure_chain_root(
            root / "workbench",
            runs_root=root / "runs",
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=session_id,
        )
    except ChainHeadConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed operation Chain active head changed before confirmation.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _ensure_main_session(repository: JsonlSessionRepository, root) -> str:
    try:
        repository.get_metadata("agent_main")
    except (KeyError, ValueError):
        repository.create_session("agent_main", chain_id=f"project:{root}", role="main")
    return "agent_main"


def _confirm_direct_data_operation(
    root: Path,
    *,
    operation_id: str,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
    preview_fingerprint: str,
    source_sha256: str,
    secondary_source_sha256: str | None,
    session_id: str,
    target_fields: dict[str, Any],
    changes: dict[str, Any],
    target_override: dict[str, Any] | None = None,
    preconditions_override: dict[str, Any] | None = None,
    proposal_id_override: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Bind a legacy direct data route to the server proposal gate.

    The route keeps the existing proposal gate, then creates the same durable
    OperationRecord used by the central operation lifecycle.  The package-owned
    data-consumer adapter completes that record after the immutable effect is
    committed.
    """

    descriptor = _require_live_data_operation_descriptor(operation_id)
    from ..data_operation_manifest import build_data_consumer_runtime_adapter

    try:
        # Validate the server-owned runtime join before the package effect can
        # be reached.  Completion validates the same join against typed ports.
        build_data_consumer_runtime_adapter()
    except (ImportError, OSError, TypeError, ValueError, RuntimeError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_CONSUMER_RUNTIME_UNAVAILABLE",
            message="The server-owned data-consumer runtime is unavailable; execution was blocked.",
            details={"operation_id": operation_id, "reason": str(exc)},
        ) from exc

    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    events = AgentEventStream(workbench_root)
    chain_id = f"data_chain:{source_run_id}"
    _ensure_data_chain_scope(
        root,
        repository,
        session_id=session_id,
        chain_id=chain_id,
        active_head_run_id=source_run_id,
    )
    local_operation = descriptor.executor_key.startswith("executor:workbench.data_consumer.")
    definition = (
        None
        if local_operation
        else OperationRegistry().require(operation_id, descriptor.operation_version)
    )
    # These claims are written by the server into both sides of the durable
    # OperationRecord identity.  They are not model input: the later Agent /
    # Notebook / Report data projection uses them to prove that a result belongs
    # to this project, session, source run, and exact preview snapshot.
    server_identity_claims = {
        "project_ref": f"project:{root.resolve()}",
        "session_ref": session_id,
        "data_snapshot_ref": f"snapshot:{preview_fingerprint}",
        "data_snapshot_digest": source_sha256,
        "source_run_id": source_run_id,
        "source_node_id": source_node_id,
        "source_artifact_id": source_artifact_id,
    }
    target = (
        {
            **dict(target_override),
            **server_identity_claims,
        }
        if target_override is not None
        else {
            "run_id": source_run_id,
            "node_ref": source_node_id,
            "artifact_id": source_artifact_id,
            "workflow_id": f"route:{operation_id}",
            "step_id": f"preview:{preview_fingerprint[:32]}",
            **target_fields,
            **server_identity_claims,
        }
    )
    dependency_fingerprints = [source_sha256]
    if secondary_source_sha256:
        dependency_fingerprints.append(secondary_source_sha256)
    preconditions = (
        {
            **dict(preconditions_override),
            **server_identity_claims,
        }
        if preconditions_override is not None
        else {
            "context_version": f"{operation_id}.v1",
            "context_fingerprint": preview_fingerprint,
            "source_fingerprint": preview_fingerprint,
            "dependency_fingerprints": dependency_fingerprints,
            "active_head_run_id": source_run_id,
            "owner_resolution": "typed_data_node",
            **server_identity_claims,
        }
    )
    if definition is not None:
        definition.validate(target=target, preconditions=preconditions, changes=changes)
    else:
        if any(not isinstance(value, str) or not value.strip() for value in target.values() if isinstance(value, str)):
            raise WorkbenchAPIError(
                status_code=422,
                code="DATA_OPERATION_INVALID",
                message="The local data-consumer operation has an invalid identity.",
                details={"operation_id": operation_id},
            )
    proposal_store = ProposalStore(workbench_root)
    safe_operation_id = operation_id.replace(".", "_")
    proposal_id = proposal_id_override or f"proposal_{safe_operation_id}_{preview_fingerprint[:24]}"
    try:
        proposal = proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = proposal_store.create(
            session_id=session_id,
            chain_id=chain_id,
            operation_id=operation_id,
            operation_version=descriptor.operation_version,
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=[f"{operation_id}:preview"],
            expected_effect=["create one immutable child data artifact"],
            risks=["downstream model rerun required"],
            proposal_id=proposal_id,
        )
        events.emit(session_id, "proposal_ready", proposal.to_dict())
        events.emit(
            session_id,
            "needs_confirmation",
            {"proposal_id": proposal_id, "revision": proposal.revision},
        )
    if (
        proposal.target != target
        or proposal.preconditions != preconditions
        or proposal.changes != changes
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="A different typed proposal already owns this preview fingerprint.",
            details={"proposal_id": proposal_id},
        )
    try:
        confirmation = proposal_store.confirm(
            proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview_fingerprint,
            current_active_head_run_id=source_run_id,
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data proposal became stale before confirmation.",
            details={"proposal_id": proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal_id},
        ) from exc
    record_store = OperationRecordStore(workbench_root)
    operation_record = record_store.create_pending(
        confirmation,
        command_id=confirmation.command_id,
    )
    if operation_record.status not in {"completed", "failed", "stale", "cancelled"}:
        operation_record = record_store.claim_execution(
            operation_record.record_id,
            execution_key=f"exec_{preview_fingerprint[:32]}",
            lease_owner="data-consumer-route",
        )
    return {
        "proposal": proposal_store.latest_revision(proposal_id).to_dict(),
        "confirmation": confirmation.to_dict(),
        "operation_record": operation_record.to_dict(),
    }


def _complete_direct_data_operation(
    root: Path,
    confirmation_result: dict[str, Any],
    effect: Any,
    *,
    method: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a package effect to OperationRecord and expose bounded evidence ports."""

    from ..data_operation_manifest import (
        build_data_consumer_runtime_adapter,
        _issue_data_consumer_derived_port,
        _issue_data_consumer_evidence_port,
        _issue_data_consumer_output_ports,
        _issue_data_consumer_server_evidence,
    )

    operation_record_payload = confirmation_result.get("operation_record")
    if not isinstance(operation_record_payload, dict):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation has no durable OperationRecord.",
            details={},
        )
    record_id = operation_record_payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation record identity is invalid.",
            details={},
        )
    store = OperationRecordStore(root / "workbench")
    record = store.get(record_id)
    if record.status == "completed":
        _validate_completed_data_consumer_record(record, effect=effect)
        return _bounded_data_consumer_operation_record(record.to_dict())
    execution_key = record.execution.get("execution_key")
    if not isinstance(execution_key, str) or not execution_key:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation record has no execution claim.",
            details={"record_id": record_id},
        )
    effect_payload = effect.to_dict()
    run_id = record.target.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation record has no server-owned run identity.",
            details={"record_id": record_id},
        )
    run_root = root / "runs" / run_id
    child_node_id = effect_payload.get("child_node_id")
    if not isinstance(child_node_id, str) or not child_node_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_EFFECT_UNCOMMITTED",
            message="The data operation effect has no committed child identity.",
            details={"record_id": record_id},
        )
    graph_payload = read_json(run_root / "graph.json")
    if not isinstance(graph_payload.get("nodes"), dict) or child_node_id not in graph_payload["nodes"]:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_EFFECT_UNCOMMITTED",
            message="The data operation child is not committed to the server graph.",
            details={"record_id": record_id, "child_node_id": child_node_id},
        )
    artifact_rows = read_json(run_root / "artifacts_index.json").get("artifacts", [])
    if not isinstance(artifact_rows, list):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_EFFECT_UNCOMMITTED",
            message="The server artifact index is malformed.",
            details={"record_id": record_id},
        )
    for field_name in ("artifact_id", "metadata_artifact_id", "recipe_artifact_id", "group_manifest_id"):
        artifact_id = effect_payload.get(field_name)
        if artifact_id is None:
            continue
        row = next((item for item in artifact_rows if item.get("artifact_id") == artifact_id), None)
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_EFFECT_UNCOMMITTED",
                message="The data operation effect references an unregistered artifact.",
                details={"record_id": record_id, "artifact_id": artifact_id},
            )
        artifact_path = (run_root / row["path"]).resolve()
        try:
            artifact_path.relative_to(run_root.resolve())
        except ValueError as exc:
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_EFFECT_UNCOMMITTED",
                message="The data operation artifact escapes the run root.",
                details={"record_id": record_id, "artifact_id": artifact_id},
            ) from exc
        if not artifact_path.is_file():
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_EFFECT_UNCOMMITTED",
                message="The data operation artifact is not committed on disk.",
                details={"record_id": record_id, "artifact_id": artifact_id},
            )
    for path_field in ("artifact_path", "metadata_artifact_path", "recipe_path", "group_manifest_path"):
        relative = effect_payload.get(path_field)
        if relative is None:
            continue
        if not isinstance(relative, str) or not relative:
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_EFFECT_UNCOMMITTED",
                message="The data operation effect has an invalid committed path.",
                details={"record_id": record_id, "path_field": path_field},
            )
        path = (run_root / relative).resolve()
        try:
            path.relative_to(run_root.resolve())
        except ValueError as exc:
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_EFFECT_UNCOMMITTED",
                message="The data operation effect path escapes the run root.",
                details={"record_id": record_id, "path_field": path_field},
            ) from exc
        if not path.is_file():
            raise WorkbenchAPIError(
                status_code=409,
                code="DATA_OPERATION_EFFECT_UNCOMMITTED",
                message="The data operation effect path is not committed on disk.",
                details={"record_id": record_id, "path_field": path_field},
            )
    adapter = build_data_consumer_runtime_adapter()
    derived_port = _issue_data_consumer_derived_port(effect)
    effect_payload = derived_port.to_dict()
    bindings = {
        key: str(value)
        for key, value in effect_payload.items()
        if key.endswith("_id") and value is not None
    }
    record = store.bind_effect(
        record_id,
        execution_key=execution_key,
        bindings=bindings,
    )
    evidence_port = _issue_data_consumer_evidence_port(
        method,
        _issue_data_consumer_server_evidence(
            method,
            dict(evidence or {}),
            record_id=record.record_id,
            operation_id=record.operation_id,
            execution_key=execution_key,
            bindings={
                key: value
                for key, value in bindings.items()
                if key not in {"record_id", "operation_id", "execution_key"}
            },
        ),
    )
    output_ports = _issue_data_consumer_output_ports(
        record,
        derived_port,
        evidence_port,
    )
    adapter.adapt_operation_record(record, output_ports)
    outputs = _bounded_data_consumer_output_ports(
        output_ports,
        effect=effect,
        catalog_digest=adapter.catalog_digest,
    )
    record = store.append_status(
        record_id,
        "completed",
        outputs=outputs,
        diff_ref={
            "kind": "data-consumer-effect.v1",
            "artifact_id": effect_payload.get("artifact_id")
            or effect_payload.get("metadata_artifact_id"),
        },
        verification={
            "passed": True,
            "mode": "immutable_artifact_and_lineage",
            "child_node_id": effect_payload.get("child_node_id"),
        },
        effect_status="committed",
        projection_status="committed",
    )
    return _bounded_data_consumer_operation_record(record.to_dict())


def _validate_completed_data_consumer_record(record: Any, *, effect: Any) -> None:
    """Fail closed when a legacy completed record lacks the central contract."""

    outputs = record.outputs if isinstance(record.outputs, dict) else None
    if outputs is None or _bounded_data_consumer_value(outputs) != outputs:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation contains unbounded or stale output fields.",
            details={"record_id": record.record_id},
        )
    if set(outputs) != {"ports", "consumer_slots", "catalog_digest"}:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation output schema is not exact.",
            details={"record_id": record.record_id},
        )
    if outputs.get("catalog_digest") != _data_consumer_catalog_digest():
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation was produced by a stale catalog.",
            details={"record_id": record.record_id},
        )
    try:
        _bounded_data_consumer_diff_ref(record.diff_ref)
        _bounded_data_consumer_verification(record.verification)
    except WorkbenchAPIError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation record has incomplete verification evidence.",
            details={"record_id": record.record_id},
        ) from exc
    ports = outputs.get("ports")
    slots = outputs.get("consumer_slots")
    if not isinstance(ports, dict) or set(ports) != {"derived", "operation_record", "evidence"}:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation has no complete typed output ports.",
            details={"record_id": record.record_id},
        )
    if not isinstance(slots, dict) or set(slots) != {"data.agent", "data.notebook", "data.report"}:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation has incomplete consumer slots.",
            details={"record_id": record.record_id},
        )
    derived = ports.get("derived")
    operation_port = ports.get("operation_record")
    evidence = ports.get("evidence")
    if not isinstance(derived, dict) or not isinstance(operation_port, dict) or not isinstance(evidence, dict):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation has malformed typed output ports.",
            details={"record_id": record.record_id},
        )
    if set(operation_port) != {"record_id", "operation_id", "operation_version"}:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation OperationRecord port is not exact.",
            details={"record_id": record.record_id},
        )
    try:
        _bounded_data_consumer_evidence(evidence)
    except WorkbenchAPIError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation evidence contains undeclared fields.",
            details={"record_id": record.record_id},
        ) from exc
    if any(not isinstance(value, str) or not value for value in derived.values()):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation derived identity is not typed.",
            details={"record_id": record.record_id},
        )
    evidence_required = ("method", "record_id", "operation_id", "execution_key", "child_node_id")
    if not all(
        isinstance(evidence.get(key), str) and evidence[key]
        for key in evidence_required
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation evidence port is not typed.",
            details={"record_id": record.record_id},
        )
    expected_derived = _bounded_data_consumer_effect(effect)
    expected_derived = {
        key: value
        for key, value in expected_derived.items()
        if key in _DATA_CONSUMER_SAFE_EFFECT_FIELDS
    }
    if derived != expected_derived:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation effect does not match the replayed effect.",
            details={"record_id": record.record_id},
        )
    if not set(derived).issubset(_DATA_CONSUMER_SAFE_EFFECT_FIELDS):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation derived port has undeclared fields.",
            details={"record_id": record.record_id},
        )
    if derived.get("execution_key") != record.execution.get("execution_key"):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation output is not bound to its execution.",
            details={"record_id": record.record_id},
        )
    expected_bindings = {
        key: str(value)
        for key, value in derived.items()
        if key.endswith("_id") and value is not None
    }
    actual_bindings = record.execution.get("bindings")
    if (
        not isinstance(actual_bindings, dict)
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or not value
            for key, value in actual_bindings.items()
        )
        or actual_bindings != expected_bindings
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation bindings are not field-exact.",
            details={"record_id": record.record_id},
        )
    if (
        operation_port.get("record_id") != record.record_id
        or operation_port.get("operation_id") != record.operation_id
        or operation_port.get("operation_version") != record.operation_version
        or evidence.get("record_id") != record.record_id
        or evidence.get("operation_id") != record.operation_id
        or evidence.get("execution_key") != record.execution.get("execution_key")
        or evidence.get("child_node_id") != derived.get("child_node_id")
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation evidence is not bound to its record.",
            details={"record_id": record.record_id},
        )
    expected_slots = {
        "data.agent": "derived",
        "data.notebook": "derived",
        "data.report": "evidence",
    }
    if any(
        not isinstance(slots.get(slot), dict)
        or set(slots[slot]) != {"record_id", "port"}
        or slots[slot].get("record_id") != record.record_id
        or slots[slot].get("port") != port
        for slot, port in expected_slots.items()
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_OUTPUT_UNAVAILABLE",
            message="The completed data operation consumer slots are not bound to its record.",
            details={"record_id": record.record_id},
        )


def _legacy_cast_operation_view(operation: dict[str, Any]) -> dict[str, Any]:
    """Keep the old cast binding names without making them authoritative.

    Older callers read ``operation.execution.bindings.data_child_node_id``.
    The central contract uses the exact effect field names instead and exposes
    that authoritative record as ``operation_record``.  This bounded view
    preserves the old response shape for migration callers while carrying no
    paths, rows, or caller-controlled payload.
    """

    view = json.loads(json.dumps(operation))
    execution = view.get("execution")
    bindings = execution.get("bindings") if isinstance(execution, dict) else None
    if not isinstance(bindings, dict):
        return view
    legacy: dict[str, str] = {}
    aliases = {
        "artifact_id": "data_artifact_id",
        "child_node_id": "data_child_node_id",
        "recipe_artifact_id": "data_recipe_artifact_id",
    }
    for key, value in bindings.items():
        if not isinstance(value, str):
            continue
        legacy[aliases.get(key, key)] = value
    execution["bindings"] = legacy
    if view.get("operation_id") in {"data.column.cast", "data.columns.cast"}:
        diff_ref = view.get("diff_ref")
        if isinstance(diff_ref, dict):
            diff_ref["kind"] = "data.schema_diff.v1"
    return view


@router.get("/data-operations/manifest")
def get_data_operation_manifest() -> dict[str, Any]:
    """Expose the read-only package descriptor used by data consumers."""

    try:
        return _public_data_operation_manifest()
    except (ImportError, OSError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_MANIFEST_UNAVAILABLE",
            message="The data-operation descriptor is unavailable.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/data-operations/metadata-loss/preview")
def preview_metadata_loss(body: MetadataLossPreviewRequest) -> dict[str, Any]:
    """Report interchange loss without writing or exporting any file."""

    _require_live_metadata_loss_unavailable()
    try:
        manifest = build_metadata_loss_manifest(
            source_format=body.source_format,
            target_format=body.target_format,
            metadata=body.metadata,
        )
        return {"manifest": manifest.to_dict()}
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="METADATA_LOSS_PREVIEW_INVALID",
            message="The metadata-loss preview request is invalid.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/data-operations/metadata/preview")
def preview_metadata_mutation_route(
    project_root: str,
    body: MetadataMutationRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.metadata.update",
        preview_ref="/data-operations/metadata/preview",
    )
    spec = _metadata_mutation_spec(body)
    preview = _metadata_mutation_preview_or_error(root, spec, confirm=False)
    return _bounded_data_consumer_value({"spec": _bounded_data_consumer_spec(spec), "preview": _preview_payload(body, preview)})


@router.post("/data-operations/metadata/confirm")
def confirm_metadata_mutation_route(
    project_root: str,
    body: MetadataMutationConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.metadata.update",
        confirm_ref="/data-operations/metadata/confirm",
    )
    spec = _metadata_mutation_spec(body)
    preview = _metadata_mutation_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The metadata mutation preview fingerprint no longer matches the source.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    _preflight_or_error(root, spec, preview)
    try:
        with data_operation_transaction(root, spec, preview):
            confirmation = _confirm_direct_data_operation(
                root,
                operation_id="data.metadata.update",
                source_run_id=spec.source_run_id,
                source_node_id=spec.source_node_id,
                source_artifact_id=spec.source_artifact_id,
                preview_fingerprint=preview.fingerprint,
                source_sha256=preview.source_sha256,
                secondary_source_sha256=None,
                session_id=body.session_id,
                target_fields={
                    "metadata_fingerprint": preview.metadata_fingerprint,
                    "changed_columns": list(preview.changed_columns),
                },
                changes=spec.to_dict(),
            )
            effect = apply_metadata_mutation(root, spec, preview)
            metadata_operation = read_metadata_mutation_record(root, effect.record_id)
            operation = _complete_direct_data_operation(
                root,
                confirmation,
                effect,
                method="metadata_update",
                evidence={
                    "metadata_artifact_id": effect.metadata_artifact_id,
                    "metadata_revision": effect.metadata_revision,
                },
            )
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The metadata mutation could not be applied because its source changed.",
            details={"operation_id": "data.metadata.update", "reason": str(exc)},
        ) from exc
    return _bounded_data_consumer_value({
        "status": "completed",
        "effect": _bounded_data_consumer_effect(effect),
        "preview": _confirm_preview_payload(body, preview),
        "proposal": _bounded_data_consumer_proposal(confirmation["proposal"]),
        "confirmation": _bounded_data_consumer_confirmation(confirmation["confirmation"]),
        "operation": _bounded_metadata_operation_record(metadata_operation),
        "operation_record": operation,
    })


@router.get("/data-operations/metadata/{record_id}")
def get_metadata_mutation_route(project_root: str, record_id: str) -> dict[str, Any]:
    root = _root(project_root)
    try:
        operation = read_metadata_mutation_record(root, record_id)
        source = operation.get("source")
        artifact = operation.get("metadata_artifact")
        if not isinstance(source, dict) or not isinstance(artifact, dict):
            raise ValueError("metadata operation record is malformed")
        run_id = source.get("run_id")
        artifact_id = artifact.get("artifact_id")
        record_relative = artifact.get("path")
        record_sha = artifact.get("sha256")
        if not isinstance(run_id, str) or not isinstance(artifact_id, str):
            raise ValueError("metadata operation record has invalid artifact identity")
        run_root = (root / "runs" / run_id).resolve()
        index = read_json(run_root / "artifacts_index.json")
        rows = index.get("artifacts")
        if not isinstance(rows, list):
            raise ValueError("metadata artifact index is malformed")
        index_row = next(
            (row for row in rows if isinstance(row, dict) and row.get("artifact_id") == artifact_id),
            None,
        )
        if not isinstance(index_row, dict):
            raise ValueError("metadata artifact is not registered")
        relative = index_row.get("path")
        expected_sha = index_row.get("sha256")
        if (
            index_row.get("artifact_type") != "metadata"
            or not isinstance(relative, str)
            or not isinstance(expected_sha, str)
            or record_relative != relative
            or record_sha != expected_sha
        ):
            raise ValueError("metadata artifact provenance is not index-bound")
        artifact_path = (run_root / relative).resolve()
        artifact_path.relative_to(run_root)
        if not artifact_path.is_file():
            raise FileNotFoundError("metadata artifact is missing")
        from ..artifacts import sha256_file

        if expected_sha != sha256_file(artifact_path):
            raise ValueError("metadata artifact fingerprint changed")
        artifact_payload = read_json(artifact_path)
        metadata = artifact_payload.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("metadata artifact payload is malformed")
        reloaded = {
            "record_id": record_id,
            "operation_id": operation.get("operation_id"),
            "source": source,
            "metadata_fingerprint": operation.get("metadata_fingerprint"),
            **metadata,
            "child_node_id": operation.get("child_node_id"),
        }
        return {
            "metadata": _bounded_data_consumer_value(reloaded),
            "operation": _bounded_metadata_operation_record(operation),
        }
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed metadata mutation record was not found or is invalid.",
            details={"record_id": record_id, "reason": str(exc)},
        ) from exc


@router.get("/data-operations/profile")
def get_data_operation_profile(
    project_root: str,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> dict[str, Any]:
    """Return a bounded server-built profile for one immutable data artifact."""

    root = _root(project_root)
    try:
        profile = _resolve_profile(
            root,
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
        )
        return {"profile": _bounded_data_profile_projection(profile)}
    except DataMetadataUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_METADATA_UNAVAILABLE",
            message="The selected data artifact has no confirmed server-owned metadata registry.",
            details={"reason": str(exc)},
        ) from exc
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_PROFILE_INVALID",
            message="The selected data artifact cannot be profiled.",
            details={},
        ) from exc


@router.post("/data-operations/column-cast/preview")
def preview_column_cast(project_root: str, body: DataColumnCastRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.column.cast",
        preview_ref="/data-operations/column-cast/preview",
    )
    spec = _spec(body)
    preview = _preview_or_error(root, spec, confirm=False)
    return _bounded_data_consumer_value({"spec": _bounded_data_consumer_spec(spec), "preview": _preview_payload(body, preview)})


@router.post("/data-operations/column-cast/confirm")
async def confirm_column_cast(
    project_root: str,
    body: DataColumnCastConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.column.cast",
        confirm_ref="/data-operations/column-cast/confirm",
    )
    spec = _spec(body)
    preview = _preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The cast preview has blocking conversion failures.",
            details={"failure_count": preview.failure_count},
        )
    _preflight_or_error(root, spec, preview)

    registry = OperationRegistry()
    definition = registry.require("data.column.cast", "v1")
    target = {
        "run_id": spec.source_run_id,
        "node_ref": spec.source_node_id,
        "artifact_id": spec.source_artifact_id,
        "column": spec.column,
        "target_dtype": spec.target_dtype,
    }
    preconditions = {
        "context_version": "data-column-cast.v1",
        "context_fingerprint": preview.fingerprint,
        "active_head_run_id": spec.source_run_id,
        "owner_resolution": "typed_data_node",
    }
    changes = {"column": spec.column, "target_dtype": spec.target_dtype}
    definition.validate(target=target, preconditions=preconditions, changes=changes)
    proposal_id = f"proposal_data_cast_{preview.fingerprint[:24]}"
    return await _confirm_cast_operation(
        root,
        body,
        spec,
        preview,
        operation_id="data.column.cast",
        proposal_id=proposal_id,
        target=target,
        preconditions=preconditions,
        changes=changes,
    )


@router.post("/data-operations/columns-cast/preview")
def preview_columns_cast(project_root: str, body: DataColumnsCastRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.columns.cast",
        preview_ref="/data-operations/columns-cast/preview",
    )
    spec = _batch_spec(body)
    preview = _batch_preview_or_error(root, spec, confirm=False)
    return _bounded_data_consumer_value({"spec": _bounded_data_consumer_spec(spec), "preview": _preview_payload(body, preview)})


@router.post("/data-operations/columns-cast/confirm")
async def confirm_columns_cast(
    project_root: str,
    body: DataColumnsCastConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.columns.cast",
        confirm_ref="/data-operations/columns-cast/confirm",
    )
    spec = _batch_spec(body)
    preview = _batch_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The cast preview has blocking conversion failures.",
            details={
                "blocked_columns": [
                    item.column for item in preview.items if item.status != "ready"
                ]
            },
        )
    _preflight_or_error(root, spec, preview)

    registry = OperationRegistry()
    definition = registry.require("data.columns.cast", "v1")
    casts = [item.to_dict() for item in spec.casts]
    target = {
        "run_id": spec.source_run_id,
        "node_ref": spec.source_node_id,
        "artifact_id": spec.source_artifact_id,
        "casts": casts,
        "output_format": spec.output_format,
    }
    preconditions = {
        "context_version": "data-columns-cast.v1",
        "context_fingerprint": preview.fingerprint,
        "active_head_run_id": spec.source_run_id,
        "owner_resolution": "typed_data_node",
    }
    changes = {"casts": casts, "output_format": spec.output_format}
    definition.validate(target=target, preconditions=preconditions, changes=changes)
    proposal_id = f"proposal_data_casts_{preview.fingerprint[:24]}"
    return await _confirm_cast_operation(
        root,
        body,
        spec,
        preview,
        operation_id="data.columns.cast",
        proposal_id=proposal_id,
        target=target,
        preconditions=preconditions,
        changes=changes,
    )


@router.post("/data-operations/feature-recipe/preview")
def preview_feature_recipe_route(project_root: str, body: FeatureRecipeRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.feature_recipe",
        preview_ref="/data-operations/feature-recipe/preview",
    )
    spec = _feature_recipe_spec(body)
    preview = _feature_recipe_preview_or_error(root, spec, confirm=False)
    return _bounded_data_consumer_value({"spec": _bounded_data_consumer_spec(spec), "preview": _preview_payload(body, preview)})


@router.post("/data-operations/feature-recipe/confirm")
def confirm_feature_recipe_route(
    project_root: str,
    body: FeatureRecipeConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.feature_recipe",
        confirm_ref="/data-operations/feature-recipe/confirm",
    )
    spec = _feature_recipe_spec(body)
    preview = _feature_recipe_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The FeatureRecipe preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The FeatureRecipe preview has blocking validation failures.",
            details={"reason": preview.reason, "next_step": preview.next_step},
        )
    _preflight_or_error(root, spec, preview)
    try:
        with data_operation_transaction(root, spec, preview):
            confirmation = _confirm_direct_data_operation(
                root,
                operation_id="data.feature_recipe",
                source_run_id=spec.source_run_id,
                source_node_id=spec.source_node_id,
                source_artifact_id=spec.source_artifact_id,
                preview_fingerprint=preview.fingerprint,
                source_sha256=preview.source_sha256,
                secondary_source_sha256=None,
                session_id=body.session_id,
                target_fields={
                    "recipe_id": spec.recipe.recipe_id,
                    "recipe_operation_id": spec.recipe.operation_id,
                    "output": spec.recipe.outputs[0],
                },
                changes=spec.recipe.to_dict(),
            )
            effect = apply_feature_recipe_operation(root, spec, preview)
            operation = _complete_direct_data_operation(
                root,
                confirmation,
                effect,
                method="feature_recipe",
                evidence={"recipe_artifact_id": effect.recipe_artifact_id},
            )
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The FeatureRecipe could not be applied because its source changed.",
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc
    return _bounded_data_consumer_value({
        "status": "completed",
        "effect": _bounded_data_consumer_effect(effect),
        "preview": _confirm_preview_payload(body, preview),
        "proposal": _bounded_data_consumer_proposal(confirmation["proposal"]),
        "confirmation": _bounded_data_consumer_confirmation(confirmation["confirmation"]),
        "operation": operation,
        "operation_record": operation,
    })


@router.post("/data-operations/transform/preview")
def preview_data_transform_route(project_root: str, body: DataTransformRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        f"data.{body.operation}",
        preview_ref="/data-operations/transform/preview",
    )
    spec = _data_transform_spec(body)
    preview = _data_transform_preview_or_error(root, spec, confirm=False)
    return _bounded_data_consumer_value({"spec": _bounded_data_consumer_spec(spec), "preview": _preview_payload(body, preview)})


@router.post("/data-operations/transform/confirm")
def confirm_data_transform_route(
    project_root: str,
    body: DataTransformConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        f"data.{body.operation}",
        confirm_ref="/data-operations/transform/confirm",
    )
    spec = _data_transform_spec(body)
    preview = _data_transform_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The data transform preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    _preflight_or_error(root, spec, preview)
    try:
        with data_operation_transaction(root, spec, preview):
            confirmation = _confirm_direct_data_operation(
                root,
                operation_id=f"data.{spec.operation}",
                source_run_id=spec.source_run_id,
                source_node_id=spec.source_node_id,
                source_artifact_id=spec.source_artifact_id,
                preview_fingerprint=preview.fingerprint,
                source_sha256=preview.source_sha256,
                secondary_source_sha256=preview.secondary_source_sha256,
                session_id=body.session_id,
                target_fields={
                    "operation": spec.operation,
                    "secondary_run_id": spec.secondary_run_id,
                    "secondary_node_id": spec.secondary_node_id,
                    "secondary_artifact_id": spec.secondary_artifact_id,
                },
                changes=spec.to_dict(),
            )
            effect = apply_data_transform(root, spec, preview)
            operation = _complete_direct_data_operation(
                root,
                confirmation,
                effect,
                method=preview.method or f"data.{spec.operation}",
                evidence=dict(preview.evidence),
            )
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The data transform could not be applied because its source changed.",
            details={"operation_id": f"data.{spec.operation}", "reason": str(exc)},
        ) from exc
    return _bounded_data_consumer_value({
        "status": "completed",
        "effect": _bounded_data_consumer_effect(effect),
        "preview": _confirm_preview_payload(body, preview),
        "proposal": _bounded_data_consumer_proposal(confirmation["proposal"]),
        "confirmation": _bounded_data_consumer_confirmation(confirmation["confirmation"]),
        "operation": operation,
        "operation_record": operation,
    })


@router.post("/data-operations/model-run")
def start_model_from_data_node_route(
    project_root: str,
    body: DataModelRunRequest,
) -> dict[str, Any]:
    """Dispatch a real OLS run from a confirmed, materialized data-operation node.

    This is intentionally a narrow bridge: it reuses the existing run lifecycle,
    keeps the source node in ``run_inputs`` lineage, and does not invent a second
    estimator path for data operations.
    """

    root = _root(project_root)
    source_path, source, source_node_id = _model_source_or_error(root, body)
    from ..events import get_event_manager
    from ..services.run_service import _submit_run

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise WorkbenchAPIError(
            status_code=429,
            code="RUN_SLOT_BUSY",
            message="A run is already in progress.",
            details={"source_node_id": source_node_id},
        )
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        result = _submit_run(
            root,
            form={
                "mode": "auto",
                "model_type": body.model_type,
                "covariance": body.covariance or "robust",
                "y": body.y,
                "x": ",".join(body.x),
            },
            upload_bytes=source_path.read_bytes(),
            upload_filename=Path(source["artifact"].get("path") or "data.csv").name,
            started_at=started_at,
            rerun_of=body.source_run_id,
            from_node=source_node_id,
            rerun_reason="data_operation_model",
            rerun_from={
                "source_run_id": body.source_run_id,
                "op_node_id": source_node_id,
                "source_artifact_id": body.source_artifact_id,
                "source_node_hash": source.get("node_hash"),
            },
        )
    except WorkbenchAPIError:
        events.release_slot(None)
        raise
    except Exception as exc:
        events.release_slot(None)
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_DISPATCH_FAILED",
            message="The data node could not be submitted to the existing model lifecycle.",
            details={"reason": str(exc), "source_node_id": source_node_id},
        ) from exc
    return {
        "status": result["status"],
        "run_id": result["run_id"],
        "model_type": body.model_type,
        "source_lineage": {
            "source_run_id": body.source_run_id,
            "source_node_id": source_node_id,
            "source_artifact_id": body.source_artifact_id,
            "source_node_hash": source.get("node_hash"),
        },
    }


@router.post("/data-operations/code-execute/preview")
def preview_code_execute_route(project_root: str, body: CodeExecuteRequest) -> dict[str, Any]:
    root = _root(project_root)
    spec = _code_spec(body)
    preview = _code_preview_or_error(root, spec, confirm=False)
    return _bounded_data_consumer_value({"spec": _bounded_data_consumer_spec(spec), "preview": _preview_payload(body, preview)})


@router.post("/data-operations/code-execute/risk-authorize")
def authorize_code_execute_risk(
    project_root: str,
    body: CodeExecuteRiskAuthorizationRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _code_spec(body)
    preview = _code_preview_or_error(root, spec, confirm=True)
    _require_ready_code_preview(body, preview)
    context = _code_operation_context(root, body, spec, preview)
    proposal_store = context["proposal_store"]
    proposal = context["proposal"]
    try:
        proposal_store.confirm(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
        grant = RiskAuthorizationStore(context["workbench_root"]).issue(
            operation_id="code.execute",
            operation_version="v1",
            proposal_id=proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            session_id=proposal.session_id,
            chain_id=proposal.chain_id,
            active_head_run_id=spec.source_run_id,
            actor_type="human_ui",
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before risk authorization.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    return {
        "proposal": _bounded_data_consumer_proposal(
            proposal_store.latest_revision(proposal.proposal_id).to_dict()
        ),
        "risk_authorization": grant.to_dict(include_token=True),
        "status": "risk_authorized",
    }


@router.post("/data-operations/code-execute/confirm")
async def confirm_code_execute(
    project_root: str,
    body: CodeExecuteConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _code_spec(body)
    preview = _code_preview_or_error(root, spec, confirm=True)
    _require_ready_code_preview(body, preview)
    context = _code_operation_context(root, body, spec, preview)
    proposal_store = context["proposal_store"]
    proposal = context["proposal"]
    orchestrator = context["orchestrator"]
    try:
        confirmation = proposal_store.confirm(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
        record = orchestrator.operation_store.create_pending(
            confirmation,
            command_id=confirmation.command_id,
        )
        if not body.risk_authorization_id or not body.risk_authorization_token:
            raise RiskAuthorizationRequired(
                "code.execute requires explicit risk authorization before apply"
            )
        record = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=root,
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
            risk_authorization_id=body.risk_authorization_id,
            risk_authorization_token=body.risk_authorization_token,
        )
    except RiskAuthorizationExpired as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_EXPIRED",
            message="The high-risk authorization expired; review the preview again.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationReplay as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_REPLAY",
            message="The high-risk authorization has already been consumed.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationStale as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_STALE",
            message="The high-risk authorization no longer matches this preview or active head.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationRequired as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_REQUIRED",
            message="A high-risk operation needs explicit risk authorization before it can run.",
            details={
                "proposal_id": proposal.proposal_id,
                "operation_id": "code.execute",
                "risk_authorization_endpoint": "/data-operations/code-execute/risk-authorize",
            },
        ) from exc
    except NondeterministicCodeError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="CODE_NOT_DETERMINISTIC",
            message=(
                "The code produced a different result when it was run again, so it is "
                "not a deterministic transform. Nothing was written."
            ),
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before execution.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except OperationRecordTransitionError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_REPLAY",
            message=(
                "This operation already has an execution claim with another "
                "risk authorization."
            ),
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_INVALID",
            message="The high-risk authorization could not be validated.",
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    return {
        "proposal": _bounded_data_consumer_proposal(
            proposal_store.latest_revision(proposal.proposal_id).to_dict()
        ),
        "operation": _bounded_code_operation_record(record.to_dict()),
        "status": record.status,
    }


@router.get("/figures/ai-context")
def get_figure_ai_context(
    project_root: str,
    run_id: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Resolve a figure's chart type and backing numeric source for AI interpretation."""

    root = _root(project_root)
    try:
        return resolve_figure_ai_context(root, run_id=run_id, artifact_id=artifact_id)
    except (FigureContextError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="FIGURE_CONTEXT_NOT_FOUND",
            message="The figure or its numeric source could not be resolved.",
            details={"run_id": run_id, "artifact_id": artifact_id, "reason": str(exc)},
        ) from exc


@router.get("/data-operations/column-cast/context")
def get_column_cast_context(
    project_root: str,
    source_run_id: str,
    source_node_id: str,
) -> dict[str, Any]:
    root = _root(project_root)
    try:
        context = resolve_data_column_cast_context(
            root,
            source_run_id=source_run_id,
            source_node_id=source_node_id,
        )
        # The internal resolver needs the path for trusted server-side consumers,
        # but the HTTP context is a central data-consumer surface and must expose
        # only artifact identity, fingerprints, and schema metadata.
        context = dict(context)
        context.pop("source_artifact_path", None)
        return context
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The selected graph node is not a materialized dataset source.",
            details={"operation_id": "data.column.cast", "reason": str(exc)},
        ) from exc


@router.get("/data-operations/column-cast/by-child-node")
def get_column_cast_operation_by_child_node(
    project_root: str,
    child_node_id: str,
) -> dict[str, Any]:
    """Resolve the durable operation record from its typed child-node binding."""

    root = _root(project_root)
    store = OperationRecordStore(root / "workbench", create=False)
    matches = [
        record
        for record in store.list_records()
        if record.operation_id in _live_data_operation_ids()
        and (
            record.execution.get("bindings", {}).get("data_child_node_id") == child_node_id
            or record.execution.get("bindings", {}).get("child_node_id") == child_node_id
        )
    ]
    if not matches:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="No typed data operation record is bound to this child node.",
            details={"child_node_id": child_node_id},
    )
    matches.sort(key=lambda record: record.updated_at)
    operation = (
        _bounded_code_operation_record(matches[-1].to_dict())
        if matches[-1].operation_id == "code.execute"
        else _bounded_data_consumer_operation_record(matches[-1].to_dict())
    )
    if operation.get("operation_id") in {"data.column.cast", "data.columns.cast"}:
        operation = _legacy_cast_operation_view(operation)
    return {"operation": operation}


@router.get("/data-operations/column-cast/{record_id}")
def get_column_cast_operation(record_id: str, project_root: str) -> dict[str, Any]:
    root = _root(project_root)
    try:
        record = OperationRecordStore(root / "workbench").get(record_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed data operation record was not found.",
            details={"record_id": record_id},
        ) from exc
    if record.operation_id not in _live_data_operation_ids():
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed data operation record was not found.",
            details={"record_id": record_id},
        )
    operation = (
        _bounded_code_operation_record(record.to_dict())
        if record.operation_id == "code.execute"
        else _bounded_data_consumer_operation_record(record.to_dict())
    )
    if operation.get("operation_id") in {"data.column.cast", "data.columns.cast"}:
        operation = _legacy_cast_operation_view(operation)
    return {"operation": operation}
