"""Host-owned construction of per-run Report evidence capabilities.

The workflow may produce a typed envelope, but it is not allowed to turn that
envelope into a citable Report source by itself.  This factory is the narrow
deployment seam that binds the envelope to the already-admitted C0 registry,
packet store, scope, and run identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from threading import RLock
from typing import Sequence
from uuid import uuid4

from .. import __version__
from ..artifacts import sha256_file
from ..canonical import canonical_json_v1, sha256_canonical
from ..contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    EvaluationDesignV1,
    ExecutionStatusV1,
    InferenceBasisV1,
    NumericalMethodV1,
    ValidationLevelV1,
    ValidationRequirementStatusV1,
    validation_level_rank,
)
from ..contracts.evidence.envelope import EvidenceEnvelopeV1
from ..evidence.consumer_adapters import (
    CONSUMER_PROJECTION_EVIDENCE_CONTRACT_DIGEST,
)
from ..evidence.persistence import (
    EvidencePacketStoreV1,
    EvidencePersistenceAdmissionV1,
    EvidencePersistenceError,
)
from ..evidence.registry import EvidenceRegistryError, EvidenceRegistryV1
from .results_service import (
    EvidenceProjectionError,
    ServerOwnedReportEvidencePersistenceV1,
)


def _required_text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty exact string")
    return value


def _required_digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_production_evidence_root(
    evidence_store: EvidencePacketStoreV1,
    canonical_project_root: Path,
) -> None:
    """Bind the C0 packet store to this project's bootstrapped evidence root.

    Unit-level deployment fixtures may use an isolated packet directory while
    they do not have a Workbench host tree yet.  Once the canonical project
    contains the production ``workbench`` directory, however, the factory must
    refuse a packet store admitted from another directory, even if the caller
    supplies the same authority object and scope string.
    """

    workbench_root = canonical_project_root / "workbench"
    expected_root = workbench_root / "evidence"
    if not workbench_root.exists() and not expected_root.exists():
        return
    if workbench_root.is_symlink() or not expected_root.is_dir() or expected_root.is_symlink():
        raise ValueError("Report owner factory requires the canonical workbench/evidence directory")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    fd = -1
    try:
        fd = os.open(expected_root, flags)
        expected_stat = os.fstat(fd)
        admission = evidence_store.admission
        if (
            int(expected_stat.st_dev) != int(getattr(admission, "_root_dev", -1))
            or int(expected_stat.st_ino) != int(getattr(admission, "_root_ino", -1))
        ):
            raise ValueError(
                "Report owner factory evidence store is not bound to the canonical project evidence root"
            )
    except OSError as exc:
        raise ValueError("Report owner factory canonical evidence root could not be admitted") from exc
    finally:
        if fd >= 0:
            os.close(fd)


class HostBoundProjectFileStoreV1:
    """FD-only access to the canonical project artifacts owned by this host.

    Report evidence is committed to the C0 packet store, but the run-local
    ``report_evidence.json`` and ``artifacts_index.json`` are still durable
    inputs to the Report view.  They must therefore use the same admission
    boundary: callers may describe a logical relative file, never choose a
    writer path or follow a symlink at execution time.
    """

    __slots__ = ("_admission", "_root", "_transaction_lock")

    def __init__(
        self,
        root: Path | str,
        *,
        authority_handle: object,
        scope_ref: str,
    ) -> None:
        canonical_root = Path(root).expanduser().resolve(strict=False)
        if not canonical_root.is_dir():
            raise ValueError("Report project persistence root must be a directory")
        self._admission = EvidencePersistenceAdmissionV1.admit(
            canonical_root,
            authority_handle=authority_handle,
            scope_ref=scope_ref,
        )
        self._root = canonical_root
        self._transaction_lock = RLock()

    @classmethod
    def from_host(
        cls,
        root: Path | str,
        *,
        authority_handle: object,
        scope_ref: str,
    ) -> "HostBoundProjectFileStoreV1":
        return cls(
            root,
            authority_handle=authority_handle,
            scope_ref=scope_ref,
        )

    def _parts(self, parts: Sequence[str], *, create: bool = False) -> tuple[str, ...]:
        checked = tuple(str(part) for part in parts)
        if not checked or any(
            not part
            or part in {".", ".."}
            or "/" in part
            or "\\" in part
            or "\x00" in part
            for part in checked
        ):
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_PATH_INVALID",
                "Report project file path is not a safe relative path",
            )
        # _directory performs the authoritative O_NOFOLLOW walk.  We only
        # use it here as a validation/open probe; the returned descriptor is
        # closed immediately.
        parent = self._admission._directory(checked[:-1], create=create)
        self._admission._close_directory(parent)
        return checked

    def _read_bytes(self, parts: Sequence[str], *, max_bytes: int | None = None) -> bytes:
        checked = self._parts(parts)
        parent = self._admission._directory(checked[:-1], create=False)
        fd = -1
        try:
            fd = os.open(
                checked[-1],
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise EvidencePersistenceError(
                    "EVIDENCE_PERSISTENCE_PATH_INVALID",
                    "Report project file is not a regular file",
                )
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = -1
                if max_bytes is None:
                    return handle.read()
                if before.st_size > max_bytes:
                    raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Model source exceeds byte budget")
                raw = handle.read(before.st_size)
                after = os.fstat(handle.fileno())
                metadata = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
                if metadata(before) != metadata(after) or len(raw) != before.st_size:
                    raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_UNSTABLE", "Model source changed during read")
                return raw
        except FileNotFoundError as exc:
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_COMMIT_UNKNOWN",
                "Report project file is missing",
            ) from exc
        except EvidencePersistenceError:
            raise
        except OSError as exc:
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_PACKET_TAMPERED",
                "Report project file could not be read safely",
            ) from exc
        finally:
            if fd >= 0:
                os.close(fd)
            self._admission._close_directory(parent)

    @staticmethod
    def _parse_json(raw: bytes) -> dict[str, object]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_JSON_INVALID",
                "Report project JSON is invalid",
            ) from exc
        if type(value) is not dict:
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_JSON_INVALID",
                "Report project JSON must be an object",
            )
        return value

    def read_json(self, parts: Sequence[str]) -> dict[str, object]:
        return self._parse_json(self._read_bytes(parts))

    def sha256(self, parts: Sequence[str]) -> str:
        return hashlib.sha256(self._read_bytes(parts)).hexdigest()

    def _parts_for_owner(
        self,
        owner: ServerOwnedReportEvidencePersistenceV1,
        *,
        run_root: Path,
        path: Path,
        filename: str,
    ) -> tuple[str, ...]:
        if getattr(owner, "_project_file_store", None) is not self:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "Report evidence owner is not bound to this host project-file capability",
            )
        canonical_run_root = self._root / "runs" / owner.run_id
        try:
            if Path(run_root).expanduser().resolve(strict=False) != canonical_run_root.resolve(strict=False):
                raise EvidenceProjectionError(
                    "EVIDENCE_SCOPE_ROOT_MISMATCH",
                    "Report evidence index root is outside the owner scope",
                )
            if Path(path).expanduser().resolve(strict=False) != (canonical_run_root / filename).resolve(strict=False):
                raise EvidenceProjectionError(
                    "EVIDENCE_ARTIFACT_PATH_MISMATCH",
                    "Report evidence index must point to the canonical evidence file",
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_SCOPE_ROOT_MISMATCH",
                "Report evidence path could not be canonically bound",
            ) from exc
        return ("runs", owner.run_id, filename)

    def _lock(self):
        import fcntl

        self._transaction_lock.acquire()
        try:
            lock_fd = os.dup(self._admission._require_open())
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return fcntl, lock_fd
        except BaseException:
            self._transaction_lock.release()
            raise

    def _unlock(self, fcntl: Any, lock_fd: int) -> None:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
            self._transaction_lock.release()

    def write_json_once(self, parts: Sequence[str], value: Mapping[str, object]) -> None:
        checked = self._parts(parts, create=True)
        raw = canonical_json_v1(dict(value)).encode("utf-8")
        fcntl, lock_fd = self._lock()
        parent = -1
        temp_fd = -1
        temporary = f".{checked[-1]}.{uuid4().hex}.tmp"
        try:
            parent = self._admission._directory(checked[:-1], create=True)
            temp_fd = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent,
            )
            offset = 0
            while offset < len(raw):
                offset += os.write(temp_fd, raw[offset:])
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = -1
            try:
                os.link(
                    temporary,
                    checked[-1],
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileExistsError:
                if self._read_bytes(checked) != raw:
                    raise EvidencePersistenceError(
                        "EVIDENCE_PERSISTENCE_PACKET_CONFLICT",
                        "Report project file already contains different bytes",
                    )
            else:
                os.fsync(parent)
        except EvidencePersistenceError:
            raise
        except OSError as exc:
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_WRITE_FAILED",
                "Report project JSON could not be written safely",
            ) from exc
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            if parent >= 0:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                self._admission._close_directory(parent)
            self._unlock(fcntl, lock_fd)

    def _replace_json_locked(self, checked: tuple[str, ...], raw: bytes) -> None:
        """Replace one admitted file while the root transaction lock is held."""

        parent = -1
        temp_fd = -1
        temporary = f".{checked[-1]}.{uuid4().hex}.tmp"
        try:
            parent = self._admission._directory(checked[:-1], create=True)
            try:
                existing_fd = os.open(
                    checked[-1],
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                pass
            else:
                try:
                    if not stat.S_ISREG(os.fstat(existing_fd).st_mode):
                        raise EvidencePersistenceError(
                            "EVIDENCE_PERSISTENCE_PATH_INVALID",
                            "Report project JSON target is not a regular file",
                        )
                finally:
                    os.close(existing_fd)
            temp_fd = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent,
            )
            offset = 0
            while offset < len(raw):
                offset += os.write(temp_fd, raw[offset:])
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = -1
            os.replace(temporary, checked[-1], src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        except EvidencePersistenceError:
            raise
        except OSError as exc:
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_WRITE_FAILED",
                "Report project JSON could not be replaced safely",
            ) from exc
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            if parent >= 0:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                self._admission._close_directory(parent)

    def replace_json(self, parts: Sequence[str], value: Mapping[str, object]) -> None:
        checked = self._parts(parts, create=True)
        raw = canonical_json_v1(dict(value)).encode("utf-8")
        fcntl, lock_fd = self._lock()
        try:
            self._replace_json_locked(checked, raw)
        finally:
            self._unlock(fcntl, lock_fd)

    def mutate_json(
        self,
        parts: Sequence[str],
        mutator: Any,
    ) -> dict[str, object]:
        """Atomically read, transform, and replace one project JSON object.

        A read followed by a separately locked ``replace_json`` is not a
        transaction: two backend workers can both read the same index and the
        last writer can erase the first worker's artifact.  This method keeps
        the read, callback, validation, and atomic replace under one
        admission-root lock.
        """

        if not callable(mutator):
            raise TypeError("JSON mutator must be callable")
        checked = self._parts(parts, create=True)
        fcntl, lock_fd = self._lock()
        try:
            current = self._parse_json(self._read_bytes(checked))
            updated = mutator(current)
            if type(updated) is not dict:
                raise TypeError("JSON mutator must return a built-in dict")
            self._replace_json_locked(
                checked,
                canonical_json_v1(updated).encode("utf-8"),
            )
            return updated
        except EvidencePersistenceError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            if isinstance(exc, TypeError) and str(exc) == "JSON mutator must return a built-in dict":
                raise
            raise EvidencePersistenceError(
                "EVIDENCE_PERSISTENCE_WRITE_FAILED",
                "Report project JSON transaction could not be completed safely",
            ) from exc
        finally:
            self._unlock(fcntl, lock_fd)

    def close(self) -> None:
        self._admission.close()


@dataclass(frozen=True, slots=True)
class ReportEvidenceProductionReceiptV1:
    """A host-issued, exact-run-bound Report evidence production capability.

    The private issuer object and the factory's identity admission table are
    deliberately both checked.  A caller can copy the visible fields, but a
    copied or locally constructed value is not a live receipt for this host.
    """

    receipt_id: str
    actor_ref: str
    project_ref: str
    session_ref: str
    scope_ref: str
    run_id: str
    model_run_id: str
    upload_hash: str
    binding_digest: str
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _required_text(self.receipt_id, "receipt_id")
        for name in ("actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id"):
            _required_text(getattr(self, name), name)
        _required_digest(self.upload_hash, "upload_hash")
        _required_digest(self.binding_digest, "binding_digest")
        if self._issuer is None:
            raise ValueError("production receipt requires a host issuer")

    def _payload(self) -> dict[str, str]:
        return {
            "actor_ref": self.actor_ref,
            "project_ref": self.project_ref,
            "session_ref": self.session_ref,
            "scope_ref": self.scope_ref,
            "run_id": self.run_id,
            "model_run_id": self.model_run_id,
            "upload_hash": self.upload_hash,
        }

    @classmethod
    def _from_host(
        cls,
        *,
        receipt_id: str,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        scope_ref: str,
        run_id: str,
        model_run_id: str,
        upload_hash: str,
        binding_digest: str,
        issuer: object,
    ) -> "ReportEvidenceProductionReceiptV1":
        return cls(
            receipt_id=receipt_id,
            actor_ref=actor_ref,
            project_ref=project_ref,
            session_ref=session_ref,
            scope_ref=scope_ref,
            run_id=run_id,
            model_run_id=model_run_id,
            upload_hash=upload_hash,
            binding_digest=binding_digest,
            _issuer=issuer,
        )


def _validate_envelope_identity(
    envelope: Mapping[str, object],
    *,
    run_id: str,
    model_run_id: str,
) -> None:
    result_identity = envelope.get("result_identity")
    if not isinstance(result_identity, Mapping):
        raise EvidenceProjectionError(
            "EVIDENCE_OWNER_CONTEXT_MISMATCH",
            "Report evidence envelope is missing its server-owned result identity",
        )
    if (
        result_identity.get("run_id") != run_id
        or result_identity.get("model_run_id") != model_run_id
        or result_identity.get("result_ref") != f"report-result:{run_id}"
    ):
        raise EvidenceProjectionError(
            "EVIDENCE_OWNER_CONTEXT_MISMATCH",
            "Report evidence envelope identity does not match its run owner",
        )


def build_workflow_report_evidence_envelope(
    *,
    run_id: str,
    model_run_id: str,
    upload_hash: str,
    primary_model_type: str,
    regression_table: Mapping[str, object],
    issue_dicts: object = (),
    allow_empty_facts: bool = False,
) -> dict[str, object]:
    """Adapt bounded Report table fields into the locked C0 envelope.

    This adapter does not recalculate a coefficient.  It accepts only the
    fields already projected by ``build_regression_table`` and rejects an
    incomplete table instead of manufacturing a partial numeric fact.
    """

    run_id = _required_text(run_id, "run_id")
    model_run_id = _required_text(model_run_id, "model_run_id")
    primary_model_type = _required_text(primary_model_type, "primary_model_type")
    if type(upload_hash) is not str or len(upload_hash) != 64 or any(
        character not in "0123456789abcdef" for character in upload_hash
    ):
        raise ValueError("upload_hash must be a lowercase SHA-256 digest")
    if type(regression_table) is not dict:
        raise TypeError("regression_table must be a server-produced dict")
    models = regression_table.get("models")
    rows = regression_table.get("rows")
    if not isinstance(models, list) or not models or not isinstance(rows, list):
        raise ValueError("Report evidence requires a bounded regression table")
    from ..report_view_model import ServerOwnedValidationReceiptV1

    raw_receipts = regression_table.get("_server_owned_validation_receipts", {})
    if not isinstance(raw_receipts, dict):
        raise ValueError("server-owned validation receipt map is invalid")
    receipts: dict[str, ServerOwnedValidationReceiptV1] = {}
    for model in models:
        if not isinstance(model, dict) or type(model.get("id")) is not str:
            raise ValueError("Report evidence model identity is invalid")
        model_id = model["id"]
        result_digest = model.get("result_digest")
        receipt = raw_receipts.get(model_id)
        if receipt is None:
            continue
        if (
            type(receipt) is not ServerOwnedValidationReceiptV1
            or not receipt.is_server_owned()
            or receipt.run_id != run_id
            or receipt.model_id != model_id
            or receipt.input_digest != upload_hash
            or receipt.result_digest != result_digest
        ):
            raise ValueError("server-owned validation receipt identity is invalid")
        receipts[model_id] = receipt

    for row in rows:
        if not isinstance(row, dict):
            continue
        cells = row.get("models")
        if not isinstance(cells, dict):
            continue
        for cell in cells.values():
            if isinstance(cell, dict) and any(
                key in cell for key in ("validation", "oracle_checks", "validation_level")
            ):
                raise ValueError("server-owned validation receipt is required")
    artifact_id = f"report:{run_id}"
    source_digest = sha256_canonical(
        {"artifact_id": artifact_id, "run_id": run_id, "model_run_id": model_run_id}
    )
    facts: list[dict[str, object]] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get("term")) is not str:
            raise ValueError("Report evidence regression rows are invalid")
        cells = row.get("models")
        if not isinstance(cells, dict):
            raise ValueError("Report evidence regression cells are invalid")
        for model in models:
            if not isinstance(model, dict) or type(model.get("id")) is not str:
                raise ValueError("Report evidence model identity is invalid")
            model_id = model["id"]
            cell = cells.get(model_id)
            if cell is None:
                continue
            if not isinstance(cell, dict):
                raise ValueError("Report evidence coefficient cell is invalid")
            estimate = cell.get("estimate")
            if allow_empty_facts and "estimate" in cell and estimate is None:
                # The structured snapshot preserves this cell as typed
                # missing; no coefficient value or validation is invented.
                continue
            if isinstance(estimate, bool) or not isinstance(estimate, (int, float)) or not math.isfinite(float(estimate)):
                raise ValueError("Report evidence coefficient estimate is unavailable")
            nobs = model.get("nobs")
            denominator: object = {
                "status": "not_applicable",
                "reason": "model observation count was not declared",
            }
            if isinstance(nobs, int) and not isinstance(nobs, bool) and nobs > 0:
                denominator = {"kind": "analysis_rows", "value": nobs, "unit": "row"}
            standard_error = cell.get("std_error")
            se_wire: object = {
                "status": "not_applicable",
                "reason": "standard error was not declared by the model packet",
            }
            if isinstance(standard_error, (int, float)) and not isinstance(standard_error, bool) and math.isfinite(float(standard_error)) and float(standard_error) >= 0:
                se_wire = float(standard_error)
            interval = cell.get("confidence_interval")
            interval_wire: object = {
                "status": "not_applicable",
                "reason": "confidence interval was not declared by the model packet",
            }
            level_wire: object = {
                "status": "not_applicable",
                "reason": "confidence level was not declared by the model packet",
            }
            interval_method = cell.get("confidence_interval_method")
            if isinstance(interval, Mapping):
                interval_method = interval.get("method")
                interval = [interval.get("lower"), interval.get("upper")]
            if isinstance(interval, (list, tuple)) and len(interval) == 2 and isinstance(interval_method, str) and interval_method:
                lower, upper = interval
                if all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) for value in (lower, upper)) and float(lower) <= float(upper):
                    interval_wire = {"lower": float(lower), "upper": float(upper), "method": interval_method}
            confidence_level = cell.get("confidence_level")
            if type(confidence_level) in (int, float) and math.isfinite(confidence_level) and 0 < confidence_level < 1:
                level_wire = float(confidence_level)
            direction: object = {
                "status": "not_applicable",
                "reason": "test direction was not declared by the model packet",
            }
            if cell.get("test_direction") in ("two_sided", "greater", "less"):
                direction = cell["test_direction"]
            receipt = receipts.get(model_id)
            oracle_checks: list[dict[str, object]] = []
            validation_level = ValidationLevelV1.NONE.value
            if receipt is not None:
                check = receipt.check_for_term(row["term"])
                if check is None:
                    raise ValueError("server-owned validation receipt is missing a numeric fact check")
                check = dict(check)
                check.pop("term", None)
                oracle_checks = [check]
                if check.get("status") == "pass":
                    validation_level = ValidationLevelV1.SAME_LIBRARY_REGRESSION.value
            facts.append(
                {
                    "fact_id": f"fact:{run_id}:{model_id}:{row_index}",
                    "estimand_id": row["term"],
                    "statistic_id": "model_coefficient",
                    "value": float(estimate),
                    "denominator": denominator,
                    "weight": {"status": "not_applicable", "reason": "weight basis is model-owned"},
                    "unit": "coefficient",
                    "scale": "linear",
                    "standard_error": se_wire,
                    "confidence_interval": interval_wire,
                    "confidence_level": level_wire,
                    "test_direction": direction,
                    "reference_distribution": cell.get("reference_distribution") or {"status": "not_applicable", "reason": "distribution was not declared by the model packet"},
                    "multiple_comparison": {
                        "family_id": {"status": "not_applicable", "reason": "Report adapter does not declare a comparison family"},
                        "correction": {"status": "not_applicable", "reason": "Report adapter does not declare a correction"},
                    },
                    "evaluation_design": EvaluationDesignV1.IN_SAMPLE.value,
                    "source_selector": {
                        "artifact_ref": artifact_id,
                        "selector": f"$.regression_table.rows[{row_index}].models.{model_id}.estimate",
                        "artifact_digest": source_digest,
                    },
                    "oracle_checks": oracle_checks,
                    "validation_level": validation_level,
                }
            )
    if not facts and not allow_empty_facts:
        raise ValueError("Report evidence requires at least one bounded numeric fact")
    warnings: list[dict[str, str]] = []
    reason_messages: dict[str, str] = {}
    execution_codes: list[str] = []
    availability_codes: list[str] = []
    completeness_codes: list[str] = []
    has_blocking_issue = False
    has_failed_issue = False
    has_degraded_issue = False

    def _append_unique(values: list[str], code: str) -> None:
        if code not in values:
            values.append(code)

    def _affects_completeness(issue: Mapping[str, object], *, failed: bool, blocked: bool) -> bool:
        explicit = issue.get("affects_completeness")
        if type(explicit) is bool:
            return explicit
        impact = str(issue.get("evidence_impact") or issue.get("impact") or "").strip().lower()
        if impact in {"informational", "methodological", "none", "not_applicable"}:
            return False
        if impact in {"completeness", "missing", "unavailable", "degraded"}:
            return True
        if failed or blocked:
            return True
        code = str(issue.get("code") or "").upper()
        return any(token in code for token in ("MISSING", "UNAVAILABLE", "INCOMPLETE", "EVIDENCE"))

    if isinstance(issue_dicts, (list, tuple)):
        from .report_result_sections import bounded_result_input

        for issue in bounded_result_input(issue_dicts):
            if not isinstance(issue, Mapping):
                continue
            code = issue.get("code")
            message = issue.get("message")
            if not isinstance(code, str) or not code.strip():
                continue
            code = code.strip()
            if isinstance(message, str):
                warnings.append({"code": code, "message": message})
                reason_messages.setdefault(code, message)
            severity = str(issue.get("severity") or "").upper()
            state = str(issue.get("status") or issue.get("state") or "").lower()
            failed = severity in {"BLOCKER", "ERROR", "FAILED"} or state in {
                "failed",
                "failure",
            }
            blocked = severity in {"BLOCKER", "ERROR"} or state in {
                "blocked",
                "unavailable",
            }
            degraded = _affects_completeness(issue, failed=failed, blocked=blocked) or state in {
                "partial",
                "degraded",
            }
            has_failed_issue = has_failed_issue or failed
            has_blocking_issue = has_blocking_issue or blocked
            has_degraded_issue = has_degraded_issue or degraded
            if failed:
                _append_unique(execution_codes, code)
            if blocked:
                _append_unique(availability_codes, code)
            if degraded:
                _append_unique(completeness_codes, code)

    def _reason_entries(codes: list[str]) -> list[dict[str, object]]:
        return [
            {
                "code": code,
                "message": reason_messages.get(code, code),
                "source_refs": [f"run:{run_id}"],
            }
            for code in codes
        ]

    if has_failed_issue:
        execution_status = ExecutionStatusV1.FAILED.value
    elif has_blocking_issue:
        execution_status = ExecutionStatusV1.BLOCKED.value
    else:
        execution_status = ExecutionStatusV1.COMPLETED.value
    availability = (
        AvailabilityStatusV1.NOT_AVAILABLE.value
        if has_blocking_issue or has_failed_issue
        else AvailabilityStatusV1.AVAILABLE.value
    )
    completeness_status = (
        CompletenessStatusV1.INSUFFICIENT.value
        if has_blocking_issue or has_failed_issue
        else (
            CompletenessStatusV1.DEGRADED.value
            if has_degraded_issue
            else CompletenessStatusV1.COMPLETE.value
        )
    )
    admitted_facts = [] if has_blocking_issue or has_failed_issue else facts
    minimum_required = (
        ValidationLevelV1.SAME_LIBRARY_REGRESSION.value
        if receipts
        else ValidationLevelV1.NONE.value
    )
    validation_requirement_status = (
        ValidationRequirementStatusV1.MET.value
        if receipts and admitted_facts and all(
            fact["validation_level"] == ValidationLevelV1.SAME_LIBRARY_REGRESSION.value
            for fact in admitted_facts
        )
        else (
            ValidationRequirementStatusV1.NOT_MET.value
            if receipts
            else ValidationRequirementStatusV1.NOT_APPLICABLE.value
        )
    )
    input_ref = f"dataset:{upload_hash}"
    envelope = EvidenceEnvelopeV1.from_dict(
        {
            "result_identity": {
                "result_ref": f"report-result:{run_id}",
                "run_id": run_id,
                "model_run_id": model_run_id,
                "schema_version": "1.0",
            },
            "execution_status": execution_status,
            "availability": availability,
            "completeness_status": completeness_status,
            "execution_reasons": _reason_entries(execution_codes) if execution_status != ExecutionStatusV1.COMPLETED.value else [],
            "availability_reasons": _reason_entries(availability_codes) if availability != AvailabilityStatusV1.AVAILABLE.value else [],
            "degradation_reasons": _reason_entries(completeness_codes) if completeness_status != CompletenessStatusV1.COMPLETE.value else [],
            "numerical_method": NumericalMethodV1.DETERMINISTIC_NUMERIC.value,
            "inference_basis": InferenceBasisV1.DESCRIPTIVE.value,
            "evaluation_design": EvaluationDesignV1.IN_SAMPLE.value,
            "validation_summary": {
                "levels_present": sorted(
                    {fact["validation_level"] for fact in admitted_facts},
                    key=lambda value: validation_level_rank(ValidationLevelV1(value)),
                ),
                "minimum_required": minimum_required,
                "requirement_status": validation_requirement_status,
            },
            "method": {"id": "workbench.report.evidence", "version": "1.0", "model_family": primary_model_type},
            "estimand": {"id": "model_coefficient", "population": "analysis-sample"},
            "input_provenance": {"artifact_ref": input_ref, "artifact_digest": upload_hash},
            "assumptions": [],
            "diagnostics": [],
            "figures": [],
            "warnings": warnings,
            "dependencies": [{"artifact_ref": input_ref}],
            "numeric_facts": admitted_facts,
            "family_evidence": (
                {"model_family": primary_model_type, "model_ids": [model["id"] for model in models if isinstance(model, dict) and isinstance(model.get("id"), str)]}
                if admitted_facts
                else {}
            ),
            "oracle": {},
            "lineage_refs": [f"run:{run_id}", input_ref],
        }
    )
    return envelope.to_dict()


class ServerOwnedReportEvidenceOwnerFactoryV1:
    """Create immutable Report owners from one deployment-owned C0 store."""

    __slots__ = (
        "_evidence_store",
        "_registry",
        "_project_file_store",
        "_actor_ref",
        "_project_ref",
        "_session_ref",
        "_scope_ref",
        "_canonical_project_root",
        "_authority_handle",
        "_receipt_issuer",
        "_production_receipts",
        "_owners",
        "_lock",
    )

    def __init__(
        self,
        evidence_store: EvidencePacketStoreV1,
        registry: EvidenceRegistryV1,
        *,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        scope_ref: str,
        canonical_project_root: Path | str,
        authority_handle: object,
    ) -> None:
        if type(evidence_store) is not EvidencePacketStoreV1:
            raise TypeError("Report owner factory requires the server-owned packet store")
        if type(registry) is not EvidenceRegistryV1:
            raise TypeError("Report owner factory requires the server-owned registry")
        if authority_handle is None:
            raise ValueError("Report owner factory requires the host authority")
        for name, value in (
            ("actor_ref", actor_ref),
            ("project_ref", project_ref),
            ("session_ref", session_ref),
            ("scope_ref", scope_ref),
        ):
            _required_text(value, name)
        if registry.scope_ref != scope_ref:
            raise ValueError("Report owner factory scope does not match the registry")
        admission = evidence_store.admission
        if getattr(admission, "_authority_handle", None) is not authority_handle:
            raise ValueError("Report owner factory authority is not the store admission authority")
        if registry._host_authority_handle() is not authority_handle:
            raise ValueError("Report owner factory authority is not the registry authority")
        admission._validate_authority()
        canonical_root = Path(canonical_project_root).expanduser().resolve(strict=False)
        _validate_production_evidence_root(evidence_store, canonical_root)
        self._evidence_store = evidence_store
        self._registry = registry
        self._project_file_store = HostBoundProjectFileStoreV1.from_host(
            canonical_root,
            authority_handle=authority_handle,
            scope_ref=scope_ref,
        )
        self._actor_ref = actor_ref
        self._project_ref = project_ref
        self._session_ref = session_ref
        self._scope_ref = scope_ref
        self._canonical_project_root = canonical_root
        self._authority_handle = authority_handle
        self._receipt_issuer = object()
        self._production_receipts: dict[int, ReportEvidenceProductionReceiptV1] = {}
        self._owners: dict[str, ServerOwnedReportEvidencePersistenceV1] = {}
        self._lock = RLock()

    @classmethod
    def from_host(
        cls,
        evidence_store: EvidencePacketStoreV1,
        registry: EvidenceRegistryV1,
        *,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        scope_ref: str,
        canonical_project_root: Path | str,
        authority_handle: object,
    ) -> "ServerOwnedReportEvidenceOwnerFactoryV1":
        """Construct a factory from the deployment's live C0 capabilities."""

        return cls(
            evidence_store,
            registry,
            actor_ref=actor_ref,
            project_ref=project_ref,
            session_ref=session_ref,
            scope_ref=scope_ref,
            canonical_project_root=canonical_project_root,
            authority_handle=authority_handle,
        )

    @classmethod
    def _from_host(cls, *args: object, **kwargs: object) -> "ServerOwnedReportEvidenceOwnerFactoryV1":
        """Deployment-only construction seam; callers still need live C0 objects."""

        return cls(*args, **kwargs)  # type: ignore[arg-type]

    def _require_host_authority(self) -> None:
        """Revalidate the external authority before a host uses this factory."""

        if self._registry._host_authority_handle() is not self._authority_handle:
            raise EvidenceProjectionError(
                "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "Report owner factory authority is no longer the registry authority",
            )
        self._evidence_store.admission._validate_authority()
        self._project_file_store._admission._validate_authority()

    def close(self) -> None:
        """Close the project-file admission owned by this host factory."""

        self._project_file_store.close()

    @staticmethod
    def report_evidence_file_sha256(envelope: Mapping[str, object]) -> str:
        """Return the hash of the exact canonical bytes the host will write."""

        if type(envelope) is not dict:
            raise TypeError("Report evidence envelope must be a built-in dict")
        return hashlib.sha256(canonical_json_v1(dict(envelope)).encode("utf-8")).hexdigest()

    def prepare_report_evidence_envelope(
        self, *, run_id: str, model_run_id: str, upload_hash: str,
        primary_model_type: str, regression_table: dict,
        model_artifact_ids: Sequence[str], report_fields: dict,
        diagnostic_summary: dict, issue_dicts: object = (),
    ) -> dict[str, object]:
        """Seal bounded pre-render producer inputs and actual model artifacts.

        The snapshot is not report output and never depends on the mutable
        diagnostic summary/index or on an export. Only the resulting C0
        envelope is a consumer source. Retries cannot overwrite this snapshot.
        """
        from ..evidence.result_dependencies import capture_result_dependencies, verify_result_dependencies
        from ..engine.stages.estimation import _result_for_downstream
        from .report_result_sections import (
            build_report_result_input, extend_report_evidence, production_regression_table,
            report_artifact_refs,
        )

        self._require_host_authority()
        store = self._project_file_store
        sources = capture_result_dependencies(store, project_ref=self._project_ref,
            run_id=run_id, artifact_ids=model_artifact_ids).to_dict()
        model_results = {}
        model_artifacts = {}
        for row in sources["records"]:
            raw = store._read_bytes(row["path"], max_bytes=8 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Model source changed before producer read")
            packet = store._parse_json(raw)
            identity = row["artifact_id"]
            payload_identity = identity
            if row["index_record"]["artifact_type"] == "model_result_packet":
                from ..contracts.common.envelope import PacketEnvelope

                typed_packet = PacketEnvelope.from_dict(packet)
                if typed_packet.contract != "linear_mixed_effects.result":
                    raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Undeclared model result packet")
                payload_identity = typed_packet.payload.get("model_id")
            model = next((item for item in regression_table["models"] if item["id"] == payload_identity), None)
            if model is None:
                raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Model artifact is not in the producer table")
            payload = _result_for_downstream(model.get("model_type") or primary_model_type, packet)
            if payload.get("model_id", payload_identity) != payload_identity or payload_identity in model_results:
                raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Model artifact identity differs from its payload")
            bindings = [payload]
            if isinstance(payload.get("execution_binding"), Mapping):
                bindings.append(payload["execution_binding"])
            for binding in bindings:
                if "run_id" in binding and binding["run_id"] != run_id:
                    raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Model packet belongs to another run")
            if model.get("result_digest") is not None and sha256_canonical(payload) != model["result_digest"]:
                raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Producer table does not match persisted model")
            model_results[payload_identity] = payload
            model_artifacts[payload_identity] = identity
        if model_run_id not in model_results:
            raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Primary model source is missing")
        # Only the family's explicit model-bound references are read. The
        # mutable index supplies membership, never digest or identity authority.
        report_refs = {identity: report_artifact_refs(model) for identity, model in model_results.items()}
        extra_ids = sorted({key for refs in report_refs.values() for key in refs})
        if set(extra_ids) & set(model_artifact_ids):
            raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Report input cannot alias a model artifact")
        report_artifacts, report_dependencies = {}, {}
        if extra_ids:
            extra = capture_result_dependencies(store, project_ref=self._project_ref,
                run_id=run_id, artifact_ids=extra_ids).to_dict()
            extra_records = {row["artifact_id"]: row for row in extra["records"]}
            for identity, refs in report_refs.items():
                if not refs:
                    continue
                model = model_results[identity]
                expected_metadata = {"run_id": run_id, "dataset_hash": upload_hash,
                    "contract_hash": model.get("contract_hash"), "analysis_view_hash": model.get("analysis_view_hash"),
                    "model_spec": model.get("selected_specification")}
                if any(value is None for value in expected_metadata.values()):
                    raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", "Report source execution binding is missing")
                payloads = {}
                for artifact_id, path in refs.items():
                    row = extra_records[artifact_id]
                    if (row["index_record"]["path"] != path
                            or row["index_record"]["artifact_type"] != "time_series_json"
                            or row["index_record"]["step"] != "arma_garch"):
                        raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Report source reference differs from index binding")
                    raw = store._read_bytes(row["path"], max_bytes=8 * 1024 * 1024)
                    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                        raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Report source changed before producer read")
                    packet = store._parse_json(raw)
                    metadata, payload = packet.get("metadata"), packet.get("payload")
                    if (packet.get("artifact_id") != artifact_id or not isinstance(metadata, Mapping)
                            or not isinstance(payload, Mapping)
                            or any(canonical_json_v1(metadata.get(key)) != canonical_json_v1(value)
                                   for key, value in expected_metadata.items())):
                        raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Report artifact belongs to a different execution")
                    # Charts are bound references, not copies of potentially
                    # large series arrays in the public result snapshot.
                    payloads[artifact_id] = {} if artifact_id.startswith("ts.chart.") else payload
                report_artifacts[identity] = payloads
                report_dependencies[identity] = list(payloads)
            sources = {**sources, "records": [*sources["records"], *extra["records"]]}
        source_ids = [*model_artifact_ids, *extra_ids]
        table = production_regression_table(regression_table, model_results)
        envelope = build_workflow_report_evidence_envelope(run_id=run_id, model_run_id=model_run_id,
            upload_hash=upload_hash, primary_model_type=primary_model_type,
            regression_table=table, issue_dicts=issue_dicts, allow_empty_facts=True)
        snapshot = build_report_result_input(run_id=run_id, model_run_id=model_run_id,
            primary_model_type=primary_model_type, regression_table=table, model_results=model_results,
            report_fields=report_fields, diagnostic_summary=diagnostic_summary,
            arma_artifacts=report_artifacts, arma_dependency_ids=report_dependencies)
        snapshot["section_model_ids"] = {
            name: [model_artifacts[identity] for identity in identities]
            for name, identities in snapshot["section_model_ids"].items()
        }
        snapshot_id = f"result-input:{run_id}"
        snapshot_path = ("runs", run_id, "result_input.json")
        from ..domain import ArtifactRecord

        snapshot_row = ArtifactRecord(
            artifact_id=snapshot_id, path="result_input.json",
            artifact_type="result_input", step="result_input", inputs=tuple(source_ids),
            sha256=hashlib.sha256(canonical_json_v1(snapshot).encode("utf-8")).hexdigest(),
            code_version=__version__,
        ).to_dict()
        # Validate the section contract before any snapshot/index write.
        provisional = {**sources, "records": [*sources["records"],
            {"artifact_id": snapshot_id, "path": list(snapshot_path), "sha256": snapshot_row["sha256"],
             "index_record": snapshot_row}]}
        extend_report_evidence(envelope, snapshot=snapshot, manifest=provisional)
        verify_result_dependencies(store, sources, project_ref=self._project_ref, run_id=run_id)
        store.write_json_once(snapshot_path, snapshot)

        def register(index):
            records = index["artifacts"]
            matching = [row for row in records if row.get("artifact_id") == snapshot_id or row.get("path") == "result_input.json"]
            if matching:
                if len(matching) != 1 or canonical_json_v1(matching[0]) != canonical_json_v1(snapshot_row):
                    raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Snapshot index binding already differs")
            else:
                records.append(snapshot_row)
            return index

        store.mutate_json(("runs", run_id, "artifacts_index.json"), register)
        sealed = capture_result_dependencies(store, project_ref=self._project_ref, run_id=run_id,
            artifact_ids=[*source_ids, snapshot_id]).to_dict()
        if sealed != provisional:
            raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "Producer sources changed during sealing")
        return extend_report_evidence(envelope, snapshot=snapshot, manifest=sealed)

    def write_report_evidence_file(
        self,
        *,
        owner: ServerOwnedReportEvidencePersistenceV1,
        production_receipt: ReportEvidenceProductionReceiptV1,
        envelope: Mapping[str, object],
    ) -> str:
        """Write only after this factory has issued the exact Report owner.

        The file is deliberately written after C0 owner creation.  A failed
        write can therefore leave the run unavailable, but it cannot leave an
        unowned file that later code treats as Report evidence.
        """

        if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CAPABILITY_REQUIRED",
                "Report evidence file writes require the server-owned Report owner",
            )
        if type(envelope) is not dict:
            raise TypeError("Report evidence envelope must be a built-in dict")
        if (
            getattr(owner, "_project_file_store", None) is not self._project_file_store
            or getattr(owner, "_registry", None) is not self._registry
            or getattr(owner, "_authority_handle", None) is not self._authority_handle
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                "Report evidence owner was not issued by this host factory",
            )
        owner._require_report_authority()
        input_provenance = envelope.get("input_provenance")
        upload_hash = (
            input_provenance.get("artifact_digest")
            if isinstance(input_provenance, Mapping)
            else None
        )
        self._validate_production_receipt(
            production_receipt,
            run_id=owner.run_id,
            model_run_id=owner.model_run_id,
            upload_hash=upload_hash if isinstance(upload_hash, str) else "",
        )
        expected_hash = self.report_evidence_file_sha256(envelope)
        if expected_hash != owner.artifact_file_sha256:
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH",
                "Report evidence envelope does not match the owner-bound file hash",
            )
        self._require_host_authority()
        self._project_file_store.write_json_once(
            ("runs", owner.run_id, "report_evidence.json"),
            envelope,
        )
        actual_hash = self._project_file_store.sha256(
            ("runs", owner.run_id, "report_evidence.json"),
        )
        if actual_hash != owner.artifact_file_sha256:
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH",
                "Report evidence file bytes do not match the owner-bound hash",
            )
        return actual_hash

    def validate_runtime_binding(
        self,
        *,
        project_ref: str,
        session_ref: str,
        data_project_root: Path | str | None,
    ) -> None:
        """Require the Agent/Notebook runtime to use this factory's scope."""

        if project_ref != self._project_ref or session_ref != self._session_ref:
            raise ValueError(
                "Report owner factory project/session scope does not match the runtime"
            )
        if data_project_root is None:
            raise ValueError(
                "Report owner factory requires the runtime's canonical project root"
            )
        try:
            runtime_root = Path(data_project_root).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ValueError("runtime project root is invalid") from exc
        if runtime_root != self._canonical_project_root:
            raise ValueError(
                "Report owner factory project root does not match the runtime"
            )

    def issue_production_receipt(
        self,
        *,
        run_id: str,
        model_run_id: str,
        upload_hash: str,
    ) -> ReportEvidenceProductionReceiptV1:
        """Issue a live production receipt at the host Report boundary."""

        run_id = _required_text(run_id, "run_id")
        model_run_id = _required_text(model_run_id, "model_run_id")
        upload_hash = _required_digest(upload_hash, "upload_hash")
        self._require_host_authority()
        payload = {
            "actor_ref": self._actor_ref,
            "project_ref": self._project_ref,
            "session_ref": self._session_ref,
            "scope_ref": self._scope_ref,
            "run_id": run_id,
            "model_run_id": model_run_id,
            "upload_hash": upload_hash,
        }
        binding_digest = sha256_canonical(payload)
        receipt = ReportEvidenceProductionReceiptV1._from_host(
            receipt_id=f"report-evidence-production:{binding_digest}",
            actor_ref=self._actor_ref,
            project_ref=self._project_ref,
            session_ref=self._session_ref,
            scope_ref=self._scope_ref,
            run_id=run_id,
            model_run_id=model_run_id,
            upload_hash=upload_hash,
            binding_digest=binding_digest,
            issuer=self._receipt_issuer,
        )
        with self._lock:
            self._production_receipts[id(receipt)] = receipt
        return receipt

    def _validate_production_receipt(
        self,
        receipt: object,
        *,
        run_id: str,
        model_run_id: str,
        upload_hash: str,
    ) -> ReportEvidenceProductionReceiptV1:
        if type(receipt) is not ReportEvidenceProductionReceiptV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PRODUCTION_RECEIPT_REQUIRED",
                "Report evidence admission requires a host-issued production receipt",
            )
        typed_receipt = receipt
        with self._lock:
            if self._production_receipts.get(id(typed_receipt)) is not typed_receipt:
                raise EvidenceProjectionError(
                    "EVIDENCE_PRODUCTION_RECEIPT_NOT_LIVE",
                    "Report evidence production receipt was not issued by this live host factory",
                )
        if typed_receipt._issuer is not self._receipt_issuer:
            raise EvidenceProjectionError(
                "EVIDENCE_PRODUCTION_RECEIPT_INVALID",
                "Report evidence production receipt issuer is not this host factory",
            )
        expected_payload = {
            "actor_ref": self._actor_ref,
            "project_ref": self._project_ref,
            "session_ref": self._session_ref,
            "scope_ref": self._scope_ref,
            "run_id": run_id,
            "model_run_id": model_run_id,
            "upload_hash": upload_hash,
        }
        if (
            typed_receipt._payload() != expected_payload
            or typed_receipt.binding_digest != sha256_canonical(expected_payload)
            or typed_receipt.receipt_id != f"report-evidence-production:{typed_receipt.binding_digest}"
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_PRODUCTION_RECEIPT_INVALID",
                "Report evidence production receipt is not bound to this exact run and source",
            )
        self._require_host_authority()
        return typed_receipt

    def create_for_run(
        self,
        *,
        run_id: str,
        model_run_id: str,
        production_receipt: ReportEvidenceProductionReceiptV1 | None = None,
        envelope: Mapping[str, object],
        artifact_file_sha256: str,
        confirmation_ref: object | None = None,
    ) -> ServerOwnedReportEvidencePersistenceV1:
        run_id = _required_text(run_id, "run_id")
        model_run_id = _required_text(model_run_id, "model_run_id")
        if confirmation_ref is not None:
            raise EvidenceProjectionError(
                "EVIDENCE_PRODUCTION_RECEIPT_REQUIRED",
                "confirmation_ref strings are not Report evidence production authority",
            )
        if type(envelope) is not dict:
            raise TypeError("Report evidence envelope must be a built-in dict")
        _validate_envelope_identity(
            envelope,
            run_id=run_id,
            model_run_id=model_run_id,
        )
        artifact_file_sha256 = _required_digest(artifact_file_sha256, "artifact_file_sha256")
        input_provenance = envelope.get("input_provenance")
        upload_hash = (
            input_provenance.get("artifact_digest")
            if isinstance(input_provenance, Mapping)
            else None
        )
        production_receipt = self._validate_production_receipt(
            production_receipt,
            run_id=run_id,
            model_run_id=model_run_id,
            upload_hash=upload_hash if isinstance(upload_hash, str) else "",
        )
        if upload_hash != production_receipt.upload_hash:
            raise EvidenceProjectionError(
                "EVIDENCE_PRODUCTION_RECEIPT_INVALID",
                "Report evidence envelope source does not match the production receipt",
            )
        confirmation_ref = production_receipt.receipt_id
        with self._lock:
            existing = self._owners.get(run_id)
            if existing is not None:
                if (
                    existing.model_run_id != model_run_id
                    or existing.confirmation_ref != confirmation_ref
                    or existing.artifact_file_sha256 != artifact_file_sha256
                ):
                    raise EvidenceProjectionError(
                        "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                        "a run cannot be rebound to a different Report evidence identity",
                    )
                if existing._canonical_report_artifact().envelope_digest != sha256_canonical(envelope):
                    raise EvidenceProjectionError(
                        "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                        "a run cannot be rebound to a different Report evidence envelope",
                    )
                return existing
            artifact_id = f"report:{run_id}"
            record = self._registry.admit_artifact(
                artifact_id=artifact_id,
                artifact_type="post_estimation",
                scope_ref=self._scope_ref,
                content=envelope,
                source_ref=f"source:run:{run_id}",
                validator_ref="validator:workbench-report-evidence:v1",
                execution_ref=f"execution:run:{run_id}",
                contract_digest=CONSUMER_PROJECTION_EVIDENCE_CONTRACT_DIGEST,
            )
            receipt = self._registry.persistence_receipt(record)
            binding = self._evidence_store.commit(record, receipt=receipt)
            owner = ServerOwnedReportEvidencePersistenceV1._from_host(
                self._evidence_store,
                self._registry,
                receipt,
                actor_ref=self._actor_ref,
                project_ref=self._project_ref,
                session_ref=self._session_ref,
                scope_ref=self._scope_ref,
                run_id=run_id,
                model_run_id=model_run_id,
                artifact_id=record.artifact_id,
                commit_id=binding.commit_id,
                confirmation_ref=confirmation_ref,
                artifact_file_sha256=artifact_file_sha256,
                canonical_project_root=self._canonical_project_root,
                project_file_store=self._project_file_store,
                authority_handle=self._authority_handle,
            )
            self._owners[run_id] = owner
            return owner

    def rehydrate_for_run(
        self,
        *,
        run_id: str,
        project_root: Path | str | None = None,
    ) -> ServerOwnedReportEvidencePersistenceV1 | None:
        """Rebuild one live Report owner from the host-owned durable bindings.

        The owner itself is intentionally not serialized.  After a local
        backend restart, this method revalidates the run's artifact index,
        canonical Report file hash, C0 registry admission, and packet-store
        commit before issuing a fresh host-bound owner.  A malformed, stale,
        or incomplete row returns ``None`` and remains unavailable; no raw
        ``model_results`` path is consulted.
        """

        run_id = _required_text(run_id, "run_id")
        self._require_host_authority()
        if project_root is not None:
            try:
                if Path(project_root).expanduser().resolve(strict=False) != self._canonical_project_root:
                    return None
            except (OSError, RuntimeError, TypeError, ValueError):
                return None
        with self._lock:
            existing = self._owners.get(run_id)
            if existing is not None:
                try:
                    existing._require_report_authority()
                except (AttributeError, TypeError, ValueError, EvidenceProjectionError):
                    return None
                return existing

            try:
                index = self._project_file_store.read_json(
                    ("runs", run_id, "artifacts_index.json"),
                )
                rows = index.get("artifacts")
                if index.get("schema_version", 1) != 1 or not isinstance(rows, list):
                    return None
                candidates = [
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and row.get("artifact_id") == f"report:{run_id}"
                    and row.get("artifact_type") == "post_estimation"
                    and row.get("path") == "report_evidence.json"
                ]
                if len(candidates) != 1:
                    return None
                row = candidates[0]

                model_run_id = row.get("model_run_id")
                confirmation_ref = row.get("confirmation_ref")
                artifact_file_sha256 = row.get("sha256")
                commit_id = row.get("evidence_commit_ref")
                artifact_id = row.get("artifact_id")
                if (
                    not all(
                        type(value) is str and value.strip()
                        for value in (model_run_id, confirmation_ref, commit_id, artifact_id)
                    )
                    or not isinstance(artifact_file_sha256, str)
                    or len(artifact_file_sha256) != 64
                    or any(char not in "0123456789abcdef" for char in artifact_file_sha256)
                    or not confirmation_ref.startswith("report-evidence-production:")
                    or len(confirmation_ref.removeprefix("report-evidence-production:")) != 64
                    or any(
                        char not in "0123456789abcdef"
                        for char in confirmation_ref.removeprefix("report-evidence-production:")
                    )
                    or not commit_id.startswith("commit:evidence:")
                ):
                    return None
                if any(
                    row.get(key) != expected
                    for key, expected in (
                        ("actor_ref", self._actor_ref),
                        ("project_ref", self._project_ref),
                        ("session_ref", self._session_ref),
                        ("scope_ref", self._scope_ref),
                        ("run_id", run_id),
                        ("evidence_run_id", run_id),
                        ("evidence_model_run_id", model_run_id),
                        ("model_run_id", model_run_id),
                        ("evidence_artifact_ref", artifact_id),
                        ("evidence_artifact_admission_ref", artifact_id),
                    )
                ):
                    return None

                evidence_path = ("runs", run_id, "report_evidence.json")
                if self._project_file_store.sha256(evidence_path) != artifact_file_sha256:
                    return None
                envelope = self._project_file_store.read_json(evidence_path)
                _validate_envelope_identity(
                    envelope,
                    run_id=run_id,
                    model_run_id=model_run_id,
                )

                admitted = self._registry.get(artifact_id, scope_ref=self._scope_ref)
                registry_receipt = self._registry.persistence_receipt(admitted)
                binding = self._evidence_store.load(
                    commit_id,
                    registry=self._registry,
                    receipt=registry_receipt,
                )
                artifact = self._evidence_store.load_packet(
                    commit_id,
                    registry=self._registry,
                    receipt=registry_receipt,
                )
                if (
                    binding.commit_id != commit_id
                    or binding.artifact_admission_ref != artifact_id
                    or artifact.artifact_id != artifact_id
                    or artifact.to_dict() != admitted.to_dict()
                    or artifact.envelope.to_dict() != envelope
                    or artifact.content_hash != row.get("evidence_content_hash")
                    or row.get("evidence_envelope_ref") != f"evidence-envelope:{artifact.envelope_digest}"
                    or row.get("evidence_commit_ref") != binding.commit_id
                ):
                    return None

                owner = ServerOwnedReportEvidencePersistenceV1._from_host(
                    self._evidence_store,
                    self._registry,
                    registry_receipt,
                    authority_handle=self._authority_handle,
                    actor_ref=self._actor_ref,
                    project_ref=self._project_ref,
                    session_ref=self._session_ref,
                    scope_ref=self._scope_ref,
                    run_id=run_id,
                    model_run_id=model_run_id,
                    artifact_id=artifact_id,
                    commit_id=commit_id,
                    confirmation_ref=confirmation_ref,
                    artifact_file_sha256=artifact_file_sha256,
                    canonical_project_root=self._canonical_project_root,
                    project_file_store=self._project_file_store,
                )
                self._owners[run_id] = owner
            except (
                EvidenceProjectionError,
                EvidencePersistenceError,
                EvidenceRegistryError,
                OSError,
                AttributeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                return None

        from .results_service import register_report_evidence_owner

        register_report_evidence_owner(owner)
        return owner

    def __copy__(self):
        raise TypeError("host-bound Report owner factories cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("host-bound Report owner factories cannot be copied")

    def __reduce__(self):
        raise TypeError("host-bound Report owner factories cannot be serialized")


def build_report_evidence_artifact_index_record(
    owner: ServerOwnedReportEvidencePersistenceV1,
    *,
    run_root: Path,
    path: Path,
    inputs: list[str],
) -> dict[str, object]:
    """Build the C0-bound index row for the immutable Report evidence file."""

    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        raise TypeError("Report evidence index requires the server-owned owner")
    owner._require_report_authority()
    project_store = getattr(owner, "_project_file_store", None)
    if not isinstance(project_store, HostBoundProjectFileStoreV1):
        raise EvidenceProjectionError(
            "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
            "Report evidence index requires the host-bound project file capability",
        )
    parts = project_store._parts_for_owner(
        owner,
        run_root=run_root,
        path=path,
        filename="report_evidence.json",
    )
    if type(inputs) is not list or any(type(item) is not str or not item.strip() for item in inputs):
        raise TypeError("Report evidence index inputs must be non-empty strings")

    actual_file_sha256 = project_store.sha256(parts)
    if actual_file_sha256 != owner.artifact_file_sha256:
        raise EvidenceProjectionError(
            "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH",
            "Report evidence file no longer matches the owner-bound canonical file",
        )
    artifact = owner._canonical_report_artifact()
    try:
        stored_envelope = project_store.read_json(parts)
    except (EvidencePersistenceError, OSError, TypeError, ValueError, KeyError) as exc:
        raise EvidenceProjectionError(
            "EVIDENCE_ARTIFACT_CONTENT_INVALID",
            "Report evidence file is not a readable canonical envelope",
        ) from exc
    if type(stored_envelope) is not dict or stored_envelope != artifact.envelope.to_dict():
        raise EvidenceProjectionError(
            "EVIDENCE_ARTIFACT_CONTENT_MISMATCH",
            "Report evidence file content is not the admitted server envelope",
        )
    validator_ref = (
        artifact.validator_ref.to_dict()
        if hasattr(artifact.validator_ref, "to_dict")
        else artifact.validator_ref
    )
    return {
        "artifact_id": owner.artifact_id,
        "path": "report_evidence.json",
        "artifact_type": artifact.artifact_type,
        "step": "report",
        "sha256": actual_file_sha256,
        "inputs": list(inputs),
        "config_hash": "",
        "code_version": __version__,
        "actor_ref": owner.actor_ref,
        "project_ref": owner.project_ref,
        "session_ref": owner.session_ref,
        "scope_ref": owner.scope_ref,
        "confirmation_ref": owner.confirmation_ref,
        "run_id": owner.run_id,
        "model_run_id": owner.model_run_id,
        "evidence_run_id": owner.run_id,
        "evidence_model_run_id": owner.model_run_id,
        "evidence_artifact_ref": artifact.artifact_id,
        "evidence_artifact_admission_ref": artifact.artifact_id,
        "evidence_content_hash": artifact.content_hash,
        "evidence_commit_ref": owner.commit_id,
        "evidence_envelope_ref": f"evidence-envelope:{artifact.envelope_digest}",
        "source_ref": artifact.source_ref,
        "validator_ref": validator_ref,
        "execution_ref": artifact.execution_ref,
        "contract_digest": artifact.contract_digest,
    }


def register_report_evidence_artifact(
    owner: ServerOwnedReportEvidencePersistenceV1,
    *,
    run_root: Path,
    path: Path,
    inputs: list[str],
) -> dict[str, object]:
    """Atomically add one idempotent C0 Report row to the run index."""

    record = build_report_evidence_artifact_index_record(
        owner,
        run_root=run_root,
        path=path,
        inputs=inputs,
    )
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        raise TypeError("Report evidence index requires the server-owned owner")
    project_store = getattr(owner, "_project_file_store", None)
    if not isinstance(project_store, HostBoundProjectFileStoreV1):
        raise EvidenceProjectionError(
            "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
            "Report evidence index requires the host-bound project file capability",
        )
    index_parts = project_store._parts_for_owner(
        owner,
        run_root=run_root,
        path=Path(run_root) / "artifacts_index.json",
        filename="artifacts_index.json",
    )
    def add_record(index: dict[str, object]) -> dict[str, object]:
        if index.get("schema_version", 1) != 1:
            raise ValueError("Report evidence artifact index is invalid")
        records = index.get("artifacts")
        if not isinstance(records, list):
            raise ValueError("Report evidence artifact index records are invalid")
        for existing in records:
            if not isinstance(existing, dict) or existing.get("artifact_id") != owner.artifact_id:
                continue
            if existing != record:
                raise EvidenceProjectionError(
                    "EVIDENCE_ARTIFACT_INDEX_CONFLICT",
                    "the exact Report evidence artifact is already indexed differently",
                )
            return index
        index["artifacts"] = [*records, record]
        return index

    project_store.mutate_json(index_parts, add_record)
    return record


__all__ = [
    "HostBoundProjectFileStoreV1",
    "ReportEvidenceProductionReceiptV1",
    "ServerOwnedReportEvidenceOwnerFactoryV1",
    "build_report_evidence_artifact_index_record",
    "register_report_evidence_artifact",
]
