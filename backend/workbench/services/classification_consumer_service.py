"""Server-owned classification evidence consumption."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets
from typing import Any
import weakref

from ..canonical import sha256_canonical
from ..predictive_research import consumer_projection as _consumer_projection
from ..predictive_research.contracts import ContractError
from ..predictive_research.persistence import classification_server_identity
from ..predictive_research.schema import PayloadContractError
from ..evidence.provider_projection_adapters import (
    ClassificationProjectionAdapterV1,
    default_provider_projection_registry,
    source_snapshot_metadata,
)
from ..evidence.consumer_adapters import EvidenceProjectionError


_CLASSIFICATION_CONSUMERS = frozenset({"agent", "notebook", "report"})
_UNAVAILABLE_SCHEMA = "workbench.prediction.classification-evidence.unavailable"
_ROUTE_SCHEMA = "workbench.prediction.classification-artifacts-wrapper"
_RECEIPT_SCHEMA = "workbench.prediction.classification-consumer-receipt"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _ClassificationRunCapability:
    """Opaque server-issued handle for one already-resolved run directory."""

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("classification run capabilities are server-issued")


@dataclass(frozen=True, slots=True)
class _CapabilityRecord:
    run_root: Path
    server_identity: tuple[tuple[str, Any], ...]


_CAPABILITY_RECORDS: weakref.WeakKeyDictionary[
    _ClassificationRunCapability, _CapabilityRecord
] = weakref.WeakKeyDictionary()


def _mint_capability(
    run_root: Path,
    *,
    require_server_runs_layout: bool,
) -> _ClassificationRunCapability:
    if not isinstance(run_root, Path):
        raise ContractError(
            "CLASSIFICATION_RUN_CAPABILITY_MINT_INVALID",
            "classification capability must be minted from a resolved run root",
        )
    resolved_run_root = run_root.resolve(strict=False)
    if (
        not resolved_run_root.is_absolute()
        or not resolved_run_root.is_dir()
        or (
            require_server_runs_layout
            and resolved_run_root.parent.name != "runs"
        )
    ):
        raise ContractError(
            "CLASSIFICATION_RUN_CAPABILITY_MINT_INVALID",
            "classification capability requires an existing resolved server run",
        )
    token = secrets.token_urlsafe(32)
    capability = object.__new__(_ClassificationRunCapability)
    object.__setattr__(capability, "_token", token)
    identity = classification_server_identity(resolved_run_root)
    _CAPABILITY_RECORDS[capability] = _CapabilityRecord(
        run_root=resolved_run_root,
        server_identity=tuple(sorted(identity.items())),
    )
    return capability


def _mint_classification_run_capability(run_root: Path) -> _ClassificationRunCapability:
    """Mint only from an existing run root resolved by a server boundary."""

    return _mint_capability(run_root, require_server_runs_layout=True)


def _capability_record(capability: object) -> _CapabilityRecord:
    if type(capability) is not _ClassificationRunCapability:
        raise ContractError(
            "CLASSIFICATION_RUN_CAPABILITY_REQUIRED",
            "classification evidence requires a server-issued run capability",
        )
    record = _CAPABILITY_RECORDS.get(capability)
    if record is None:
        raise ContractError(
            "CLASSIFICATION_RUN_CAPABILITY_REQUIRED",
            "classification run capability is unknown or expired",
        )
    return record


def _unavailable_projection(
    adapter: ClassificationProjectionAdapterV1,
    consumer_id: str,
    code: str,
) -> dict[str, Any]:
    """Keep unavailable results bound to the same catalog identity as success."""

    return {
        **adapter.unavailable(consumer_id, code),
        "payload_schema": _UNAVAILABLE_SCHEMA,
        "code": code,
    }


def unavailable_classification_report_evidence(code: str) -> dict[str, Any]:
    """Return the only safe Report fallback: a catalog-bound unavailable packet."""

    adapter = ClassificationProjectionAdapterV1(default_provider_projection_registry())
    return {
        **_unavailable_projection(adapter, "report", code),
        "reason": code,
    }


def read_classification_consumer_projection(
    capability: object,
    consumer_id: str,
) -> dict[str, Any]:
    """Read one persisted classification projection through one capability."""

    record = _capability_record(capability)
    if consumer_id not in _CLASSIFICATION_CONSUMERS:
        raise ContractError(
            "CLASSIFICATION_CONSUMER_UNSUPPORTED",
            f"unsupported classification consumer {consumer_id!r}",
        )
    adapter = ClassificationProjectionAdapterV1(default_provider_projection_registry())
    try:
        # The wrapper is the sole pathname read.  It validates the index,
        # indexed artifact, receipt, source contract, server identity, and C0
        # in one snapshot before issuing an opaque source handle.
        source_snapshot = _consumer_projection.read_classification_source_snapshot_from_run_root(
            record.run_root
        )
    except PayloadContractError as exc:
        if exc.code in {
            "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE",
            "CLASSIFICATION_ARTIFACTS_INDEX_INVALID",
        }:
            # Preserve the package-level unavailable wire contract.  The
            # scoped adapter was still resolved above, so an unavailable
            # index cannot bypass the server-owned catalog boundary.
            return _unavailable_projection(adapter, consumer_id, exc.code)
        raise

    metadata = source_snapshot_metadata(source_snapshot)
    expected_identity = dict(record.server_identity)
    if metadata.get("server_identity") != expected_identity:
        raise ContractError(
            "CLASSIFICATION_SERVER_IDENTITY_MISMATCH",
            "classification wrapper identity does not match the server-issued run capability",
        )
    try:
        projection = adapter.project_artifact(
            source_snapshot,
            consumer_id=consumer_id,
        )
    except EvidenceProjectionError as exc:
        # A server-owned artifact can still be inadmissible for this consumer
        # (for example because its declared sensitivity or serialized size is
        # outside the catalog policy).  Preserve the bound unavailable shape;
        # never let a route manufacture an identity-less fallback.
        return _unavailable_projection(adapter, consumer_id, exc.code)
    return {
        **projection,
        "source_artifact_id": metadata["artifact_id"],
        "source_artifact_sha256": metadata["artifact_sha256"],
        "source_receipt_digest": metadata["receipt_digest"],
        "server_identity": expected_identity,
    }


def read_classification_report_evidence(capability: object) -> dict[str, Any]:
    """Build the typed Report surface from the central capability reader."""

    try:
        projection = read_classification_consumer_projection(capability, "report")
    except (PayloadContractError, ContractError, EvidenceProjectionError) as exc:
        code = getattr(exc, "code", "CLASSIFICATION_EVIDENCE_UNAVAILABLE")
        return unavailable_classification_report_evidence(code)
    if projection.get("payload_schema") == _UNAVAILABLE_SCHEMA:
        return {
            **projection,
            "reason": projection.get("code"),
        }
    if projection.get("status") not in {"validated", "degraded"}:
        return {**projection, "reason": projection.get("code")}

    source = {
        "artifact_id": projection["source_artifact_id"],
        "artifact_sha256": projection["source_artifact_sha256"],
        "receipt_digest": projection["source_receipt_digest"],
        "server_identity": dict(projection["server_identity"]),
    }
    receipt_base = {
        "payload_schema": _RECEIPT_SCHEMA,
        "schema_version": 1,
        "status": projection["status"],
        "source": source,
    }
    receipt = {**receipt_base, "receipt_digest": sha256_canonical(receipt_base)}
    response = {
        "payload_schema": _ROUTE_SCHEMA,
        "schema_version": 1,
        "status": projection["status"],
        "consumer": "report",
        "artifact_id": source["artifact_id"],
        "artifact_sha256": source["artifact_sha256"],
        "receipt_digest": receipt["receipt_digest"],
        "server_identity": dict(source["server_identity"]),
        "projection": projection,
        "source": source,
        "receipt": receipt,
    }
    if projection["status"] == "degraded":
        response["reason"] = list(projection.get("blocked_reasons", []))
    return response


__all__ = [
    "read_classification_consumer_projection",
    "read_classification_report_evidence",
]
