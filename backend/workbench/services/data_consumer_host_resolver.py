"""Server-owned durable resolver for the v1.8.9 data-consumer port.

The generic Agent/Notebook runtime is deliberately not allowed to open a
project directory or receive a dataframe.  This module is the application
bootstrap seam that resolves an opaque runtime request against the server's
durable OperationRecord store and returns only the typed identity/evidence
projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from workbench.agent.operations import OperationRecord, OperationRecordStore
from workbench.canonical import sha256_canonical
from workbench.data_operation_manifest import (
    DataConsumerExecutionPortV1,
    DataConsumerRuntimeOutputV1,
    _DATA_OPERATION_IDS,
    _SERVER_OWNED_CAPABILITY,
    _SERVER_OWNED_ISSUER,
    _reject_data_host_raw_payload,
)


class DataConsumerHostResolverError(ValueError):
    """A durable data-consumer result could not be resolved safely."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


_REQUEST_FIELDS = frozenset(
    {
        "capability_id",
        "target_ref",
        "data_snapshot_ref",
        "source_text_digest",
        "operation_id",
        "source_run_id",
        "source_node_id",
        "source_artifact_id",
        "operation",
        "options",
    }
)
_ARTIFACT_ID_FIELDS = frozenset(
    {"artifact_id", "metadata_artifact_id", "recipe_artifact_id", "group_manifest_id"}
)
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


def _non_empty(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_REQUEST_INVALID",
            f"{field_name} must be a non-empty opaque identity",
        )
    return value


def _claim(record: OperationRecord, field_name: str) -> object | None:
    values = []
    for container in (record.target, record.preconditions):
        if isinstance(container, Mapping) and field_name in container:
            values.append(container[field_name])
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID",
            f"record has conflicting {field_name} claims",
        )
    return values[0]


def _require_safe_identity(value: object, field_name: str) -> str:
    identity = _non_empty(value, field_name)
    if "/" in identity or "\\" in identity or ".." in identity:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID",
            f"{field_name} must not be path-like",
        )
    return identity


def _validate_request(request: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(request, Mapping):
        raise DataConsumerHostResolverError("DATA_CONSUMER_HOST_REQUEST_INVALID")
    try:
        _reject_data_host_raw_payload(request)
    except (TypeError, ValueError) as exc:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_REQUEST_INVALID", "raw data fields are not accepted"
        ) from exc
    unknown = sorted(set(request) - _REQUEST_FIELDS)
    if unknown:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_REQUEST_INVALID",
            "unsupported field(s): " + ", ".join(str(item) for item in unknown),
        )
    normalized = dict(request)
    options = normalized.get("options")
    if options is not None and not isinstance(options, Mapping):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_REQUEST_INVALID", "options must be an object"
        )
    operation_id = normalized.get("operation_id")
    if operation_id is None and isinstance(options, Mapping):
        operation_id = options.get("operation_id")
    if type(operation_id) is not str or operation_id not in _DATA_OPERATION_IDS:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_OPERATION_INVALID",
            "operation_id is not a declared data operation",
        )
    normalized["operation_id"] = operation_id
    _non_empty(normalized.get("target_ref"), "target_ref")
    _non_empty(normalized.get("data_snapshot_ref"), "data_snapshot_ref")
    for field_name in (
        "capability_id",
        "source_text_digest",
        "source_run_id",
        "source_node_id",
        "source_artifact_id",
        "operation",
    ):
        if field_name in normalized and normalized[field_name] is not None:
            _non_empty(normalized[field_name], field_name)
    return normalized


