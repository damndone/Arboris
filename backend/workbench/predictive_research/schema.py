"""Fail-closed payload schema registry for predictive-research packets.

Classification evidence is deliberately represented as a typed packet.  The
schema layer validates identity, status, and provenance shape; it never
calculates a metric or infers a model result.  That keeps Report, Notebook,
Table, Compare, and Agent consumers on the same evidence source.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping
from typing import Any, Iterable


class PayloadContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Schema:
    payload_schema: str
    schema_version: int
    required_fields: frozenset[str]


class PayloadSchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[tuple[str, int], _Schema] = {}

    def register(self, payload_schema: str, schema_version: int, *, required_fields: Iterable[str]) -> None:
        if not isinstance(payload_schema, str) or not payload_schema:
            raise PayloadContractError("ARTIFACT_PAYLOAD_SCHEMA_INVALID", "payload_schema is required")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise PayloadContractError("ARTIFACT_PAYLOAD_SCHEMA_VERSION_INVALID", "schema_version must be positive")
        key = (payload_schema, schema_version)
        if key in self._schemas:
            raise PayloadContractError("ARTIFACT_PAYLOAD_SCHEMA_DUPLICATE", "schema/version is already registered")
        self._schemas[key] = _Schema(payload_schema, schema_version, frozenset(required_fields))

    def validate(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise PayloadContractError("ARTIFACT_PAYLOAD_VALIDATION_FAILED", "payload must be an object")
        payload_schema = payload.get("payload_schema")
        schema_version = payload.get("schema_version")
        if payload_schema is None or schema_version is None:
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_REQUIRED", "payload_schema and schema_version are required")
        if not isinstance(payload_schema, str) or not isinstance(schema_version, int):
            raise PayloadContractError("ARTIFACT_PAYLOAD_VALIDATION_FAILED", "payload contract has invalid types")
        known_versions = [version for schema, version in self._schemas if schema == payload_schema]
        if not known_versions:
            raise PayloadContractError("ARTIFACT_PAYLOAD_SCHEMA_UNKNOWN", f"unknown payload schema {payload_schema!r}")
        schema = self._schemas.get((payload_schema, schema_version))
        if schema is None:
            raise PayloadContractError("ARTIFACT_PAYLOAD_SCHEMA_VERSION_UNSUPPORTED", "payload schema version is unsupported")
        missing = schema.required_fields - payload.keys()
        if missing:
            raise PayloadContractError("ARTIFACT_PAYLOAD_VALIDATION_FAILED", f"missing payload fields: {sorted(missing)}")
        return dict(payload)


CLASSIFICATION_PACKET_SCHEMA = "workbench.classification.evidence-packet"
CLASSIFICATION_PACKET_VERSION = 1
CLASSIFICATION_GRAPH_SCHEMA = "workbench.classification.graph"

_CLASSIFICATION_PACKET_REQUIRED_FIELDS = frozenset(
    {
        "payload_schema",
        "schema_version",
        "packet_id",
        "packet_hash",
        "status",
        "task",
        "split",
        "models",
        "selected_model",
        "evaluation",
        "calibration",
        "baselines",
        "controls",
        "comparison",
        "explanations",
        "decision_policy",
        "holdout_boundary",
        "availability",
        "warnings",
        "artifact_refs",
        "evidence_receipt",
    }
)

_CLASSIFICATION_STATUSES = frozenset({"validated", "blocked", "unavailable"})
_CLASSIFICATION_HOLDOUT_STATUSES = frozenset(
    {"sealed_not_opened", "evaluated_once", "blocked", "unavailable"}
)


def _classification_text(value: object, *, code: str, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise PayloadContractError(code, f"{label} must be a non-empty string")
    return value


def _classification_mapping(value: object, *, code: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PayloadContractError(code, f"{label} must be an object")
    return dict(value)


def _classification_string_list(value: object, *, code: str, label: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item for item in value):
        raise PayloadContractError(code, f"{label} must be a list of non-empty strings")
    return list(value)


def _classification_json_safe(value: object) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PayloadContractError(
            "CLASSIFICATION_PACKET_NOT_JSON_SAFE",
            "classification evidence must be finite and JSON serializable",
        ) from exc


def classification_content_hash(payload: Mapping[str, Any]) -> str:
    """Return a stable identity for a validated packet or graph payload."""

    canonical_payload = dict(payload)
    # packet_hash is a receipt over the packet body, not a recursive input to
    # its own digest.  This keeps a stored packet hash independently
    # recomputable by every consumer.
    canonical_payload.pop("packet_hash", None)
    _classification_json_safe(canonical_payload)
    encoded = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_classification_packet(payload: Any) -> dict[str, Any]:
    """Validate the packet boundary used by every classification consumer.

    This function intentionally permits additive fields inside the typed
    sections so future model families can extend the packet without changing
    the consumer control flow.  It rejects missing identity/provenance fields
    and never fills missing numeric values with defaults.
    """

    if not isinstance(payload, Mapping):
        raise PayloadContractError("CLASSIFICATION_PACKET_INVALID", "classification packet must be an object")
    _classification_json_safe(payload)
    packet = dict(payload)
    if "packet_hash" not in packet:
        raise PayloadContractError(
            "CLASSIFICATION_PACKET_HASH_REQUIRED",
            "classification packet hash is required",
        )
    missing = _CLASSIFICATION_PACKET_REQUIRED_FIELDS - packet.keys()
    if missing:
        raise PayloadContractError(
            "CLASSIFICATION_PACKET_FIELDS_INVALID",
            f"missing classification packet fields: {sorted(missing)}",
        )
    if packet.get("payload_schema") != CLASSIFICATION_PACKET_SCHEMA:
        raise PayloadContractError("CLASSIFICATION_PACKET_SCHEMA_INVALID", "classification packet schema is unsupported")
    if packet.get("schema_version") != CLASSIFICATION_PACKET_VERSION:
        raise PayloadContractError("CLASSIFICATION_PACKET_VERSION_INVALID", "classification packet version is unsupported")
    _classification_text(packet.get("packet_id"), code="CLASSIFICATION_PACKET_ID_INVALID", label="packet_id")
    if packet.get("packet_hash") != classification_content_hash(packet):
        raise PayloadContractError(
            "CLASSIFICATION_PACKET_HASH_INVALID",
            "classification packet hash does not match its packet body",
        )
    status = packet.get("status")
    if status not in _CLASSIFICATION_STATUSES:
        raise PayloadContractError("CLASSIFICATION_PACKET_STATUS_INVALID", "classification packet status is unsupported")

    for field_name in (
        "task",
        "split",
        "evaluation",
        "calibration",
        "comparison",
        "explanations",
        "decision_policy",
        "holdout_boundary",
        "availability",
        "artifact_refs",
        "evidence_receipt",
    ):
        _classification_mapping(
            packet[field_name],
            code="CLASSIFICATION_PACKET_SECTION_INVALID",
            label=field_name,
        )
    if type(packet["models"]) is not list:
        raise PayloadContractError("CLASSIFICATION_PACKET_MODELS_INVALID", "models must be a list")
    if any(not isinstance(model, Mapping) for model in packet["models"]):
        raise PayloadContractError("CLASSIFICATION_PACKET_MODELS_INVALID", "each model must be an object")
    for field_name in ("baselines", "controls"):
        if type(packet[field_name]) is not list:
            raise PayloadContractError("CLASSIFICATION_PACKET_SECTION_INVALID", f"{field_name} must be a list")
    _classification_string_list(
        packet["warnings"],
        code="CLASSIFICATION_PACKET_SECTION_INVALID",
        label="warnings",
    )
    if packet["selected_model"] is not None and not isinstance(packet["selected_model"], Mapping):
        raise PayloadContractError("CLASSIFICATION_PACKET_SELECTED_MODEL_INVALID", "selected_model must be an object or null")

    holdout = packet["holdout_boundary"]
    holdout_status = holdout.get("status")
    if holdout_status not in _CLASSIFICATION_HOLDOUT_STATUSES:
        raise PayloadContractError(
            "CLASSIFICATION_HOLDOUT_BOUNDARY_INVALID",
            "holdout_boundary.status is unsupported",
        )
    _classification_text(
        holdout.get("metric_release_plan_hash"),
        code="CLASSIFICATION_HOLDOUT_BOUNDARY_INVALID",
        label="holdout_boundary.metric_release_plan_hash",
    )
    if type(holdout.get("access_count")) is not int or holdout["access_count"] < 0:
        raise PayloadContractError(
            "CLASSIFICATION_HOLDOUT_BOUNDARY_INVALID",
            "holdout_boundary.access_count must be a non-negative integer",
        )
    if status == "blocked":
        blocked_invalid = (
            holdout_status != "blocked"
            or holdout["access_count"] != 0
            or packet["selected_model"] is not None
            or bool(packet["models"])
            or packet["evaluation"].get("status") != "unavailable"
            or packet["evaluation"].get("metrics") != {}
            or packet["calibration"].get("status") != "unavailable"
            or bool(packet["baselines"])
            or bool(packet["controls"])
            or packet["comparison"].get("status") != "unavailable"
            or packet["explanations"].get("status") != "unavailable"
            or packet["decision_policy"].get("status") != "unavailable"
            or packet["availability"].get("status") == "VALIDATED"
        )
        if blocked_invalid:
            raise PayloadContractError(
                "CLASSIFICATION_BLOCKED_PACKET_EVIDENCE_INVALID",
                "blocked classification packets cannot contain holdout or selected-model evidence",
            )
    if holdout_status == "evaluated_once":
        _classification_text(
            holdout.get("authorization_ref"),
            code="CLASSIFICATION_HOLDOUT_BOUNDARY_INVALID",
            label="holdout_boundary.authorization_ref",
        )
        if holdout["access_count"] != 1:
            raise PayloadContractError(
                "CLASSIFICATION_HOLDOUT_BOUNDARY_INVALID",
                "evaluated holdout must have exactly one access",
            )
    if holdout_status != "evaluated_once" and holdout["access_count"] != 0:
        raise PayloadContractError(
            "CLASSIFICATION_HOLDOUT_BOUNDARY_INVALID",
            "an unopened or blocked holdout cannot have an access count",
        )

    if status in {"blocked", "unavailable"}:
        blocked_evidence = (
            packet.get("selected_model") is not None
            or bool(packet.get("models"))
            or bool(packet.get("baselines"))
            or bool(packet.get("controls"))
            or bool(packet["evaluation"].get("metrics"))
            or packet["calibration"].get("status") not in {"unavailable", "blocked"}
            or packet["comparison"].get("status") not in {"unavailable", "blocked"}
            or packet["explanations"].get("status") not in {"unavailable", "blocked"}
            or packet["decision_policy"].get("status") not in {"unavailable", "blocked"}
            or holdout_status not in {"blocked", "unavailable"}
        )
        if blocked_evidence:
            raise PayloadContractError(
                "CLASSIFICATION_BLOCKED_PACKET_EVIDENCE_INVALID",
                "blocked or unavailable classification packets cannot contain released evidence",
            )

    receipt = packet["evidence_receipt"]
    _classification_text(
        receipt.get("receipt_id"),
        code="CLASSIFICATION_EVIDENCE_RECEIPT_INVALID",
        label="evidence_receipt.receipt_id",
    )
    sources = receipt.get("source_artifacts")
    if type(sources) is not list or not sources or any(type(item) is not str or not item for item in sources):
        raise PayloadContractError(
            "CLASSIFICATION_EVIDENCE_RECEIPT_INVALID",
            "evidence_receipt.source_artifacts must contain at least one artifact ref",
        )
    _classification_text(
        receipt.get("validation_level"),
        code="CLASSIFICATION_EVIDENCE_RECEIPT_INVALID",
        label="evidence_receipt.validation_level",
    )

    artifact_refs = packet["artifact_refs"]
    if not artifact_refs or any(type(value) is not str or not value for value in artifact_refs.values()):
        raise PayloadContractError(
            "CLASSIFICATION_ARTIFACT_REFS_INVALID",
            "artifact_refs must contain non-empty typed references",
        )
    if status == "blocked" and not packet["warnings"]:
        raise PayloadContractError(
            "CLASSIFICATION_PACKET_BLOCK_REASON_REQUIRED",
            "blocked classification packets must expose a warning or blocked reason",
        )
    return packet


def build_classification_packet(
    *,
    packet_id: str,
    task: Mapping[str, Any],
    split: Mapping[str, Any],
    models: list[Mapping[str, Any]],
    selected_model: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any],
    calibration: Mapping[str, Any],
    baselines: list[Mapping[str, Any]],
    controls: list[Mapping[str, Any]],
    comparison: Mapping[str, Any],
    explanations: Mapping[str, Any],
    decision_policy: Mapping[str, Any],
    holdout_boundary: Mapping[str, Any],
    availability: Mapping[str, Any],
    warnings: list[str],
    artifact_refs: Mapping[str, str],
    evidence_receipt: Mapping[str, Any],
    status: str = "validated",
) -> dict[str, Any]:
    """Construct, then validate, an additive classification evidence packet."""

    packet = {
        "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
        "schema_version": CLASSIFICATION_PACKET_VERSION,
        "packet_id": packet_id,
        "status": status,
        "task": dict(task),
        "split": dict(split),
        "models": [dict(model) for model in models],
        "selected_model": dict(selected_model) if selected_model is not None else None,
        "evaluation": dict(evaluation),
        "calibration": dict(calibration),
        "baselines": [dict(item) for item in baselines],
        "controls": [dict(item) for item in controls],
        "comparison": dict(comparison),
        "explanations": dict(explanations),
        "decision_policy": dict(decision_policy),
        "holdout_boundary": dict(holdout_boundary),
        "availability": dict(availability),
        "warnings": list(warnings),
        "artifact_refs": dict(artifact_refs),
        "evidence_receipt": dict(evidence_receipt),
    }
    packet["packet_hash"] = classification_content_hash(packet)
    return validate_classification_packet(packet)


def default_v1_prediction_registry() -> PayloadSchemaRegistry:
    """Return the bounded registry for the new v1.8.6 packet families."""

    registry = PayloadSchemaRegistry()
    envelope = {"payload_schema", "schema_version"}
    for payload_schema in (
        "workbench.prediction.sample-spec",
        "workbench.prediction.task-spec",
        "workbench.prediction.split-plan",
        "workbench.prediction.preprocessing-plan",
        "workbench.prediction.feature-recipe",
        "workbench.prediction.prediction-packet",
        "workbench.prediction.evaluation-packet",
        "workbench.prediction.negative-control-packet",
        "workbench.prediction.model-comparison-packet",
        "workbench.statistics.evidence-packet",
        CLASSIFICATION_PACKET_SCHEMA,
        CLASSIFICATION_GRAPH_SCHEMA,
    ):
        registry.register(payload_schema, 1, required_fields=envelope)
    return registry
