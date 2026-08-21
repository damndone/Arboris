"""Admission-gated FD-only persistence for predictive-research packets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
from uuid import uuid4

from .. import __version__
from ..canonical import sha256_canonical
from ..domain import ArtifactRecord
from .schema import PayloadContractError, default_v1_prediction_registry
from .contracts import ContractError

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_CLASSIFICATION_SERVER_NAMESPACE = "workbench.prediction.classification-artifacts.v1"
_CLASSIFICATION_RECEIPT_SCHEMA = "workbench.prediction.classification-receipt"
_CLASSIFICATION_RECEIPT_PATH = "classification_receipt.json"


def _safe_part(part: str) -> str:
    if not isinstance(part, str) or not part or part in {".", ".."} or "/" in part or "\\" in part:
        raise ContractError("PREDICTION_PERSISTENCE_PATH_INVALID", "persistence path contains an unsafe component")
    return part


def _json_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("PREDICTION_PERSISTENCE_JSON_INVALID", "packet is not JSON serializable") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classification_artifact_id(**identity_parts: str) -> str:
    """Return a content identity bound to every classification artifact input."""

    if not identity_parts or any(not isinstance(key, str) or not key for key in identity_parts):
        raise ContractError("CLASSIFICATION_ARTIFACT_ID_INVALID", "artifact identity parts are required")
    if any(not isinstance(value, str) or not value for value in identity_parts.values()):
        raise ContractError("CLASSIFICATION_ARTIFACT_ID_INVALID", "artifact identity values must be non-empty strings")
    payload = {"schema": "classification-artifact-identity.v1", "parts": dict(sorted(identity_parts.items()))}
    return "sha256:" + _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def classification_server_identity(run_root: Path) -> dict[str, Any]:
    """Derive the server-owned project/run/namespace binding for one run root.

    The binding is intentionally derived from the admitted run location rather
    than accepted from a caller payload.  A copied packet/index therefore keeps
    its source binding and fails when a consumer recomputes the binding for the
    destination project or run.
    """

    resolved_run_root = Path(run_root).resolve()
    if not resolved_run_root.is_absolute() or not resolved_run_root.name:
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_INVALID", "classification run root is invalid")
    project_root = (
        resolved_run_root.parent.parent
        if resolved_run_root.parent.name == "runs"
        else resolved_run_root.parent
    )
    project_id = "project:sha256:" + _sha256(str(project_root).encode("utf-8"))
    run_id = resolved_run_root.name
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_INVALID", "classification run id is invalid")
    base = {
        "schema_version": 1,
        "project_id": project_id,
        "run_id": run_id,
        "namespace": _CLASSIFICATION_SERVER_NAMESPACE,
    }
    digest = "sha256:" + sha256_canonical(base)
    return {**base, "digest": digest}


def _validate_server_identity_shape(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "project_id", "run_id", "namespace", "digest"}:
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_INVALID", "classification server identity shape is invalid")
    base = {
        "schema_version": value.get("schema_version"),
        "project_id": value.get("project_id"),
        "run_id": value.get("run_id"),
        "namespace": value.get("namespace"),
    }
    if value.get("schema_version") != 1 or any(type(base[key]) is not str or not base[key] for key in ("project_id", "run_id", "namespace")):
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_INVALID", "classification server identity fields are invalid")
    expected_digest = "sha256:" + sha256_canonical(base)
    if value.get("digest") != expected_digest:
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_INVALID", "classification server identity digest is invalid")
    return dict(value)


def validate_classification_server_identity_shape(value: Any) -> dict[str, Any]:
    """Validate the self-digest without binding it to a destination run root."""

    return _validate_server_identity_shape(value)


def validate_classification_server_identity(value: Any, run_root: Path) -> dict[str, Any]:
    _validate_server_identity_shape(value)
    expected = classification_server_identity(run_root)
    if value != expected:
        raise ContractError(
            "CLASSIFICATION_SERVER_IDENTITY_MISMATCH",
            "classification artifact is bound to another server project, run or namespace",
        )
    return expected


def _classification_source_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist the typed source contract in the server receipt.

    Consumer-side catalog lookup is not sufficient provenance: the receipt
    must carry the exact evidence/envelope refs that were admitted when this
    packet crossed the server persistence seam.  The estimator does not
    choose these refs; the server-owned provider catalog does.
    """

    from ..evidence.provider_projection_adapters import (
        CLASSIFICATION_EXPOSURE_PATH,
        CLASSIFICATION_PROVIDER_ID,
    )
    from ..providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    provider = next(
        provider
        for provider in catalog.providers
        if provider.provider_id == CLASSIFICATION_PROVIDER_ID
    )
    path = next(
        path
        for path in provider.exposure_paths
        if path.path_id == CLASSIFICATION_EXPOSURE_PATH
    )
    evidence = payload.get("evidence")
    return {
        "payload_contract": {
            "payload_schema": payload.get("payload_schema"),
            "schema_version": payload.get("schema_version"),
        },
        "evidence_schema_ref": evidence.get("payload_schema") if isinstance(evidence, Mapping) else None,
        "evidence_contract_refs": [ref.to_dict() for ref in path.evidence_contract_refs],
        "envelope_contract_refs": [],
    }