def _validate_record_output(
    record: OperationRecord,
    *,
    catalog_digest: str,
) -> DataConsumerRuntimeOutputV1:
    if record.status != "completed" or record.effect_status != "committed" or record.projection_status != "committed":
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RESULT_UNAVAILABLE",
            "the durable data operation is not fully committed",
        )
    execution_key = record.execution.get("execution_key")
    bindings = record.execution.get("bindings")
    if type(execution_key) is not str or not execution_key or not isinstance(bindings, Mapping):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID",
            "the durable operation has no exact execution binding",
        )
    outputs = record.outputs
    if not isinstance(outputs, Mapping) or set(outputs) != {"ports", "consumer_slots", "catalog_digest"}:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the durable output schema is not exact"
        )
    if outputs.get("catalog_digest") != catalog_digest:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RESULT_STALE", "the durable output uses a stale catalog"
        )
    ports = outputs.get("ports")
    slots = outputs.get("consumer_slots")
    if not isinstance(ports, Mapping) or set(ports) != {"derived", "operation_record", "evidence"}:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the durable ports schema is not exact"
        )
    if not isinstance(slots, Mapping) or set(slots) != {"data.agent", "data.notebook", "data.report"}:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the durable consumer slots are not exact"
        )
    operation_port = ports.get("operation_record")
    if (
        not isinstance(operation_port, Mapping)
        or set(operation_port) != {"record_id", "operation_id", "operation_version"}
        or operation_port.get("record_id") != record.record_id
        or operation_port.get("operation_id") != record.operation_id
        or operation_port.get("operation_version") != record.operation_version
    ):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the OperationRecord port is not bound"
        )
    derived = ports.get("derived")
    if not isinstance(derived, Mapping) or not derived:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the derived port is missing"
        )
    if not set(derived).issubset(_DATA_CONSUMER_SAFE_EFFECT_FIELDS):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the derived port contains undeclared fields"
        )
    if any(type(value) is not str or not value for value in derived.values()):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "the derived port contains an invalid identity"
        )
    expected_bindings = {
        str(key): str(value)
        for key, value in derived.items()
        if str(key).endswith("_id") and value is not None
    }
    actual_bindings = {str(key): str(value) for key, value in bindings.items()}
    if actual_bindings != expected_bindings:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "effect bindings do not match the durable output"
        )
    if derived.get("execution_key") != execution_key:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "derived output is not bound to execution"
        )
    child_node_id = _require_safe_identity(derived.get("child_node_id"), "child_node_id")
    artifact_ids = tuple(
        sorted(
            _require_safe_identity(derived[field_name], field_name)
            for field_name in _ARTIFACT_ID_FIELDS
            if field_name in derived and derived[field_name] is not None
        )
    )
    if not artifact_ids:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "derived output has no artifact identity"
        )
    evidence = ports.get("evidence")
    if not isinstance(evidence, Mapping):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "evidence port is missing"
        )
    if any(type(key) is not str for key in evidence):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "evidence field names are invalid"
        )
    try:
        _reject_data_host_raw_payload(evidence)
    except (TypeError, ValueError) as exc:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "evidence contains a raw field"
        ) from exc
    required_evidence = {
        "record_id": record.record_id,
        "operation_id": record.operation_id,
        "execution_key": execution_key,
        "child_node_id": child_node_id,
    }
    if any(evidence.get(key) != value for key, value in required_evidence.items()):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_HOST_RECORD_INVALID", "evidence is not bound to the record"
        )
    for slot_name, expected_port in (
        ("data.agent", "derived"),
        ("data.notebook", "derived"),
        ("data.report", "evidence"),
    ):
        slot = slots.get(slot_name)
        if (
            not isinstance(slot, Mapping)
            or set(slot) != {"record_id", "port"}
            or slot.get("record_id") != record.record_id
            or slot.get("port") != expected_port
        ):
            raise DataConsumerHostResolverError(
                "DATA_CONSUMER_HOST_RECORD_INVALID",
                f"consumer slot {slot_name} is not bound",
            )
    return DataConsumerRuntimeOutputV1.from_server(
        record_id=record.record_id,
        operation_id=record.operation_id,
        operation_version=record.operation_version,
        execution_key=execution_key,
        child_node_id=child_node_id,
        artifact_ids=artifact_ids,
        evidence_digest=sha256_canonical(dict(evidence)),
        catalog_digest=catalog_digest,
        _issuer=_SERVER_OWNED_ISSUER,
    )


