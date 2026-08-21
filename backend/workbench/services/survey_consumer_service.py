"""Central, capability-only Survey consumer service."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Any
import weakref

from ..artifacts import read_json, sha256_file
from ..canonical import sha256_canonical
from ..evidence.survey_projection_adapter import (
    _SERVER_SOURCE_ISSUER,
    _authorize_survey_source_receipt,
    _issue_survey_source_snapshot,
    project_survey_source_snapshot,
)
from ..predictive_research.contracts import ContractError
from .server_run_artifacts import (
    ServerOwnedArtifactManifestError,
    read_server_owned_run_artifacts,
)


_REPORT_SCHEMA = "workbench.survey.report-evidence.v1"
_RECEIPT_SCHEMA = "evidence.survey.server-receipt.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _SurveyRunCapability:
    """Opaque handle for one server-resolved run directory."""

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("survey run capabilities are server-issued")


@dataclass(frozen=True, slots=True)
class _CapabilityRecord:
    run_root: Path
    server_identity: tuple[tuple[str, str], ...]


_CAPABILITY_RECORDS: weakref.WeakKeyDictionary[
    _SurveyRunCapability, _CapabilityRecord
] = weakref.WeakKeyDictionary()
_SERVER_RUN_CAPABILITY_ISSUER = object()


def _mint_survey_run_capability(
    run_root: Path,
    *,
    _issuer: object | None = None,
) -> _SurveyRunCapability:
    """Mint only after a server boundary has resolved an existing run directory."""

    if _issuer is not _SERVER_RUN_CAPABILITY_ISSUER:
        raise ContractError(
            "SURVEY_RUN_SERVER_AUTHORITY_REQUIRED",
            "survey run capability requires the server issuer",
        )
    if not isinstance(run_root, Path):
        raise ContractError(
            "SURVEY_RUN_CAPABILITY_MINT_INVALID",
            "survey capability must be minted from a resolved run root",
        )
    resolved = run_root.resolve(strict=False)
    if not resolved.is_absolute() or not resolved.is_dir() or resolved.parent.name != "runs":
        raise ContractError(
            "SURVEY_RUN_CAPABILITY_MINT_INVALID",
            "survey capability requires an existing resolved server run",
        )
    try:
        read_server_owned_run_artifacts(
            resolved.parent.parent,
            resolved.name,
            required=True,
        )
    except (ServerOwnedArtifactManifestError, OSError, ValueError) as exc:
        raise ContractError(
            "SURVEY_RUN_CAPABILITY_MINT_INVALID",
            "survey capability requires a verified server artifact manifest",
        ) from exc
    capability = object.__new__(_SurveyRunCapability)
    object.__setattr__(capability, "_token", secrets.token_urlsafe(32))
    _CAPABILITY_RECORDS[capability] = _CapabilityRecord(
        run_root=resolved,
        server_identity=(("run_id", resolved.name),),
    )
    return capability


def issue_survey_run_capability(project_root: Path, run_id: str) -> object:
    """Issue a run capability only for a persisted, server-owned run identity."""

    if (
        not isinstance(project_root, Path)
        or type(run_id) is not str
        or not run_id
        or run_id != run_id.strip()
        or "/" in run_id
        or "\\" in run_id
        or ".." in run_id
    ):
        raise ContractError(
            "SURVEY_RUN_CAPABILITY_MINT_INVALID",
            "survey capability requires an opaque project/run identity",
        )
    return _mint_survey_run_capability(
        project_root / "runs" / run_id,
        _issuer=_SERVER_RUN_CAPABILITY_ISSUER,
    )


def _capability_record(capability: object) -> _CapabilityRecord:
    if type(capability) is not _SurveyRunCapability:
        raise ContractError(
            "SURVEY_RUN_CAPABILITY_REQUIRED",
            "survey evidence requires a server-issued run capability",
        )
    record = _CAPABILITY_RECORDS.get(capability)
    if record is None:
        raise ContractError(
            "SURVEY_RUN_CAPABILITY_REQUIRED",
            "survey run capability is unknown or expired",
        )
    return record


def _payload_digest(payload: dict[str, Any]) -> str | None:
    binding = payload.get("result_binding")
    if not isinstance(binding, dict):
        return None
    unsigned = dict(payload)
    unsigned_binding = dict(binding)
    unsigned_binding.pop("payload_sha256", None)
    unsigned["result_binding"] = unsigned_binding
    try:
        return hashlib.sha256(
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return None


def _valid_opaque_identity(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and "\x00" not in value
        and "/" not in value
        and "\\" not in value
        and ".." not in value
    )


def _valid_survey_result_binding(
    binding: object,
    *,
    payload: dict[str, Any],
    project_root: Path,
    run_id: str,
    artifact_id: str,
) -> bool:
    """Validate the producer-owned binding, not merely a self-consistent hash."""

    if not isinstance(binding, dict):
        return False
    expected_fields = {
        "strategy",
        "project_root",
        "run_id",
        "model_id",
        "source_artifact_ids",
        "coefficient_source_ids",
        "payload_sha256",
    }
    if set(binding) != expected_fields or binding.get("strategy") != "coefficient_table_v1":
        return False
    if (
        binding.get("project_root") != str(project_root.resolve())
        or binding.get("run_id") != run_id
        or binding.get("model_id") != artifact_id
    ):
        return False
    source_artifact_ids = binding.get("source_artifact_ids")
    if (
        not isinstance(source_artifact_ids, list)
        or not source_artifact_ids
        or any(not _valid_opaque_identity(value) for value in source_artifact_ids)
        or len(set(source_artifact_ids)) != len(source_artifact_ids)
    ):
        return False
    coefficients = payload.get("coefficients")
    source_ids = binding.get("coefficient_source_ids")
    if not isinstance(coefficients, dict) or not coefficients or not isinstance(source_ids, dict):
        return False
    expected_source_ids = {
        term: f"model_results.{artifact_id}.coefficients.{term}"
        for term in coefficients
        if type(term) is str
    }
    if source_ids != expected_source_ids:
        return False
    payload_sha256 = binding.get("payload_sha256")
    return (
        type(payload_sha256) is str
        and _SHA256_RE.fullmatch(payload_sha256) is not None
        and payload_sha256 == _payload_digest(payload)
    )


def _read_validated_survey_artifact(record: _CapabilityRecord) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read exactly one indexed Survey model result and validate its receipt binding."""

    try:
        artifacts = read_server_owned_run_artifacts(
            record.run_root.parent.parent, record.run_root.name, required=True
        )
    except (ServerOwnedArtifactManifestError, OSError, ValueError) as exc:
        raise ContractError(
            "SURVEY_PERSISTED_ARTIFACT_UNAVAILABLE",
            "survey server-owned artifact index is unavailable",
        ) from exc
    candidates = [
        item
        for item in artifacts
        if item.get("artifact_type") == "model_result"
        and isinstance(item.get("artifact_id"), str)
        and isinstance(item.get("path"), str)
    ]
    valid: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in candidates:
        artifact_id = item["artifact_id"]
        path_text = item["path"]
        if path_text != f"model_results/{artifact_id}.json":
            continue
        path = record.run_root / path_text
        digest = item.get("sha256")
        if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
            continue
        try:
            if not path.is_file() or sha256_file(path) != digest:
                continue
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("model_id") != artifact_id:
            continue
        binding = payload.get("result_binding")
        if not _valid_survey_result_binding(
            binding,
            payload=payload,
            project_root=record.run_root.parent.parent,
            run_id=record.run_root.name,
            artifact_id=artifact_id,
        ):
            continue
        if not isinstance(payload.get("survey_design"), dict):
            continue
        valid.append((dict(item), payload))
    if len(valid) != 1:
        raise ContractError(
            "SURVEY_PERSISTED_ARTIFACT_REQUIRED",
            "exactly one validated persisted Survey model artifact is required",
        )
    return valid[0]


