"""Opaque, server-owned Survey source snapshots for bounded consumers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
import secrets
from typing import Any
import weakref

from ..predictive_research.contracts import ContractError
from ..providers.catalog import load_builtin_catalog
from ..survey.projection import project_survey_design


SURVEY_PROVIDER_ID = "workbench.survey"
SURVEY_EXPOSURE_PATH = "workbench.survey.central_source"
SURVEY_CONSUMERS = frozenset({"agent", "notebook", "report"})
_SOURCE_SCHEMA = "workbench.survey.central-source"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SERVER_SOURCE_ISSUER = object()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class SurveySourceSnapshotV1:
    """A source handle that only the verified Survey reader can issue."""

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("survey source snapshots are server-issued")


@dataclass(frozen=True, slots=True, weakref_slot=True)
class SurveySourceReceiptAuthorizationV1:
    """An opaque proof of a validated result-binding receipt."""

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("survey source receipt authorizations are server-issued")


@dataclass(frozen=True, slots=True)
class _SourceSnapshotRecord:
    artifact: Mapping[str, Any]
    metadata: Mapping[str, Any]


_SOURCE_RECEIPTS: weakref.WeakKeyDictionary[
    SurveySourceReceiptAuthorizationV1, Mapping[str, Any]
] = weakref.WeakKeyDictionary()
_SOURCE_SNAPSHOTS: weakref.WeakKeyDictionary[
    SurveySourceSnapshotV1, _SourceSnapshotRecord
] = weakref.WeakKeyDictionary()


def _required_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "artifact_id",
        "artifact_sha256",
        "receipt_digest",
        "server_identity",
    }:
        raise ContractError(
            "SURVEY_SOURCE_RECEIPT_REQUIRED",
            "survey source receipt metadata is incomplete",
        )
    artifact_id = value.get("artifact_id")
    artifact_sha256 = value.get("artifact_sha256")
    receipt_digest = value.get("receipt_digest")
    server_identity = value.get("server_identity")
    if (
        type(artifact_id) is not str
        or not artifact_id
        or type(artifact_sha256) is not str
        or _SHA256_RE.fullmatch(artifact_sha256) is None
        or type(receipt_digest) is not str
        or _SHA256_RE.fullmatch(receipt_digest) is None
        or not isinstance(server_identity, Mapping)
    ):
        raise ContractError(
            "SURVEY_SOURCE_RECEIPT_REQUIRED",
            "survey source receipt metadata is invalid",
        )
    return {
        "artifact_id": artifact_id,
        "artifact_sha256": artifact_sha256,
        "receipt_digest": receipt_digest,
        "server_identity": dict(server_identity),
    }


def _authorize_survey_source_receipt(
    metadata: object,
    *,
    _issuer: object | None = None,
) -> SurveySourceReceiptAuthorizationV1:
    """Authorize only exact metadata emitted by the persisted-artifact reader."""

    if _issuer is not _SERVER_SOURCE_ISSUER:
        raise ContractError(
            "SURVEY_SOURCE_SERVER_AUTHORITY_REQUIRED",
            "survey source receipt requires the server issuer",
        )
    verified = _required_metadata(metadata)
    authorization = object.__new__(SurveySourceReceiptAuthorizationV1)
    object.__setattr__(authorization, "_token", secrets.token_urlsafe(32))
    _SOURCE_RECEIPTS[authorization] = verified
    return authorization


def _issue_survey_source_snapshot(
    artifact: object,
    *,
    authorization: object,
    metadata: object,
    _issuer: object | None = None,
) -> SurveySourceSnapshotV1:
    """Issue one opaque snapshot only after receipt and artifact verification."""

    if _issuer is not _SERVER_SOURCE_ISSUER:
        raise ContractError(
            "SURVEY_SOURCE_SERVER_AUTHORITY_REQUIRED",
            "survey source snapshot requires the server issuer",
        )
    verified_metadata = _required_metadata(metadata)
    if (
        not isinstance(artifact, Mapping)
        or type(authorization) is not SurveySourceReceiptAuthorizationV1
        or _SOURCE_RECEIPTS.get(authorization) != verified_metadata
    ):
        raise ContractError(
            "SURVEY_SOURCE_RECEIPT_REQUIRED",
            "survey source snapshot requires an authorized persisted receipt",
        )
    snapshot = object.__new__(SurveySourceSnapshotV1)
    object.__setattr__(snapshot, "_token", secrets.token_urlsafe(32))
    _SOURCE_SNAPSHOTS[snapshot] = _SourceSnapshotRecord(
        artifact=dict(artifact), metadata=verified_metadata
    )
    return snapshot


def _source_record(source: object) -> _SourceSnapshotRecord:
    if type(source) is not SurveySourceSnapshotV1:
        raise ContractError(
            "SURVEY_SOURCE_SNAPSHOT_REQUIRED",
            "survey projection requires a server-issued source snapshot",
        )
    record = _SOURCE_SNAPSHOTS.get(source)
    if record is None:
        raise ContractError(
            "SURVEY_SOURCE_SNAPSHOT_REQUIRED",
            "survey source snapshot is unknown or expired",
        )
    return record


def survey_source_snapshot_metadata(source: object) -> dict[str, Any]:
    """Return the immutable identity selected by the server reader."""

    return dict(_source_record(source).metadata)


def _require_catalog_contribution(consumer_id: str) -> tuple[object, object, object]:
    if consumer_id not in SURVEY_CONSUMERS:
        raise ContractError(
            "SURVEY_CONSUMER_UNSUPPORTED",
            f"unsupported survey consumer {consumer_id!r}",
        )
    catalog = load_builtin_catalog()
    provider = next(
        (
            item
            for item in catalog.providers
            if item.provider_id == SURVEY_PROVIDER_ID
        ),
        None,
    )
    path = next(
        (item for item in provider.exposure_paths if item.path_id == SURVEY_EXPOSURE_PATH),
        None,
    ) if provider is not None else None
    declaration = next(
        (
            item
            for item in provider.projection_declarations
            if item.path_id == SURVEY_EXPOSURE_PATH
            and item.consumer_id == consumer_id
            and item.coverage_status == "required"
        ),
        None,
    ) if provider is not None else None
    if provider is None or path is None or declaration is None:
        raise ContractError(
            "SURVEY_PROVIDER_CONTRIBUTION_REQUIRED",
            "survey consumer has no server-owned catalog contribution",
        )
    if (
        path.projection_refs.get(consumer_id) != declaration.projection_ref
        or declaration.projection_ref not in provider.projection_refs
        or declaration.policy_ref not in provider.policy_refs
        or declaration.renderer_ref not in provider.renderer_refs
        or any(ref not in path.evidence_contract_refs for ref in declaration.evidence_contract_refs)
        or not declaration.evidence_contract_refs
    ):
        raise ContractError(
            "SURVEY_PROVIDER_CONTRIBUTION_INVALID",
            "survey catalog projection, evidence, policy, or renderer refs are not bound",
        )
    return catalog, path, declaration


def _status_and_reason(artifact: Mapping[str, Any], design: Mapping[str, Any]) -> tuple[str, str | None]:
    """Carry persisted status forward; warnings only make a valid read degraded."""

    status = artifact.get("survey_evidence_status")
    reason = artifact.get("survey_unavailable_reason")
    if status not in {"validated", "degraded", "unavailable"}:
        status = "unavailable"
        reason = "SURVEY_EVIDENCE_STATUS_INVALID"
    elif design.get("projection_status") == "unavailable":
        status = "unavailable"
        reason = design.get("unavailable_reason")
    elif status == "validated" and (design.get("warnings") or design.get("replicates_failed")):
        status = "degraded"
        reason = "SURVEY_REPLICATE_FAILURES" if design.get("replicates_failed") else "SURVEY_WARNINGS"
    if status == "unavailable" and type(reason) is not str:
        reason = "SURVEY_EVIDENCE_UNAVAILABLE"
    if status == "degraded" and type(reason) is not str:
        reason = "SURVEY_EVIDENCE_DEGRADED"
    return status, reason if type(reason) is str else None


def project_survey_source_snapshot(
    source: object,
    *,
    consumer_id: str,
) -> dict[str, Any]:
    """Project one validated snapshot without accepting raw packets or registries."""

    catalog, path, declaration = _require_catalog_contribution(consumer_id)
    record = _source_record(source)
    artifact = record.artifact
    persisted_model_type = artifact.get("model_type")
    model_family = None
    if type(persisted_model_type) is str:
        model_family = {
            "ols": "ols",
            "ols_robust": "ols",
            "logit": "logit",
        }.get(persisted_model_type)
    design = project_survey_design(
        artifact.get("survey_design"),
        unavailable_reason="SURVEY_DESIGN_METADATA_INVALID",
        run_id=record.metadata["server_identity"].get("run_id"),
        source_id=record.metadata["artifact_id"],
    )
    if design is None:
        design = {
            "projection_status": "unavailable",
            "unavailable_reason": "SURVEY_DESIGN_METADATA_UNAVAILABLE",
        }
    status, reason = _status_and_reason(artifact, design)
    result = {
        "payload_schema": _SOURCE_SCHEMA,
        "schema_version": 1,
        "provider_id": SURVEY_PROVIDER_ID,
        "consumer": consumer_id,
        "status": status,
        "survey_design": design,
        "source": dict(record.metadata),
        "catalog": {
            "digest": catalog.catalog_digest,
            "provider_id": SURVEY_PROVIDER_ID,
            "path_id": path.path_id,
            "projection_ref": declaration.projection_ref.to_dict(),
            "evidence_contract_refs": [
                ref.to_dict() for ref in declaration.evidence_contract_refs
            ],
            "policy_ref": declaration.policy_ref.to_dict(),
            "renderer_ref": declaration.renderer_ref.to_dict(),
        },
    }
    if model_family is None:
        result["status"] = "unavailable"
        result["reason"] = "SURVEY_MODEL_FAMILY_UNSUPPORTED"
        result["source_status"] = status
        if reason is not None:
            result["source_reason"] = reason
        return result
    result["model_family"] = model_family
    if reason is not None:
        result["reason"] = reason
    return result


__all__ = [
    "SurveySourceSnapshotV1",
    "_authorize_survey_source_receipt",
    "_issue_survey_source_snapshot",
    "project_survey_source_snapshot",
    "survey_source_snapshot_metadata",
]