def _classification_content_receipt(payload: Mapping[str, Any], *, artifact_sha256: str, server_identity: Mapping[str, Any]) -> dict[str, Any]:
    """Create the server-owned receipt for every classification consumer field.

    The receipt is deliberately derived after the persistence seam has
    injected the destination server identity.  Callers may provide arbitrary
    packet-local digest fields, but those fields are never trusted here.
    """

    evidence = payload.get("evidence")
    evaluation = payload.get("evaluation")
    models = payload.get("models")
    fit = payload.get("fit")
    if isinstance(evidence, Mapping) and isinstance(evaluation, Mapping) and isinstance(models, Mapping) and isinstance(fit, Mapping):
        model_metadata = {
            str(model_id): model.get("metadata")
            for model_id, model in models.items()
            if isinstance(model_id, str) and isinstance(model, Mapping)
        }
        model_warnings = {
            model_id: metadata.get("warnings")
            for model_id, metadata in model_metadata.items()
            if isinstance(metadata, Mapping)
        }
        content_digests = {
            "artifact": artifact_sha256,
            "evidence": sha256_canonical(evidence),
            "evidence.metrics": sha256_canonical(evidence.get("metrics")),
            "evaluation": sha256_canonical(evaluation),
            "evaluation.metrics": sha256_canonical(evaluation.get("metrics")),
            "models": sha256_canonical(models),
            "models.metadata": sha256_canonical(model_metadata),
            "models.warnings": sha256_canonical(model_warnings),
            "fit": sha256_canonical(fit),
            "fold_receipts": sha256_canonical(
                {
                    str(model_id): model.get("fold_receipts")
                    for model_id, model in fit.get("models", {}).items()
                    if isinstance(model_id, str) and isinstance(model, Mapping)
                }
            ),
        }
    else:
        # Keep the low-level persistence helper usable by contract tests and
        # migration tooling.  Such an incomplete packet can be persisted for
        # inspection, but it cannot pass the production consumer validator.
        content_digests = {"artifact": artifact_sha256, "payload": sha256_canonical(payload)}
    base = {
        "payload_schema": _CLASSIFICATION_RECEIPT_SCHEMA,
        "schema_version": 1,
        "receipt_id": f"classification-receipt:{uuid4().hex}",
        "artifact_path": "classification_artifacts.json",
        "artifact_id": payload.get("artifact_id"),
        "artifact_sha256": artifact_sha256,
        "payload_contract": {
            "payload_schema": payload.get("payload_schema"),
            "schema_version": payload.get("schema_version"),
        },
        "source_contract": _classification_source_contract(payload),
        "server_identity": dict(server_identity),
        "content_digests": content_digests,
        "issuer": "workbench.server.classification-persistence",
    }
    return {**base, "receipt_digest": sha256_canonical(base)}


