"""Admission-gated, FD-safe persistence for immutable evidence packets."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import RLock
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Evidence Core requires POSIX admission
    fcntl = None  # type: ignore[assignment]

from workbench.canonical import CanonicalJSONError, canonical_json_v1
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.common.foundation_status import TransactionStatusV1
from workbench.contracts.evidence.envelope import NotApplicableV1
from workbench.contracts.evidence.persistence import (
    EvidenceCommitBindingV1,
    EvidenceCommitRequestV1,
)

from .authority import (
    EVIDENCE_HOST_AUTHORITY_REQUIRED,
    EvidenceHostAuthorityError,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from .contracts import (
    ArtifactAdmissionV1,
    EVIDENCE_PERSISTENCE_CONTRACT_DIGEST,
    EvidenceBindingV1,
    EvidenceCoreContractError,
    _digest as _evidence_digest,
    _opaque_ref,
    _text,
)
from .registry import (
    EvidenceRegistryError,
    EvidenceRegistryV1,
    validate_registry_persistence_receipt,
)


EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED = "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"
EVIDENCE_PERSISTENCE_PATH_INVALID = "EVIDENCE_PERSISTENCE_PATH_INVALID"
EVIDENCE_PERSISTENCE_PACKET_CONFLICT = "EVIDENCE_PERSISTENCE_PACKET_CONFLICT"
EVIDENCE_PERSISTENCE_PACKET_TAMPERED = "EVIDENCE_PERSISTENCE_PACKET_TAMPERED"
EVIDENCE_PERSISTENCE_INDEX_TAMPERED = "EVIDENCE_PERSISTENCE_INDEX_TAMPERED"
EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN = "EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN"
EVIDENCE_PERSISTENCE_WRITE_FAILED = "EVIDENCE_PERSISTENCE_WRITE_FAILED"
EVIDENCE_PERSISTENCE_JSON_INVALID = "EVIDENCE_PERSISTENCE_JSON_INVALID"

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_PACKET_CONTRACT = "evidence-packet"
_PACKET_VERSION = "1.0"
_INDEX_CONTRACT = "evidence-index"
_INDEX_PRODUCER_VERSION = "1.0"
_PACKET_PRODUCER_VERSION = "1.0"
_INDEX_ROW_FIELDS = frozenset(
    {
        "artifact_id",
        "artifact_type",
        "scope_ref",
        "content_hash",
        "source_ref",
        "validator_ref",
        "execution_ref",
        "contract_digest",
        "packet_ref",
        "commit_ref",
    }
)


class EvidencePersistenceError(ValueError):
    """A persistence failure that never silently repairs or overwrites evidence."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _error(code: str, message: str) -> EvidencePersistenceError:
    return EvidencePersistenceError(code, message)