@dataclass(frozen=True)
class ServerOwnedDataConsumerHostResolverV1:
    """Resolve one server-scoped request against durable data evidence."""

    project_root: Path
    project_ref: str
    session_ref: str
    catalog_digest: str
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("data host resolver can only be created by the server")
        if not isinstance(self.project_root, Path):
            raise TypeError("data host resolver project_root must be a Path")
        if not self.project_root.is_absolute():
            raise ValueError("data host resolver requires a server-owned absolute project root")
        _non_empty(self.project_ref, "project_ref")
        _non_empty(self.session_ref, "session_ref")
        _non_empty(self.catalog_digest, "catalog_digest")

    @classmethod
    def from_server(
        cls,
        *,
        project_root: Path | str,
        project_ref: str,
        session_ref: str,
        catalog_digest: str,
        _issuer: object | None = None,
    ) -> "ServerOwnedDataConsumerHostResolverV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("data host resolver requires the server-owned issuer")
        return cls(
            project_root=Path(project_root).resolve(),
            project_ref=project_ref,
            session_ref=session_ref,
            catalog_digest=catalog_digest,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    def as_execution_port(self) -> DataConsumerExecutionPortV1:
        return DataConsumerExecutionPortV1.from_server(
            self.resolve,
            catalog_digest=self.catalog_digest,
            _issuer=_SERVER_OWNED_ISSUER,
        )

    def resolve(self, context: object, request: Mapping[str, object]) -> DataConsumerRuntimeOutputV1:
        from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

        if type(context) is not ProviderRuntimeContextV1:
            raise TypeError("data host resolver requires a server runtime context")
        if context.project_ref != self.project_ref or context.session_ref != self.session_ref:
            raise DataConsumerHostResolverError("DATA_CONSUMER_HOST_SCOPE_MISMATCH")
        normalized = _validate_request(request)
        operation_id = str(normalized["operation_id"])
        target_ref = str(normalized["target_ref"])
        snapshot_ref = str(normalized["data_snapshot_ref"])
        store = OperationRecordStore(self.project_root / "workbench", create=False)
        try:
            records = store.list_records()
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
            raise DataConsumerHostResolverError(
                "DATA_CONSUMER_HOST_RESULT_UNAVAILABLE", "operation records are unavailable"
            ) from exc
        matches: list[OperationRecord] = []
        for record in records:
            if record.operation_id != operation_id or record.agent_session_id != self.session_ref:
                continue
            try:
                project_claim = _claim(record, "project_ref")
                run_claim = _claim(record, "run_id")
                snapshot_claim = _claim(record, "data_snapshot_ref")
            except DataConsumerHostResolverError:
                continue
            if project_claim != self.project_ref or run_claim != target_ref or snapshot_claim != snapshot_ref:
                continue
            if record.target.get("source_run_id") not in {None, target_ref}:
                continue
            if normalized.get("source_run_id") is not None and _claim(record, "source_run_id") != normalized["source_run_id"]:
                continue
            if normalized.get("source_node_id") is not None and _claim(record, "source_node_id") != normalized["source_node_id"]:
                continue
            if normalized.get("source_artifact_id") is not None and _claim(record, "source_artifact_id") != normalized["source_artifact_id"]:
                continue
            matches.append(record)
        if len(matches) == 0:
            raise DataConsumerHostResolverError(
                "DATA_CONSUMER_HOST_RESULT_UNAVAILABLE",
                "no exact completed server-owned data result matched the request",
            )
        if len(matches) != 1:
            raise DataConsumerHostResolverError(
                "DATA_CONSUMER_HOST_RESULT_AMBIGUOUS",
                "more than one durable data result matched the request",
            )
        return _validate_record_output(matches[0], catalog_digest=self.catalog_digest)


def build_server_owned_data_consumer_execution_port(
    *,
    project_root: Path | str,
    project_ref: str,
    session_ref: str,
    catalog_digest: str,
) -> DataConsumerExecutionPortV1:
    """Create the default application-scoped data execution port."""

    resolver = ServerOwnedDataConsumerHostResolverV1.from_server(
        project_root=project_root,
        project_ref=project_ref,
        session_ref=session_ref,
        catalog_digest=catalog_digest,
        _issuer=_SERVER_OWNED_ISSUER,
    )
    return resolver.as_execution_port()


__all__ = [
    "DataConsumerHostResolverError",
    "ServerOwnedDataConsumerHostResolverV1",
    "build_server_owned_data_consumer_execution_port",
]
