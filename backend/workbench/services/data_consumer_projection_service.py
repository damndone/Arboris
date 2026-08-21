"""Server-owned data-operation projections for Agent, Notebook, and Report.

The data-operation package already persists a typed ``OperationRecord`` and
three output slots.  This module is the read boundary for those slots.  It
does not open an artifact path or recalculate a dataframe result; it only
rehydrates the bounded identities and digests that the server committed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import secrets
from typing import Any
import weakref

from ..agent.operations import OperationRecord, OperationRecordStore
from ..canonical import sha256_canonical
from ..data_operation_manifest import _DATA_OPERATION_IDS, build_data_consumer_runtime_adapter
from ..predictive_research.contracts import ContractError
from .data_consumer_host_resolver import (
    DataConsumerHostResolverError,
    _claim,
    _validate_record_output,
)


_CONSUMERS = frozenset({"agent", "notebook", "report"})
_SCHEMA = "workbench.data.consumer-evidence.v1"
_RECEIPT_SCHEMA = "evidence.data-consumer.server-receipt.v1"
_SERVER_CAPABILITY_ISSUER = object()


class DataConsumerProjectionError(ContractError):
    """A data projection request is not admissible at the server boundary."""


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DataConsumerRunCapabilityV1:
    """Opaque server-issued handle for one project/session/run scope."""

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("data-consumer run capabilities are server-issued")


@dataclass(frozen=True, slots=True)
class _CapabilityRecord:
    run_root: Path
    project_ref: str
    session_ref: str
    run_id: str
    catalog_digest: str


_CAPABILITY_RECORDS: weakref.WeakKeyDictionary[
    DataConsumerRunCapabilityV1, _CapabilityRecord
] = weakref.WeakKeyDictionary()


def _require_identity(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip() or "\x00" in value:
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_PROJECTION_IDENTITY_INVALID",
            f"{name} must be a non-empty server identity",
        )
    return value


def _live_catalog_digest() -> str:
    try:
        return build_data_consumer_runtime_adapter().catalog_digest
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_CATALOG_UNAVAILABLE",
            "the live server data-consumer catalog is unavailable",
        ) from exc


def _capability_record(capability: object) -> _CapabilityRecord:
    if type(capability) is not DataConsumerRunCapabilityV1:
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_RUN_CAPABILITY_REQUIRED",
            "data evidence requires a server-issued run capability",
        )
    record = _CAPABILITY_RECORDS.get(capability)
    if record is None:
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_RUN_CAPABILITY_REQUIRED",
            "data-consumer run capability is unknown or expired",
        )
    return record


def _resolved_run_root(run_root: Path) -> Path:
    if not isinstance(run_root, Path):
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_RUN_CAPABILITY_MINT_INVALID",
            "run capability must be minted from a server-resolved Path",
        )
    if run_root.is_symlink() or run_root.parent.is_symlink() or run_root.parent.parent.is_symlink():
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_RUN_CAPABILITY_MINT_INVALID",
            "run capability cannot be minted through a symlinked project boundary",
        )
    resolved = run_root.expanduser().resolve(strict=False)
    if (
        not resolved.is_absolute()
        or not resolved.is_dir()
        or resolved.parent.name != "runs"
        or not resolved.parent.parent.is_dir()
    ):
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_RUN_CAPABILITY_MINT_INVALID",
            "run capability requires an existing project/runs/run directory",
        )
    return resolved


def issue_data_consumer_run_capability(
    run_root: Path,
    *,
    project_ref: str,
    session_ref: str,
) -> DataConsumerRunCapabilityV1:
    """Mint an opaque capability at a server-owned Report/runtime boundary."""

    resolved = _resolved_run_root(run_root)
    project = _require_identity(project_ref, "project_ref")
    session = _require_identity(session_ref, "session_ref")
    catalog_digest = _live_catalog_digest()
    capability = object.__new__(DataConsumerRunCapabilityV1)
    object.__setattr__(capability, "_token", secrets.token_urlsafe(32))
    _CAPABILITY_RECORDS[capability] = _CapabilityRecord(
        run_root=resolved,
        project_ref=project,
        session_ref=session,
        run_id=resolved.name,
        catalog_digest=catalog_digest,
    )
    return capability


def _unavailable(consumer_id: str, reason_code: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "payload_schema": _SCHEMA,
        "consumer_id": consumer_id,
        "status": "unavailable",
        "availability": "unavailable",
        "execution_status": "unavailable",
        "completeness_status": "unavailable",
        "authority": "server-owned",
        "source": "persisted-data-operation-output",
        "facts": [],
        "projection_digest": None,
        "catalog_digest": None,
        "reason_code": reason_code,
        "receipt": None,
    }


def _claim_required(record: OperationRecord, field_name: str) -> str:
    value = _claim(record, field_name)
    if type(value) is not str or not value.strip() or value != value.strip():
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_PROJECTION_IDENTITY_UNAVAILABLE",
            f"record is missing the exact {field_name} claim",
        )
    return value


def _opaque_claim_required(record: OperationRecord, field_name: str) -> str:
    value = _claim_required(record, field_name)
    if "/" in value or "\\" in value or ".." in value:
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_PROJECTION_IDENTITY_INVALID",
            f"{field_name} must be an opaque identity",
        )
    return value


def _record_matches(record: OperationRecord, scope: _CapabilityRecord) -> bool:
    if record.operation_id not in _DATA_OPERATION_IDS:
        return False
    if record.agent_session_id != scope.session_ref:
        return False
    try:
        return (
            _claim_required(record, "project_ref") == scope.project_ref
            and _claim_required(record, "run_id") == scope.run_id
            and _claim_required(record, "source_run_id") == scope.run_id
        )
    except DataConsumerHostResolverError:
        # Legacy records are not consumer evidence.  They remain available to
        # their old bounded compatibility endpoints but cannot be promoted to
        # the central data projection without the new identity claims.
        return False


def _fact_for_record(
    record: OperationRecord,
    *,
    output: Any,
    scope: _CapabilityRecord,
) -> dict[str, object]:
    source_run_id = _opaque_claim_required(record, "source_run_id")
    source_node_id = _opaque_claim_required(record, "source_node_id")
    source_artifact_id = _opaque_claim_required(record, "source_artifact_id")
    snapshot_ref = _opaque_claim_required(record, "data_snapshot_ref")
    snapshot_digest = _claim_required(record, "data_snapshot_digest")
    if (
        len(snapshot_digest) != 64
        or any(character not in "0123456789abcdef" for character in snapshot_digest)
    ):
        raise DataConsumerHostResolverError(
            "DATA_CONSUMER_PROJECTION_IDENTITY_INVALID",
            "data_snapshot_digest must be a lowercase SHA-256 digest",
        )
    evidence = record.outputs.get("ports", {}).get("evidence")
    method = evidence.get("method") if isinstance(evidence, Mapping) else None
    fact: dict[str, object] = {
        "fact_id": f"data-operation:{record.record_id}",
        "kind": "data_operation",
        "operation_id": output.operation_id,
        "operation_version": output.operation_version,
        "record_id": output.record_id,
        "execution_key": output.execution_key,
        "child_node_id": output.child_node_id,
        "artifact_ids": list(output.artifact_ids),
        "evidence_digest": output.evidence_digest,
        "catalog_digest": output.catalog_digest,
        "run_id": scope.run_id,
        "source_run_id": source_run_id,
        "source_node_id": source_node_id,
        "source_artifact_id": source_artifact_id,
        "data_snapshot_ref": snapshot_ref,
        "data_snapshot_digest": snapshot_digest,
    }
    if type(method) is str and method.strip():
        fact["method"] = method
    return fact


def _projection_digest(
    facts: Sequence[Mapping[str, object]],
    scope: _CapabilityRecord,
) -> str:
    """Hash the source projection, not the consumer label.

    Agent, Notebook, and Report may wrap the same facts differently at their
    presentation boundary, but the source digest must prove that they read
    one server-owned data projection rather than independently recomputing it.
    """

    return sha256_canonical(
        {
            "schema_version": 1,
            "payload_schema": _SCHEMA,
            "scope_digest": sha256_canonical(
                {"project_ref": scope.project_ref, "session_ref": scope.session_ref, "run_id": scope.run_id}
            ),
            "facts": [dict(fact) for fact in facts],
            "catalog_digest": scope.catalog_digest,
        }
    )


def read_data_consumer_projection(
    capability: object,
    consumer_id: str,
    *,
    requested_fact_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    """Read one bounded projection shared by all three central consumers."""

    scope = _capability_record(capability)
    if consumer_id not in _CONSUMERS:
        raise DataConsumerProjectionError(
            "DATA_CONSUMER_UNSUPPORTED_CONSUMER",
            f"unsupported data consumer {consumer_id!r}",
        )
    if requested_fact_ids is not None:
        if type(requested_fact_ids) not in {tuple, list} or any(
            type(value) is not str or not value.strip() for value in requested_fact_ids
        ):
            return _unavailable(consumer_id, "DATA_CONSUMER_FACT_SELECTOR_INVALID")
        requested = set(requested_fact_ids)
    else:
        requested = None
    try:
        live_catalog_digest = _live_catalog_digest()
    except DataConsumerProjectionError as exc:
        return _unavailable(consumer_id, exc.code)
    if live_catalog_digest != scope.catalog_digest:
        return _unavailable(consumer_id, "DATA_CONSUMER_CATALOG_STALE")
    store = OperationRecordStore(scope.run_root.parent.parent / "workbench", create=False)
    try:
        records = [record for record in store.list_records() if _record_matches(record, scope)]
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError):
        return _unavailable(consumer_id, "DATA_CONSUMER_OPERATION_RECORDS_UNAVAILABLE")
    if not records:
        return _unavailable(consumer_id, "DATA_CONSUMER_PROJECTION_UNAVAILABLE")
    records.sort(key=lambda record: (record.updated_at, record.record_id))
    identities: set[tuple[str, str, str, str, str]] = set()
    facts: list[dict[str, object]] = []
    try:
        for record in records:
            identity = (
                record.operation_id,
                _opaque_claim_required(record, "data_snapshot_ref"),
                _opaque_claim_required(record, "source_run_id"),
                _opaque_claim_required(record, "source_node_id"),
                _opaque_claim_required(record, "source_artifact_id"),
            )
            if identity in identities:
                return _unavailable(consumer_id, "DATA_CONSUMER_PROJECTION_AMBIGUOUS")
            identities.add(identity)
            output = _validate_record_output(record, catalog_digest=live_catalog_digest)
            fact = _fact_for_record(record, output=output, scope=scope)
            if requested is None or fact["fact_id"] in requested:
                facts.append(fact)
    except DataConsumerHostResolverError as exc:
        return _unavailable(consumer_id, exc.code)
    if requested is not None and not facts:
        return _unavailable(consumer_id, "DATA_CONSUMER_FACT_NOT_FOUND")
    facts.sort(key=lambda fact: str(fact["fact_id"]))
    digest = _projection_digest(facts, scope)
    result: dict[str, object] = {
        "schema_version": 1,
        "payload_schema": _SCHEMA,
        "consumer_id": consumer_id,
        "status": "available",
        "availability": "available",
        "execution_status": "completed",
        "completeness_status": "complete",
        "authority": "server-owned",
        "source": "persisted-data-operation-output",
        "facts": facts,
        "projection_digest": digest,
        "catalog_digest": live_catalog_digest,
        "run_id": scope.run_id,
        "scope_digest": sha256_canonical(
            {"project_ref": scope.project_ref, "session_ref": scope.session_ref, "run_id": scope.run_id}
        ),
        "reason_code": None,
        "receipt": None,
    }
    result["receipt"] = data_consumer_projection_receipt(result)
    return result


def data_consumer_projection_receipt(
    projection: Mapping[str, object],
) -> dict[str, object] | None:
    """Return a transport receipt only for an available bounded projection."""

    if (
        projection.get("status") != "available"
        or not isinstance(projection.get("projection_digest"), str)
        or not isinstance(projection.get("run_id"), str)
        or not isinstance(projection.get("scope_digest"), str)
        or not isinstance(projection.get("catalog_digest"), str)
    ):
        return None
    identity = {
        "consumerId": projection.get("consumer_id"),
        "runId": projection.get("run_id"),
        "scopeDigest": projection.get("scope_digest"),
        "catalogDigest": projection.get("catalog_digest"),
    }
    if any(type(value) is not str or not value for value in identity.values()):
        return None
    return {
        "schemaVersion": 1,
        "kind": _RECEIPT_SCHEMA,
        "projectionDigest": projection["projection_digest"],
        "identity": identity,
    }


def unavailable_data_consumer_projection(
    consumer_id: str,
    reason_code: str,
) -> dict[str, object]:
    """Build the safe Report fallback without accepting a caller packet."""

    if consumer_id not in _CONSUMERS:
        consumer_id = "unknown"
    return _unavailable(consumer_id, reason_code)


__all__ = [
    "DataConsumerProjectionError",
    "DataConsumerRunCapabilityV1",
    "_CAPABILITY_RECORDS",
    "issue_data_consumer_run_capability",
    "read_data_consumer_projection",
    "data_consumer_projection_receipt",
    "unavailable_data_consumer_projection",
]