def _safe_part(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise _error(EVIDENCE_PERSISTENCE_PATH_INVALID, "persistence component is unsafe")
    return value


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return canonical_json_v1(value).encode("utf-8")
    except (CanonicalJSONError, ValueError, OverflowError, RecursionError) as exc:
        raise _error(EVIDENCE_PERSISTENCE_JSON_INVALID, "packet is not canonical JSON") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _error(EVIDENCE_PERSISTENCE_JSON_INVALID, f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _parse_canonical(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except EvidencePersistenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _error(EVIDENCE_PERSISTENCE_JSON_INVALID, "stored evidence JSON is invalid") from exc
    if type(value) is not dict or _canonical_bytes(value) != raw:
        raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored evidence JSON is not canonical")
    return value


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class EvidencePersistenceAdmissionV1:
    """A short-lived pinned directory capability; no raw path is retained."""

    __slots__ = (
        "_root_fd",
        "_root_dev",
        "_root_ino",
        "_owner_pid",
        "_scope_ref",
        "_authority_handle",
        "_authority_request",
        "_authority_proof",
    )

    def __init__(
        self,
        root_fd: int,
        *,
        authority_handle: object | None = None,
        scope_ref: str | None = None,
    ) -> None:
        if authority_handle is None:
            raise _error(EVIDENCE_HOST_AUTHORITY_REQUIRED, "persistence admission requires a host-issued authority handle")
        if type(root_fd) is not int or root_fd < 0:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "persistence root descriptor is invalid")
        self._root_fd = root_fd
        try:
            stat_result = os.fstat(root_fd)
        except OSError as exc:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "persistence root descriptor is unavailable") from exc
        if not stat.S_ISDIR(stat_result.st_mode):
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "persistence root is not a directory")
        self._root_dev = int(stat_result.st_dev)
        self._root_ino = int(stat_result.st_ino)
        self._owner_pid = os.getpid()
        if scope_ref is None:
            scope_ref = getattr(authority_handle, "scope_ref", None)
        if type(scope_ref) is not str or not scope_ref:
            raise _error(EVIDENCE_HOST_AUTHORITY_REQUIRED, "persistence admission scope is not host-bound")
        self._scope_ref = scope_ref
        self._authority_handle = authority_handle
        try:
            self._authority_request = build_authority_request(
                authority_handle,
                purpose="evidence.persistence",
                scope_ref=scope_ref,
                subject_id=id(self),
                payload_digest=self._payload_digest(),
                root_fd=root_fd,
            )
            self._authority_proof = issue_host_proof(authority_handle, self._authority_request)
            self._validate_authority()
        except EvidenceHostAuthorityError as exc:
            raise _error(exc.code, str(exc)) from exc

    def _payload_digest(self) -> str:
        return hashlib.sha256(f"{self._scope_ref}:{self._root_dev}:{self._root_ino}".encode("utf-8")).hexdigest()

    @classmethod
    def admit(
        cls,
        root: Path | str,
        *,
        authority_handle: object | None = None,
        scope_ref: str | None = None,
    ) -> "EvidencePersistenceAdmissionV1":
        if authority_handle is None:
            raise _error(EVIDENCE_HOST_AUTHORITY_REQUIRED, "persistence admission requires a host-issued authority handle")
        if (
            os.name != "posix"
            or fcntl is None
            or not _O_NOFOLLOW
            or not _O_DIRECTORY
            or os.open not in os.supports_dir_fd
        ):
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "FD-safe evidence persistence is unavailable")
        try:
            fd = os.open(os.fspath(root), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC)
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                os.close(fd)
                raise OSError("root is not a directory")
        except (OSError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "persistence root could not be admitted") from exc
        try:
            return cls(fd, authority_handle=authority_handle, scope_ref=scope_ref)
        except Exception:
            os.close(fd)
            raise

    def __enter__(self) -> "EvidencePersistenceAdmissionV1":
        self._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            fd = self._root_fd
        except AttributeError:
            return
        self._root_fd = -1
        if fd >= 0:
            os.close(fd)

    def _validate_authority(self) -> None:
        try:
            root_fd = self._root_fd
            root_dev = self._root_dev
            root_ino = self._root_ino
            owner_pid = self._owner_pid
            scope_ref = self._scope_ref
            handle = self._authority_handle
            request = self._authority_request
            proof = self._authority_proof
            if (
                type(root_fd) is not int
                or type(root_dev) is not int
                or type(root_ino) is not int
                or type(owner_pid) is not int
                or type(scope_ref) is not str
            ):
                raise ValueError("persistence admission proof fields are malformed")
            if owner_pid != os.getpid() or root_fd < 0 or request.subject_id != id(self):
                raise ValueError("persistence admission belongs to another owner")
            stat_result = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(stat_result.st_mode)
                or int(stat_result.st_dev) != root_dev
                or int(stat_result.st_ino) != root_ino
            ):
                raise ValueError("persistence admission root identity changed")
            if (
                request.scope_ref != scope_ref
                or request.root_fd != root_fd
                or request.root_device != root_dev
                or request.root_inode != root_ino
                or request.payload_digest != self._payload_digest()
            ):
                raise ValueError("persistence admission binding is invalid")
            validate_host_proof(handle, request, proof)
        except EvidencePersistenceError:
            raise
        except EvidenceHostAuthorityError as exc:
            raise _error(EVIDENCE_HOST_AUTHORITY_REQUIRED, str(exc)) from exc
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise _error(
                EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED,
                "persistence admission is not a server-issued authority",
            ) from exc

    def __reduce__(self):
        raise TypeError("persistence admissions are host-bound capabilities")

    def __copy__(self):
        raise TypeError("persistence admissions are host-bound capabilities")

    def __deepcopy__(self, memo):
        raise TypeError("persistence admissions are host-bound capabilities")

    def _require_open(self) -> int:
        self._validate_authority()
        if self._root_fd < 0:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "persistence admission is closed")
        return self._root_fd

    def _directory(self, parts: Sequence[str], *, create: bool) -> int:
        current = self._require_open()
        opened: list[int] = []
        try:
            for raw in parts:
                part = _safe_part(raw)
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
                    raise OSError("not a directory")
                opened.append(child)
                current = child
            for fd in opened[:-1]:
                os.close(fd)
            return opened[-1] if opened else self._root_fd
        except (OSError, ValueError) as exc:
            for fd in reversed(opened):
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise _error(EVIDENCE_PERSISTENCE_PATH_INVALID, "persistence path is not a safe directory tree") from exc

    def _close_directory(self, fd: int) -> None:
        if fd != self._root_fd:
            os.close(fd)

    def _open_index_lock(self) -> int:
        root_fd = self._require_open()
        try:
            # Lock the admitted directory inode itself.  A pathname lock can
            # be unlinked and replaced between two admitted writers, creating
            # independent lock domains; a duplicated root FD stays anchored to
            # the admitted directory inode for the whole operation.
            return os.dup(root_fd)
        except (OSError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_WRITE_FAILED, "evidence index lock could not be opened safely") from exc


