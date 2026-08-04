"""Small fail-closed payload schema registry for new v1.8.6 packets."""

from __future__ import annotations

from dataclasses import dataclass
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
    ):
        registry.register(payload_schema, 1, required_fields=envelope)
    return registry