def read_survey_consumer_projection(
    capability: object,
    consumer_id: str,
) -> dict[str, Any]:
    """Read one Survey projection through a capability and a source snapshot."""

    record = _capability_record(capability)
    artifact_record, artifact = _read_validated_survey_artifact(record)
    binding = artifact["result_binding"]
    metadata = {
        "artifact_id": artifact_record["artifact_id"],
        "artifact_sha256": artifact_record["sha256"],
        "receipt_digest": binding["payload_sha256"],
        "server_identity": {
            **dict(record.server_identity),
            "model_id": artifact["model_id"],
            "model_type": artifact.get("model_type"),
        },
    }
    authorization = _authorize_survey_source_receipt(
        metadata,
        _issuer=_SERVER_SOURCE_ISSUER,
    )
    source = _issue_survey_source_snapshot(
        artifact,
        authorization=authorization,
        metadata=metadata,
        _issuer=_SERVER_SOURCE_ISSUER,
    )
    return project_survey_source_snapshot(source, consumer_id=consumer_id)


def survey_consumer_projection_receipt(
    projection: dict[str, Any],
) -> dict[str, Any] | None:
    """Create a bounded receipt for a validated or degraded Report source."""

    if projection.get("status") not in {"validated", "degraded"}:
        return None
    source = projection.get("source")
    if not isinstance(source, dict):
        return None
    server_identity = source.get("server_identity")
    if not isinstance(server_identity, dict):
        return None
    identity = {
        "consumerId": projection.get("consumer"),
        "runId": server_identity.get("run_id"),
        "artifactId": source.get("artifact_id"),
        "artifactSha256": source.get("artifact_sha256"),
        "sourceReceiptDigest": source.get("receipt_digest"),
        "catalogDigest": projection.get("catalog", {}).get("digest")
        if isinstance(projection.get("catalog"), dict)
        else None,
    }
    if (
        any(type(value) is not str or not value for value in identity.values())
        or _SHA256_RE.fullmatch(identity["artifactSha256"]) is None
        or _SHA256_RE.fullmatch(identity["sourceReceiptDigest"]) is None
        or _SHA256_RE.fullmatch(identity["catalogDigest"]) is None
    ):
        return None
    source_projection = dict(projection)
    source_projection.pop("consumer", None)
    projection_digest = sha256_canonical(source_projection)
    return {
        "schemaVersion": 1,
        "kind": _RECEIPT_SCHEMA,
        "projectionDigest": projection_digest,
        "identity": identity,
    }


def unavailable_survey_report_evidence(reason: str) -> dict[str, Any]:
    """Return a safe Report fallback without a caller-supplied payload."""

    return {
        "payload_schema": _REPORT_SCHEMA,
        "schema_version": 1,
        "provider_id": "workbench.survey",
        "consumer": "report",
        "status": "unavailable",
        "authority": "server-owned",
        "survey_design": None,
        "source": None,
        "reason": reason,
        "receipt": None,
    }


def read_survey_report_evidence(capability: object) -> dict[str, Any]:
    """Build the typed Report surface from the central Survey reader."""

    try:
        projection = read_survey_consumer_projection(capability, "report")
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return unavailable_survey_report_evidence(
            getattr(exc, "code", "SURVEY_EVIDENCE_UNAVAILABLE")
        )
    response = {
        **projection,
        "payload_schema": _REPORT_SCHEMA,
        "authority": "server-owned",
    }
    response["receipt"] = survey_consumer_projection_receipt(response)
    return response


__all__ = [
    "issue_survey_run_capability",
    "read_survey_consumer_projection",
    "read_survey_report_evidence",
    "survey_consumer_projection_receipt",
    "unavailable_survey_report_evidence",
]