def persist_classification_artifacts(run_root: Path, artifacts: Mapping[str, Any]) -> dict[str, Any]:
    """Persist one classification packet through the existing FD-only admission."""

    if not isinstance(artifacts, Mapping) or not artifacts:
        raise ContractError("CLASSIFICATION_ARTIFACTS_INVALID", "classification artifacts must be a non-empty object")
    payload = dict(artifacts)
    declared_schema = payload.get("payload_schema", "workbench.prediction.classification-artifacts")
    declared_version = payload.get("schema_version", 1)
    if declared_schema != "workbench.prediction.classification-artifacts" or declared_version != 1:
        raise ContractError(
            "CLASSIFICATION_ARTIFACT_CONTRACT_INVALID",
            "classification artifacts must use payload schema version 1",
        )
    payload["payload_schema"] = declared_schema
    payload["schema_version"] = declared_version
    server_identity = classification_server_identity(Path(run_root))
    if "server_identity" in payload and payload["server_identity"] != server_identity:
        raise ContractError(
            "CLASSIFICATION_SERVER_IDENTITY_MISMATCH",
            "classification artifact server identity is not server-owned",
        )
    payload["server_identity"] = server_identity
    content = _json_bytes(payload)
    with PredictionPersistenceAdmission.admit(Path(run_root)) as admission:
        digest = admission.write_json(("classification_artifacts.json",), payload)
        receipt = _classification_content_receipt(
            payload,
            artifact_sha256=digest,
            server_identity=server_identity,
        )
        receipt_sha256 = admission.write_json((_CLASSIFICATION_RECEIPT_PATH,), receipt)
    return {
        "status": "persisted",
        "path": "classification_artifacts.json",
        "sha256": digest,
        "content_size": len(content),
        "server_identity": server_identity,
        "receipt_path": _CLASSIFICATION_RECEIPT_PATH,
        "receipt_sha256": receipt_sha256,
        "receipt": receipt,
    }