class EvidencePacketStoreV1:
    """Immutable packet/index store constructed only from an admission token."""

    __slots__ = ("_admission", "_lock")

    def __init__(self, admission: EvidencePersistenceAdmissionV1) -> None:
        if type(admission) is not EvidencePersistenceAdmissionV1:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "writer requires a persistence admission token")
        admission._require_open()
        self._admission = admission
        self._lock = RLock()

    @classmethod
    def admit(
        cls,
        root: Path | str,
        *,
        authority_handle: object | None = None,
        scope_ref: str | None = None,
    ) -> "EvidencePacketStoreV1":
        return cls(
            EvidencePersistenceAdmissionV1.admit(
                root,
                authority_handle=authority_handle,
                scope_ref=scope_ref,
            )
        )

    def __enter__(self) -> "EvidencePacketStoreV1":
        self._admission._require_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._admission.close()

    @property
    def admission(self) -> EvidencePersistenceAdmissionV1:
        return self._admission

    @staticmethod
    def _commit_id(record: ArtifactAdmissionV1) -> str:
        return f"commit:evidence:{record.content_hash}"

    @staticmethod
    def _projector_ref() -> ContractRefV1:
        return ContractRefV1(
            kind="projector",
            logical_id="evidence:core:persistence",
            semantic_version="1.0",
            contract_digest=EVIDENCE_PERSISTENCE_CONTRACT_DIGEST,
        )

    @classmethod
    def _binding_for(cls, record: ArtifactAdmissionV1) -> EvidenceCommitBindingV1:
        commit_id = cls._commit_id(record)
        request = EvidenceCommitRequestV1(
            artifact_admission_ref=record.artifact_id,
            projector_ref=cls._projector_ref(),
            envelope_digest=record.envelope_digest,
            idempotency_key=commit_id,
            supersedes_ref=NotApplicableV1("initial immutable evidence commit"),
            invalidation_refs=(),
        )
        return EvidenceCommitBindingV1(
            commit_id=commit_id,
            request_digest=request.request_digest,
            artifact_admission_ref=request.artifact_admission_ref,
            projector_ref=request.projector_ref,
            envelope_digest=request.envelope_digest,
            idempotency_key=request.idempotency_key,
            transaction_status=TransactionStatusV1.COMMITTED,
            supersedes_ref=request.supersedes_ref,
            invalidation_refs=(),
            failure_receipt=NotApplicableV1("evidence commit succeeded"),
        )

    @contextmanager
    def _index_lock(self):
        if fcntl is None:  # pragma: no cover - guarded by admission on POSIX
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, "cross-process evidence locking is unavailable")
        lock_fd = self._admission._open_index_lock()
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except OSError as exc:
                raise _error(EVIDENCE_PERSISTENCE_WRITE_FAILED, "evidence index lock could not be acquired") from exc
            yield
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _write_new(self, parts: Sequence[str], raw: bytes) -> bool:
        checked = tuple(_safe_part(part) for part in parts)
        if not checked:
            raise _error(EVIDENCE_PERSISTENCE_PATH_INVALID, "destination is empty")
        parent = self._admission._directory(checked[:-1], create=True)
        temporary = f".{checked[-1]}.{uuid4().hex}.tmp"
        temp_fd: int | None = None
        created = False
        try:
            temp_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            offset = 0
            while offset < len(raw):
                offset += os.write(temp_fd, raw[offset:])
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            try:
                os.link(temporary, checked[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            except FileExistsError:
                current = self._read_bytes(checked)
                if current != raw:
                    raise _error(EVIDENCE_PERSISTENCE_PACKET_CONFLICT, "immutable evidence destination already contains different bytes")
            else:
                created = True
                os.fsync(parent)
        except EvidencePersistenceError:
            raise
        except (OSError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_WRITE_FAILED, "evidence file could not be written safely") from exc
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            self._admission._close_directory(parent)
        return created

    def _remove_new(self, parts: Sequence[str]) -> None:
        checked = tuple(_safe_part(part) for part in parts)
        if not checked:
            raise _error(EVIDENCE_PERSISTENCE_PATH_INVALID, "destination is empty")
        parent = self._admission._directory(checked[:-1], create=False)
        try:
            try:
                os.unlink(checked[-1], dir_fd=parent)
            except FileNotFoundError:
                pass
            os.fsync(parent)
        except (OSError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_WRITE_FAILED, "evidence transaction rollback failed") from exc
        finally:
            self._admission._close_directory(parent)

    def _replace_index(self, raw: bytes) -> None:
        checked = ("index.json",)
        parent = self._admission._directory((), create=True)
        temporary = f".index.{uuid4().hex}.tmp"
        temp_fd: int | None = None
        try:
            temp_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            offset = 0
            while offset < len(raw):
                offset += os.write(temp_fd, raw[offset:])
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(temporary, checked[0], src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        except (OSError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_WRITE_FAILED, "evidence index could not be replaced safely") from exc
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            self._admission._close_directory(parent)

    def _read_bytes(self, parts: Sequence[str]) -> bytes:
        checked = tuple(_safe_part(part) for part in parts)
        if not checked:
            raise _error(EVIDENCE_PERSISTENCE_PATH_INVALID, "read destination is empty")
        parent = self._admission._directory(checked[:-1], create=False)
        fd: int | None = None
        try:
            fd = os.open(checked[-1], os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC, dir_fd=parent)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("not a regular file")
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = None
                return handle.read()
        except FileNotFoundError as exc:
            raise _error(EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN, "stored evidence file is missing") from exc
        except (OSError, UnicodeError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored evidence file cannot be read safely") from exc
        finally:
            if fd is not None:
                os.close(fd)
            self._admission._close_directory(parent)

    def _read_json(self, parts: Sequence[str]) -> dict[str, object]:
        return _parse_canonical(self._read_bytes(parts))

    def _empty_index(self) -> dict[str, object]:
        return {
            "contract": _INDEX_CONTRACT,
            "contract_version": _PACKET_VERSION,
            "producer_version": _INDEX_PRODUCER_VERSION,
            "artifacts": [],
        }

    def _load_index(self) -> dict[str, object]:
        try:
            value = self._read_json(("index.json",))
        except EvidencePersistenceError as exc:
            if exc.code == EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN:
                return self._empty_index()
            raise
        if (
            set(value) != {"contract", "contract_version", "producer_version", "artifacts"}
            or value["contract"] != _INDEX_CONTRACT
            or value["contract_version"] != _PACKET_VERSION
            or value["producer_version"] != _INDEX_PRODUCER_VERSION
            or type(value["artifacts"]) is not list
        ):
            raise _error(EVIDENCE_PERSISTENCE_INDEX_TAMPERED, "evidence index fields are invalid")
        rows = value["artifacts"]
        artifact_ids: list[str] = []
        content_hashes: set[str] = set()
        for row in rows:
            self._validate_index_row(row, artifact_ids, content_hashes)
        if artifact_ids != sorted(artifact_ids):
            raise _error(EVIDENCE_PERSISTENCE_INDEX_TAMPERED, "evidence index rows are not deterministically ordered")
        return value

    @staticmethod
    def _validate_index_row(
        row: object,
        artifact_ids: list[str],
        content_hashes: set[str],
    ) -> None:
        if type(row) is not dict or set(row) != _INDEX_ROW_FIELDS:
            raise _error(EVIDENCE_PERSISTENCE_INDEX_TAMPERED, "evidence index row fields are invalid")
        try:
            artifact_id = _opaque_ref(row["artifact_id"], "artifact_id")
            _text(row["artifact_type"], "artifact_type")
            _opaque_ref(row["scope_ref"], "scope_ref")
            content_hash = _evidence_digest(row["content_hash"], "content_hash")
            validator_ref = row["validator_ref"]
            if type(validator_ref) is dict:
                validator_ref = ContractRefV1.from_dict(validator_ref)
            EvidenceBindingV1(
                source_ref=row["source_ref"],  # type: ignore[arg-type]
                validator_ref=validator_ref,  # type: ignore[arg-type]
                execution_ref=row["execution_ref"],  # type: ignore[arg-type]
                contract_digest=row["contract_digest"],  # type: ignore[arg-type]
            )
            packet_ref = row["packet_ref"]
            commit_ref = row["commit_ref"]
            expected_packet = f"packets/{content_hash}.json"
            expected_commit = f"commits/{content_hash}.json"
            if packet_ref != expected_packet or commit_ref != expected_commit:
                raise ValueError("index refs are not content-addressed")
        except (ContractError, EvidenceCoreContractError, TypeError, KeyError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_INDEX_TAMPERED, "evidence index row is corrupt") from exc
        if artifact_id in artifact_ids or content_hash in content_hashes:
            raise _error(EVIDENCE_PERSISTENCE_INDEX_TAMPERED, "evidence index contains a duplicate identity")
        artifact_ids.append(artifact_id)
        content_hashes.add(content_hash)

    def _packet_payload(self, record: ArtifactAdmissionV1, binding: EvidenceCommitBindingV1) -> dict[str, object]:
        return {
            "contract": _PACKET_CONTRACT,
            "contract_version": _PACKET_VERSION,
            "producer_version": _PACKET_PRODUCER_VERSION,
            "payload": {
                "artifact": record.to_dict(),
                "binding": binding.to_dict(),
            },
        }

    @staticmethod
    def _index_row(record: ArtifactAdmissionV1, binding: EvidenceCommitBindingV1) -> dict[str, object]:
        digest = record.content_hash
        return {
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "scope_ref": record.scope_ref,
            "content_hash": digest,
            "source_ref": record.source_ref,
            "validator_ref": record.validator_ref.to_dict()
            if type(record.validator_ref) is ContractRefV1
            else record.validator_ref,
            "execution_ref": record.execution_ref,
            "contract_digest": record.contract_digest,
            "packet_ref": f"packets/{digest}.json",
            "commit_ref": f"commits/{digest}.json",
        }

    def commit(
        self,
        record: object,
        *,
        receipt: object | None = None,
    ) -> EvidenceCommitBindingV1:
        try:
            validate_registry_persistence_receipt(record, receipt)
        except EvidenceRegistryError as exc:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, str(exc)) from exc
        with self._lock:
            with self._index_lock():
                self._admission._require_open()
                assert type(record) is ArtifactAdmissionV1
                binding = self._binding_for(record)
                index = self._load_index()
                artifacts = list(index["artifacts"])  # type: ignore[arg-type]
                row = self._index_row(record, binding)
                matching = [
                    item
                    for item in artifacts
                    if type(item) is dict and item.get("content_hash") == record.content_hash
                ]
                if matching and matching[0] != row:
                    raise _error(
                        EVIDENCE_PERSISTENCE_PACKET_CONFLICT,
                        "content-addressed evidence is already bound to a different artifact identity",
                    )

                packet = self._packet_payload(record, binding)
                packet_raw = _canonical_bytes(packet)
                packet_name = f"{record.content_hash}.json"
                commit_name = f"{record.content_hash}.json"
                created_files: list[tuple[str, str]] = []
                try:
                    if self._write_new(("packets", packet_name), packet_raw):
                        created_files.append(("packets", packet_name))
                    if self._write_new(("commits", commit_name), _canonical_bytes(binding.to_dict())):
                        created_files.append(("commits", commit_name))
                    if not matching:
                        artifacts.append(row)
                        artifacts.sort(key=lambda item: str(item["artifact_id"]))
                        index["artifacts"] = artifacts
                        self._replace_index(_canonical_bytes(index))
                    return binding
                except Exception as exc:
                    rollback_error: EvidencePersistenceError | None = None
                    for parts in reversed(created_files):
                        try:
                            self._remove_new(parts)
                        except EvidencePersistenceError as cleanup_exc:
                            rollback_error = cleanup_exc
                            break
                    if rollback_error is not None:
                        raise _error(
                            EVIDENCE_PERSISTENCE_WRITE_FAILED,
                            "evidence transaction rollback failed; commit remains quarantined",
                        ) from rollback_error
                    raise exc

    def _index_exists(self) -> bool:
        try:
            self._read_bytes(("index.json",))
        except EvidencePersistenceError as exc:
            if exc.code == EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN:
                return False
            raise
        return True

    def _require_load_authority(
        self,
        packet_artifact: ArtifactAdmissionV1,
        *,
        registry: object,
        receipt: object,
    ) -> ArtifactAdmissionV1:
        if type(registry) is not EvidenceRegistryV1 or receipt is None:
            raise _error(
                EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED,
                "evidence load requires the owning registry and its receipt",
            )
        try:
            trusted_record = registry.resolve(
                packet_artifact.artifact_id,
                scope_ref=packet_artifact.scope_ref,
            )
            validate_registry_persistence_receipt(
                trusted_record,
                receipt,
                registry=registry,
            )
        except EvidenceRegistryError as exc:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, str(exc)) from exc
        if trusted_record.to_dict() != packet_artifact.to_dict():
            raise _error(
                EVIDENCE_PERSISTENCE_PACKET_TAMPERED,
                "stored packet is not the exact artifact admitted by the supplied registry",
            )
        return trusted_record

    def load(
        self,
        commit_id: str,
        *,
        registry: object | None = None,
        receipt: object | None = None,
    ) -> EvidenceCommitBindingV1:
        if type(registry) is not EvidenceRegistryV1 or receipt is None:
            raise _error(
                EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED,
                "evidence load requires the owning registry and its receipt",
            )
        try:
            registry.validate_persistence_capability(receipt)
        except EvidenceRegistryError as exc:
            raise _error(EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED, str(exc)) from exc
        if type(commit_id) is not str or not commit_id.startswith("commit:evidence:"):
            raise _error(EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN, "commit identity is unknown")
        digest = commit_id.removeprefix("commit:evidence:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise _error(EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN, "commit identity is unknown")
        raw = self._read_bytes(("commits", f"{digest}.json"))
        try:
            value = _parse_canonical(raw)
            binding = EvidenceCommitBindingV1.from_dict(value)
        except EvidencePersistenceError:
            raise
        except (ContractError, TypeError, KeyError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored commit binding is corrupt") from exc
        if binding.commit_id != commit_id:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored commit identity does not match its filename")
        packet_raw = self._read_bytes(("packets", f"{digest}.json"))
        packet = _parse_canonical(packet_raw)
        if (
            set(packet) != {"contract", "contract_version", "producer_version", "payload"}
            or packet["contract"] != _PACKET_CONTRACT
            or packet["contract_version"] != _PACKET_VERSION
            or packet["producer_version"] != _PACKET_PRODUCER_VERSION
        ):
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored packet envelope is invalid")
        payload = packet["payload"]
        if type(payload) is not dict or set(payload) != {"artifact", "binding"}:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored packet payload is invalid")
        try:
            stored_binding = EvidenceCommitBindingV1.from_dict(payload["binding"])  # type: ignore[arg-type]
            packet_artifact = ArtifactAdmissionV1.from_dict(payload["artifact"])  # type: ignore[arg-type]
        except (ContractError, EvidenceCoreContractError, TypeError, KeyError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored packet evidence is corrupt") from exc
        if stored_binding != binding:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "packet and commit binding disagree")
        if packet_artifact.artifact_id != binding.artifact_admission_ref:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "packet artifact identity does not match the commit")
        if packet_artifact.content_hash != digest:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "packet artifact hash does not match the commit filename")
        if packet_artifact.envelope_digest != binding.envelope_digest:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "packet envelope digest does not match the commit")
        if binding != self._binding_for(packet_artifact):
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "commit binding is not derived from the admitted artifact")
        self._require_load_authority(packet_artifact, registry=registry, receipt=receipt)
        index = self._load_index()
        rows = index["artifacts"]
        matching = [row for row in rows if type(row) is dict and row.get("commit_ref") == f"commits/{digest}.json"]
        expected_row = self._index_row(packet_artifact, binding)
        if len(matching) != 1 or matching[0] != expected_row:
            raise _error(EVIDENCE_PERSISTENCE_INDEX_TAMPERED, "evidence index is not bound to the commit")
        return binding

    def load_packet(
        self,
        commit_id: str,
        *,
        registry: object | None = None,
        receipt: object | None = None,
    ) -> ArtifactAdmissionV1:
        binding = self.load(commit_id, registry=registry, receipt=receipt)
        digest = binding.commit_id.removeprefix("commit:evidence:")
        value = _parse_canonical(self._read_bytes(("packets", f"{digest}.json")))
        try:
            return ArtifactAdmissionV1.from_dict(value["payload"]["artifact"])  # type: ignore[index,arg-type]
        except (ContractError, EvidenceCoreContractError, TypeError, KeyError, ValueError) as exc:
            raise _error(EVIDENCE_PERSISTENCE_PACKET_TAMPERED, "stored packet artifact is corrupt") from exc


EvidencePersistenceV1 = EvidencePacketStoreV1
AdmissionGatedEvidenceWriterV1 = EvidencePacketStoreV1


__all__ = [
    "AdmissionGatedEvidenceWriterV1",
    "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
    "EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN",
    "EVIDENCE_PERSISTENCE_INDEX_TAMPERED",
    "EVIDENCE_PERSISTENCE_JSON_INVALID",
    "EVIDENCE_PERSISTENCE_PACKET_CONFLICT",
    "EVIDENCE_PERSISTENCE_PACKET_TAMPERED",
    "EVIDENCE_PERSISTENCE_PATH_INVALID",
    "EVIDENCE_PERSISTENCE_WRITE_FAILED",
    "EvidencePacketStoreV1",
    "EvidencePersistenceAdmissionV1",
    "EvidencePersistenceError",
    "EvidencePersistenceV1",
]
