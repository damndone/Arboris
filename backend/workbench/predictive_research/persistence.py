"""Admission-gated FD-only persistence for predictive-research packets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
from uuid import uuid4

from .. import __version__
from ..domain import ArtifactRecord
from .schema import (
    CLASSIFICATION_PACKET_SCHEMA,
    PayloadContractError,
    default_v1_prediction_registry,
    validate_classification_packet,
)
from .contracts import ContractError

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


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


@dataclass
class PredictionPersistenceAdmission:
    """A short-lived run-root capability with no raw-path writes."""

    _root_fd: int
    _lock_fd: int = field(default=-1, repr=False)

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
        lock_fd = -1
        try:
            lock_fd = os.open(
                ".workbench-persistence.lock",
                os.O_RDWR | os.O_CREAT | _O_NOFOLLOW | _O_CLOEXEC,
                0o600,
                dir_fd=fd,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (OSError, ValueError) as exc:
            if lock_fd >= 0:
                os.close(lock_fd)
            os.close(fd)
            raise ContractError(
                "PREDICTION_PERSISTENCE_ADMISSION_REQUIRED",
                "run root could not acquire its persistence lock",
            ) from exc
        return cls(fd, lock_fd)

    def __enter__(self) -> "PredictionPersistenceAdmission":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        lock_fd, self._lock_fd = self._lock_fd, -1
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
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

    def _read_json(self, relative_parts: Sequence[str], *, allow_missing: bool = False) -> Any:
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
        except FileNotFoundError as exc:
            if allow_missing:
                return None
            raise ContractError("PREDICTION_PERSISTENCE_INDEX_INVALID", "artifact index is not a valid JSON object") from exc
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ContractError("PREDICTION_PERSISTENCE_INDEX_INVALID", "artifact index is not a valid JSON object") from exc
        finally:
            if fd is not None:
                os.close(fd)
            self._close_children(parent_fd)

    def _file_sha256(self, relative_parts: Sequence[str]) -> str:
        checked = tuple(_safe_part(part) for part in relative_parts)
        if not checked:
            raise ContractError("PREDICTION_PERSISTENCE_PATH_INVALID", "persistence path cannot be empty")
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
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest()
        except FileNotFoundError as exc:
            raise PayloadContractError(
                "ARTIFACT_FILE_MISSING",
                "registered artifact file is missing",
            ) from exc
        except (OSError, ValueError) as exc:
            raise PayloadContractError(
                "ARTIFACT_FILE_INVALID",
                "registered artifact file is not a readable regular file",
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
            self._close_children(parent_fd)

    def read_verified_json(self, relative_parts: Sequence[str], expected_sha256: str) -> Any:
        """Read and hash one artifact through the admitted, pinned directory FD."""

        checked = tuple(_safe_part(part) for part in relative_parts)
        if not checked or not isinstance(expected_sha256, str):
            raise PayloadContractError("ARTIFACT_PAYLOAD_HASH_MISMATCH", "artifact path or digest is invalid")
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
                content = handle.read()
            if _sha256(content) != expected_sha256:
                raise PayloadContractError(
                    "ARTIFACT_PAYLOAD_HASH_MISMATCH",
                    "artifact payload hash does not match its index record",
                )
            try:
                return json.loads(content.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise PayloadContractError(
                    "ARTIFACT_PAYLOAD_VALIDATION_FAILED",
                    "artifact payload is not valid JSON",
                ) from exc
        except PayloadContractError:
            raise
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise PayloadContractError(
                "ARTIFACT_PAYLOAD_HASH_MISMATCH",
                "artifact payload is missing or is not a regular file",
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
            self._close_children(parent_fd)

    def _artifact_records(self, artifact_id: str) -> list[dict[str, Any]]:
        index = self._read_json(("artifacts_index.json",))
        if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
            raise PayloadContractError("ARTIFACT_INDEX_INVALID", "artifacts_index.json has no artifact list")
        return [
            record
            for record in index["artifacts"]
            if isinstance(record, dict) and record.get("artifact_id") == artifact_id
        ]

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
    ) -> None:
        contract = {
            "payload_schema": payload_contract.get("payload_schema"),
            "schema_version": payload_contract.get("schema_version"),
        }
        if contract["payload_schema"] is None or contract["schema_version"] is None:
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_REQUIRED", "payload schema and version are required")
        payload = self._read_json(relative_parts)
        validated = default_v1_prediction_registry().validate(payload)
        actual_sha256 = self._file_sha256(relative_parts)
        if actual_sha256 != sha256:
            raise PayloadContractError(
                "ARTIFACT_DIGEST_MISMATCH",
                f"artifact {artifact_id!r} digest does not match the persisted file",
            )
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
        existing_records = [
            existing
            for existing in index["artifacts"]
            if isinstance(existing, dict) and existing.get("artifact_id") == artifact_id
        ]
        if existing_records:
            if len(existing_records) == 1 and existing_records[0] == record_payload:
                return
            raise PayloadContractError(
                "ARTIFACT_ID_CONFLICT",
                f"artifact_id {artifact_id!r} is already bound to a different artifact",
            )
        index["artifacts"].append(record_payload)
        self._atomic_write(("artifacts_index.json",), _json_bytes(index))


def persist_classification_evidence_packet(
    admission: PredictionPersistenceAdmission,
    *,
    artifact_id: str,
    packet: Mapping[str, Any],
    inputs: list[str],
) -> dict[str, Any]:
    """Persist one validated classification packet through an admitted FD.

    The caller supplies only an artifact identity and typed packet.  The
    function chooses the bounded relative location and registers the exact
    payload contract, so a provider or Agent cannot smuggle a filesystem path
    into the persistence layer.
    """

    if not isinstance(admission, PredictionPersistenceAdmission):
        raise ContractError(
            "PREDICTION_PERSISTENCE_ADMISSION_REQUIRED",
            "classification evidence requires a PredictionPersistenceAdmission",
        )
    if not isinstance(artifact_id, str) or not artifact_id or "/" in artifact_id or "\\" in artifact_id:
        raise ContractError("PREDICTION_PERSISTENCE_PATH_INVALID", "classification artifact_id is unsafe")
    validated = validate_classification_packet(packet)
    relative_parts = ("classification_evidence", f"{artifact_id}.json")
    candidate_bytes = _json_bytes(validated)
    candidate_sha256 = _sha256(candidate_bytes)
    existing_records = admission._artifact_records(artifact_id)
    if existing_records:
        if len(existing_records) != 1:
            raise PayloadContractError("ARTIFACT_ID_CONFLICT", "artifact_id has duplicate index records")
        existing = existing_records[0]
        expected = {
            "artifact_id": artifact_id,
            "path": "/".join(relative_parts),
            "artifact_type": "classification_evidence_packet",
            "sha256": candidate_sha256,
            "inputs": list(inputs),
            "payload_contract": {
                "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
                "schema_version": 1,
            },
        }
        if all(existing.get(key) == value for key, value in expected.items()):
            actual_sha256 = admission._file_sha256(relative_parts)
            if actual_sha256 != existing["sha256"]:
                raise PayloadContractError(
                    "ARTIFACT_DIGEST_MISMATCH",
                    f"artifact {artifact_id!r} index digest does not match the persisted file",
                )
            return {
                "artifact_id": artifact_id,
                "path": "/".join(relative_parts),
                "artifact_type": "classification_evidence_packet",
                "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
                "schema_version": 1,
                "sha256": candidate_sha256,
            }
        raise PayloadContractError(
            "ARTIFACT_ID_CONFLICT",
            f"artifact_id {artifact_id!r} is already bound to a different artifact",
        )
    digest = admission.write_json(relative_parts, validated)
    admission.register_artifact(
        artifact_id=artifact_id,
        relative_parts=relative_parts,
        artifact_type="classification_evidence_packet",
        step="classification",
        inputs=list(inputs),
        sha256=digest,
        payload_contract={
            "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
            "schema_version": 1,
        },
    )
    return {
        "artifact_id": artifact_id,
        "path": "/".join(relative_parts),
        "artifact_type": "classification_evidence_packet",
        "payload_schema": CLASSIFICATION_PACKET_SCHEMA,
        "schema_version": 1,
        "sha256": digest,
    }