@dataclass
class PredictionPersistenceAdmission:
    """A short-lived run-root capability with no raw-path writes."""

    _root_fd: int

    @classmethod
    def admit(cls, run_root: Path) -> "PredictionPersistenceAdmission":
        if os.name != "posix" or not _O_DIRECTORY or not _O_NOFOLLOW or os.open not in os.supports_dir_fd:
            raise ContractError(
                "PREDICTION_PERSISTENCE_ADMISSION_REQUIRED",
                "predictive evidence persistence requires POSIX directory-FD support",
            )
        try:
            fd = os.open(os.fspath(run_root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC)
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError
        except (OSError, ValueError) as exc:
            raise ContractError(
                "PREDICTION_PERSISTENCE_ADMISSION_REQUIRED",
                "run root could not be admitted as a pinned directory",
            ) from exc
        return cls(fd)

    def __enter__(self) -> "PredictionPersistenceAdmission":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        fd, self._root_fd = self._root_fd, -1
        if fd >= 0:
            os.close(fd)

    def _require_open(self) -> int:
        if self._root_fd < 0:
            raise ContractError("PREDICTION_PERSISTENCE_ADMISSION_REQUIRED", "persistence admission is closed")
        return self._root_fd

    def _directory(self, parts: Sequence[str], *, create: bool) -> int:
        current = self._require_open()
        opened: list[int] = []
        try:
            for raw_part in parts:
                part = _safe_part(raw_part)
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                        dir_fd=current,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o700, dir_fd=current)
                    child = os.open(
                        part,
                        os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                        dir_fd=current,
                    )
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    os.close(child)
                    raise OSError
                opened.append(child)
                current = child
            for fd in opened[:-1]:
                os.close(fd)
            return opened[-1] if opened else self._root_fd
        except (OSError, ValueError) as exc:
            for fd in reversed(opened):
                os.close(fd)
            raise ContractError(
                "PREDICTION_PERSISTENCE_PATH_INVALID",
                "predictive evidence path is not a regular directory tree",
            ) from exc

    def _close_children(self, directory_fd: int) -> None:
        if directory_fd != self._root_fd:
            os.close(directory_fd)

    def _atomic_write(self, parts: Sequence[str], content: bytes) -> str:
        if not parts:
            raise ContractError("PREDICTION_PERSISTENCE_PATH_INVALID", "persistence path cannot be empty")
        checked = tuple(_safe_part(part) for part in parts)
        parent_fd = self._directory(checked[:-1], create=True)
        temporary = f".{checked[-1]}.{uuid4().hex}.tmp"
        temp_fd: int | None = None
        try:
            temp_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
            offset = 0
            while offset < len(content):
                offset += os.write(temp_fd, content[offset:])
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(temporary, checked[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.fsync(parent_fd)
            return _sha256(content)
        except (OSError, ValueError) as exc:
            raise ContractError(
                "PREDICTION_PERSISTENCE_WRITE_FAILED",
                "predictive evidence packet could not be persisted",
            ) from exc
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            self._close_children(parent_fd)

    def write_json(self, relative_parts: Sequence[str], payload: Any) -> str:
        return self._atomic_write(relative_parts, _json_bytes(payload))

    def _read_json(self, relative_parts: Sequence[str]) -> Any:
        checked = tuple(_safe_part(part) for part in relative_parts)
        parent_fd = self._directory(checked[:-1], create=False)
        fd: int | None = None
        try:
            fd = os.open(
                checked[-1],
                os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC,
                dir_fd=parent_fd,
            )
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = None
                return json.loads(handle.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ContractError("PREDICTION_PERSISTENCE_INDEX_INVALID", "artifact index is not a valid JSON object") from exc
        finally:
            if fd is not None:
                os.close(fd)
            self._close_children(parent_fd)

    def register_artifact(
        self,
        *,
        artifact_id: str,
        relative_parts: Sequence[str],
        artifact_type: str,
        step: str,
        inputs: list[str],
        sha256: str,
        payload_contract: Mapping[str, Any],
        server_identity: Mapping[str, Any] | None = None,
        receipt_path: str | None = None,
        receipt_sha256: str | None = None,
    ) -> None:
        contract = {
            "payload_schema": payload_contract.get("payload_schema"),
            "schema_version": payload_contract.get("schema_version"),
        }
        if contract["payload_schema"] is None or contract["schema_version"] is None:
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_REQUIRED", "payload schema and version are required")
        payload = self._read_json(relative_parts)
        validated = default_v1_prediction_registry().validate(payload)
        if (
            validated.get("payload_schema") != contract["payload_schema"]
            or validated.get("schema_version") != contract["schema_version"]
        ):
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_MISMATCH", "record contract does not match packet")
        index = self._read_json(("artifacts_index.json",))
        if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
            raise PayloadContractError("ARTIFACT_INDEX_INVALID", "artifacts_index.json has no artifact list")
        record = ArtifactRecord(
            artifact_id=artifact_id,
            path="/".join(_safe_part(part) for part in relative_parts),
            artifact_type=artifact_type,
            step=step,
            sha256=sha256,
            inputs=inputs,
            code_version=__version__,
            payload_contract=contract,
        )
        record_payload = record.to_dict()
        if server_identity is not None:
            _validate_server_identity_shape(server_identity)
            record_payload["server_identity"] = dict(server_identity)
            index["classification_server_identity"] = dict(server_identity)
        if receipt_path is not None or receipt_sha256 is not None:
            if not isinstance(receipt_path, str) or not isinstance(receipt_sha256, str):
                raise PayloadContractError("ARTIFACT_RECEIPT_INVALID", "receipt path and digest must be supplied together")
            record_payload["receipt_path"] = _safe_part(receipt_path)
            record_payload["receipt_sha256"] = receipt_sha256
        index["artifacts"].append(record_payload)
        self._atomic_write(("artifacts_index.json",), _json_bytes(index))
