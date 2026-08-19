"""Native service adapter that executes one compiled workflow step."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import fcntl
import os
import re
import secrets
import stat
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from scipy import stats

from .. import __version__
from ..api_errors import WorkbenchAPIError
from ..artifacts import read_json, sha256_file
from ..data_operations import (
    DataTransformSpecV1,
    FeatureRecipeOperationSpecV1,
    apply_data_transform,
    apply_feature_recipe_operation,
    preview_data_transform,
    preview_feature_recipe,
)
from ..econometrics.runner import apply_ols_covariance, run_ols
from ..exports import export_pdf, export_xlsx
from ..graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from ..graph_store import GraphStore
from ..lineage.pipeline_drafts import (
    PipelineDraftStore,
    compute_executable_draft_hash,
    validate_draft_for_execution,
)
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import store_upload_bytes, verify_upload
from ..model_terms import (
    ModelTermError,
    dummy_column_name,
    expand_branch_terms,
    polynomial_column_name,
)
from ..predictive_research.contracts import FeatureRecipeV1
from ..reporting import render_html_report
from ..repository.run_repository import _read_artifacts_index
from ..statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    STATA_QUANTILE_METHOD,
    StatisticalExplorationValidationError,
    execute_exploration,
    exploration_fingerprint,
    persist_exploration,
    resolve_statistical_source,
)
from ..services.draft_materialization import create_genesis_draft
from ..services.draft_service import execute_genesis_draft
from .storage import read_jsonl
from .workflow import (
    WorkflowDraft,
    WorkflowExecutionError,
    WorkflowStep,
    WorkflowStepResult,
    _fingerprint,
    _require_server_compiler_receipt,
    _workflow_admission_fingerprint,
    _workflow_contract_fingerprint,
    _workflow_scope_ref,
    _typed_output_bindings,
    _persisted_lineage,
    _binding_body,
    _validated_artifact_ids,
)
from .post_estimation_registry import (
    PostEstimationRegistryError,
    post_estimation_registry,
)
from .workflow_contracts import (
    STEP_REPLAYABLE_BY_RECIPE,
    WORKFLOW_STEP_SPEC_CONTRACTS,
    family_context_columns,
    genesis_run_params,
    model_family_contract,
    workflow_dispatcher_key,
)


_NUMERIC_DERIVATION_SCHEMA = "workflow-derived-numeric.v1"
# Versioned because a consuming step reads this block back from persisted state
# on resume, and because every dataset-producing operation will publish it.
_PRODUCED_DATASET_SCHEMA = "workflow-produced-dataset.v1"

# The artifact types a declared workflow-analysis step can persist. All are
# registered evidence; this is the read side of the same contract.
POST_ESTIMATION_ARTIFACT_TYPES = (
    "post_estimation",
    "statistical_test",
    "p7_analysis",
    "workflow_capability_result",
)

# Some established producers publish a stable artifact ``step`` label rather
# than the workflow dispatcher id.  Keep this translation explicit and small:
# it is part of the evidence contract, not a wildcard that would let an
# arbitrary registered file satisfy completion.
_WORKFLOW_ARTIFACT_STEP_ALIASES: dict[str, frozenset[str]] = {
    "statistical.explore": frozenset(
        {"statistical_exploration", "reporting", "export"}
    ),
    "statistical.derive_boolean": frozenset(
        {
            "statistical_exploration",
            "reporting",
            "export",
            "data.derive.boolean",
        }
    ),
    "statistical.derive_numeric": frozenset({"workflow.derive_numeric"}),
    "statistical.derived_group_summarize": frozenset(
        {"statistical_exploration", "reporting", "export"}
    ),
}

# A product surface renders these inline, so the projection stays bounded
# rather than growing with a project's workflow history.
MAX_PROJECTED_POST_ESTIMATION_RESULTS = 20

_EVIDENCE_LOCK_GUARD = threading.Lock()
_EVIDENCE_LOCKS: dict[str, threading.RLock] = {}
_EVIDENCE_RECEIPT_OWNER = f"workflow-evidence-process:{secrets.token_hex(16)}"
_PROCESS_GENERATION = secrets.token_hex(16)
_EVIDENCE_COMPLETION_SEAL_KEY = secrets.token_bytes(32)
_WRITE_CONTEXT: ContextVar[tuple[Any, ...] | None] = ContextVar(
    "workbench_workflow_write_context", default=None
)
_PENDING_RUNTIME_OUTPUTS: ContextVar[
    dict[str, tuple[Any, bool]] | None
] = ContextVar("workbench_pending_runtime_outputs", default=None)
_ISSUED_EVIDENCE_PORTS: dict[int, Any] = {}
_SUPERVISOR_HOST_ENDPOINTS: dict[int, tuple[Any, ...]] = {}


def _invalidate_inherited_workflow_authority() -> None:
    """Invalidate all parent-owned workflow capabilities in a forked child."""

    global _EVIDENCE_RECEIPT_OWNER, _PROCESS_GENERATION
    _PROCESS_GENERATION = secrets.token_hex(16)
    _EVIDENCE_RECEIPT_OWNER = f"workflow-evidence-process:{secrets.token_hex(16)}"
    _ISSUED_EVIDENCE_PORTS.clear()
    _SUPERVISOR_HOST_ENDPOINTS.clear()
    with _EVIDENCE_LOCK_GUARD:
        _EVIDENCE_LOCKS.clear()
    _WRITE_CONTEXT.set(None)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_invalidate_inherited_workflow_authority)


@dataclass(frozen=True, slots=True)
class WorkflowHostEndpointV1:
    """Deployment-owned workflow evidence endpoint identity.

    This value is deliberately not constructible by a request caller.  The
    deployment adapter must admit it at the explicit supervisor seam below;
    the default resolver remains fail-closed until that adapter is wired.
    """

    project_root: Path
    workflow_evidence_root_fd: int
    owner_pid: int = 0
    process_generation: str = ""
    supervisor_admitted: bool = False

    def __post_init__(self) -> None:
        raise TypeError(
            "WorkflowHostEndpointV1 must be admitted by the deployment supervisor"
        )


def _admit_workflow_host_endpoint_from_supervisor(
    project_root: Path | str,
    workflow_evidence_root_fd: int,
) -> WorkflowHostEndpointV1:
    """Admit an endpoint only at the explicit deployment integration seam.

    The production adapter must call this only after its external supervisor
    has authenticated the inherited directory FD.  The workflow package does
    not invent a default path, accept request metadata, or mint a local token.
    """

    normalized_root = Path(project_root).expanduser().resolve()
    if isinstance(workflow_evidence_root_fd, bool) or not isinstance(
        workflow_evidence_root_fd, int
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: supervisor workflow directory fd is invalid"
        )
    try:
        endpoint_stat = os.fstat(workflow_evidence_root_fd)
    except OSError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: supervisor workflow endpoint is unavailable"
        ) from exc
    if not stat.S_ISDIR(endpoint_stat.st_mode):
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: supervisor workflow endpoint is not a directory"
        )
    endpoint = object.__new__(WorkflowHostEndpointV1)
    object.__setattr__(endpoint, "project_root", normalized_root)
    object.__setattr__(endpoint, "workflow_evidence_root_fd", workflow_evidence_root_fd)
    object.__setattr__(endpoint, "owner_pid", os.getpid())
    object.__setattr__(endpoint, "process_generation", _PROCESS_GENERATION)
    object.__setattr__(endpoint, "supervisor_admitted", True)
    _SUPERVISOR_HOST_ENDPOINTS[id(endpoint)] = (
        endpoint,
        workflow_evidence_root_fd,
        os.getpid(),
        _PROCESS_GENERATION,
        (endpoint_stat.st_dev, endpoint_stat.st_ino),
    )
    return endpoint


def _require_supervisor_host_endpoint(endpoint: object) -> None:
    if type(endpoint) is not WorkflowHostEndpointV1:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment resolver returned an unadmitted workflow endpoint"
        )
    admitted = _SUPERVISOR_HOST_ENDPOINTS.get(id(endpoint))
    if (
        admitted is None
        or admitted[0] is not endpoint
        or endpoint.owner_pid != os.getpid()
        or endpoint.process_generation != _PROCESS_GENERATION
        or endpoint.supervisor_admitted is not True
        or admitted[2] != os.getpid()
        or admitted[3] != _PROCESS_GENERATION
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: workflow endpoint was not admitted by the deployment supervisor"
        )
    try:
        current = os.fstat(endpoint.workflow_evidence_root_fd)
    except OSError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: admitted supervisor endpoint is unavailable"
        ) from exc
    if (current.st_dev, current.st_ino) != admitted[4]:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: admitted supervisor endpoint identity changed"
        )


def _deployment_host_endpoint_from_supervisor(
    _project_root: Path,
) -> WorkflowHostEndpointV1:
    """Resolve host authority from deployment, or fail closed.

    The workflow package does not derive a default endpoint, accept request
    metadata, read caller-selected configuration, or mint a local key.  The
    production host adapter must replace this seam with its supervisor-owned
    resolver.  Package tests patch this private seam only to model that
    external boundary.
    """

    raise WorkflowExecutionError(
        "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: no deployment-owned workflow host resolver is configured"
    )


class _EvidencePathLock:
    """Serialize one workflow's read/decide/write transaction across workers."""

    def __init__(self, path: Path, admitted_directory_fd: int | None = None) -> None:
        self.path = path
        self._admitted_directory_fd = admitted_directory_fd
        self._thread_lock: threading.RLock | None = None
        self._directory_fd: int | None = None

    def __enter__(self):
        key = str(self.path)
        with _EVIDENCE_LOCK_GUARD:
            lock = _EVIDENCE_LOCKS.get(key)
            if lock is None:
                lock = threading.RLock()
                _EVIDENCE_LOCKS[key] = lock
        self._thread_lock = lock
        lock.acquire()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Lock the admitted directory inode, not a pathname-created lock
            # file.  A pathname lock can be replaced between open calls and
            # split two workers into independent lock domains.
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            self._directory_fd = os.open(self.path.parent, directory_flags)
            if self._admitted_directory_fd is not None:
                admitted = os.fstat(self._admitted_directory_fd)
                current = os.fstat(self._directory_fd)
                if (admitted.st_dev, admitted.st_ino) != (current.st_dev, current.st_ino):
                    raise WorkflowExecutionError(
                        "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: host endpoint is not the admitted workflow directory"
                    )
            fcntl.flock(self._directory_fd, fcntl.LOCK_EX)
        except Exception:
            if self._directory_fd is not None:
                os.close(self._directory_fd)
                self._directory_fd = None
            lock.release()
            self._thread_lock = None
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._directory_fd is not None:
            fcntl.flock(self._directory_fd, fcntl.LOCK_UN)
            os.close(self._directory_fd)
            self._directory_fd = None
        if self._thread_lock is not None:
            self._thread_lock.release()
            self._thread_lock = None

    @property
    def directory_fd(self) -> int:
        if self._directory_fd is None:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_LOCK_REQUIRED: workflow directory is not admitted"
            )
        return self._directory_fd


def _evidence_lock(
    path: Path, *, admitted_directory_fd: int | None = None
) -> _EvidencePathLock:
    return _EvidencePathLock(path, admitted_directory_fd=admitted_directory_fd)


def _append_evidence_record(
    path: Path,
    record: Mapping[str, Any],
    *,
    directory_fd: int | None = None,
) -> None:
    """Append evidence while the caller holds the directory inode lock.

    The generic JSONL helper uses a sibling pathname lock.  That is safe for
    ordinary callers but leaves a replacement window for a security-sensitive
    evidence path.  Evidence writes use the already-held directory lock and
    open the target with ``O_NOFOLLOW`` so a replaced file cannot redirect the
    append outside the project.
    """

    if directory_fd is None:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_LOCK_REQUIRED: append requires the admitted directory fd"
        )
    try:
        admitted = os.fstat(directory_fd)
        current = os.stat(path.parent, follow_symlinks=False)
    except OSError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_PATH_CHANGED: admitted workflow directory is unavailable"
        ) from exc
    if (admitted.st_dev, admitted.st_ino) != (current.st_dev, current.st_ino):
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_PATH_CHANGED: workflow directory inode changed"
        )
    line = (
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    file_fd = os.open(path.name, flags, 0o600, dir_fd=directory_fd)
    try:
        view = memoryview(line)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                raise OSError("evidence append made no progress")
            view = view[written:]
        os.fsync(file_fd)
    finally:
        os.close(file_fd)
    os.fsync(directory_fd)


def _completion_seal(record: Mapping[str, Any]) -> str:
    payload = {
        str(key): value
        for key, value in record.items()
        if key != "completion_seal"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hmac.new(_EVIDENCE_COMPLETION_SEAL_KEY, encoded, hashlib.sha256).hexdigest()


def _persisted_admission_fingerprint(record: Mapping[str, Any]) -> str:
    return _fingerprint(
        {
            "workflow_id": record.get("workflow_id"),
            "workflow_template": record.get("workflow_template"),
            "target": record.get("target"),
            "preconditions": record.get("preconditions"),
            "bindings": record.get("bindings"),
            "steps": record.get("plan_steps"),
            "plan_fingerprint": record.get("plan_fingerprint"),
        }
    )


def _snapshot_json(value: Any) -> Any:
    return json.loads(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    )


def _workflow_contract_fingerprint_from_dict(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_WORKFLOW_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_WORKFLOW_ARTIFACT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


def _require_workflow_opaque_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _WORKFLOW_OPAQUE_REF.fullmatch(value):
        raise WorkflowExecutionError(
            f"{field_name} must be a project-local opaque reference"
        )
    return value


def _require_workflow_artifact_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _WORKFLOW_ARTIFACT_REF.fullmatch(value):
        raise WorkflowExecutionError(
            f"{field_name} must be a project-local artifact reference"
        )
    return value


def _digest_matches(value: Any, actual: str) -> bool:
    return value in {actual, f"sha256:{actual}"}


def _artifact_path_without_following(
    project_root: Path,
    run_id: str,
    artifact_path: Path,
) -> tuple[Path, Path]:
    """Return a project-local artifact path after no-follow validation."""

    _require_workflow_opaque_ref(run_id, "workflow artifact run_id")
    run_root = project_root / "runs" / run_id
    try:
        run_stat = os.lstat(run_root)
    except OSError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact run is unavailable"
        ) from exc
    if stat.S_ISLNK(run_stat.st_mode) or not stat.S_ISDIR(run_stat.st_mode):
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact run is not project-owned"
        )
    try:
        relative = artifact_path.relative_to(run_root)
    except ValueError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact path escapes its run"
        ) from exc
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact path escapes its run"
        )
    current = run_root
    for component in relative.parts[:-1]:
        current = current / component
        try:
            component_stat = os.lstat(current)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact parent is unavailable"
            ) from exc
        if stat.S_ISLNK(component_stat.st_mode) or not stat.S_ISDIR(component_stat.st_mode):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact parent is not project-owned"
            )
    try:
        file_stat = os.lstat(artifact_path)
    except OSError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact is unavailable"
        ) from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact is unavailable"
        )
    return run_root, relative


class _FormalOutputTarget:
    """An output target held open in the admitted parent directory."""

    def __init__(
        self,
        *,
        run_root: Path,
        parent_path: Path,
        parent_fd: int,
        root_fd: int,
        parent_identity: tuple[int, int],
        root_identity: tuple[int, int],
        filename: str,
    ) -> None:
        self.run_root = run_root
        self.parent_path = parent_path
        self.parent_fd = parent_fd
        self.root_fd = root_fd
        self.parent_identity = parent_identity
        self.root_identity = root_identity
        self.filename = filename
        self.temp_name: str | None = None
        self.destination_existed = False
        self.destination_identity: tuple[int, int] | None = None
        self.destination_backup_name: str | None = None
        self.destination_backup_identity: tuple[int, int] | None = None
        self.destination_backup_file_identity: tuple[int, int] | None = None
        self.committed = False
        self.closed = False

    @property
    def path(self) -> Path:
        return self.parent_path / self.filename

    def _check_identity(self) -> None:
        try:
            root_stat = os.fstat(self.root_fd)
            current_root = os.stat(self.run_root, follow_symlinks=False)
            parent_stat = os.fstat(self.parent_fd)
            current_parent = os.stat(self.parent_path, follow_symlinks=False)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output parent is unavailable"
            ) from exc
        if (
            (root_stat.st_dev, root_stat.st_ino) != self.root_identity
            or (current_root.st_dev, current_root.st_ino) != self.root_identity
            or (parent_stat.st_dev, parent_stat.st_ino) != self.parent_identity
            or (current_parent.st_dev, current_parent.st_ino) != self.parent_identity
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output path or parent inode changed"
            )

    def _check_destination(self) -> None:
        """Reject a replaced final name before opening a temporary file."""

        try:
            existing = os.stat(
                self.filename,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            self.destination_existed = False
            self.destination_identity = None
            return
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination is unavailable"
            ) from exc
        if stat.S_ISLNK(existing.st_mode):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination is a symlink"
            )
        if not stat.S_ISREG(existing.st_mode):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination is not a file"
            )
        self.destination_existed = True
        self.destination_identity = (existing.st_dev, existing.st_ino)

    def _check_destination_identity(self) -> None:
        """Reject a final-name replacement after the target was admitted."""

        try:
            current = os.stat(
                self.filename,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            if not self.destination_existed and self.destination_identity is None:
                return
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination disappeared"
            ) from exc
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination is unavailable"
            ) from exc
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination was rebound"
            )
        identity = (current.st_dev, current.st_ino)
        if self.destination_identity is None or identity != self.destination_identity:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination was rebound"
            )

    def open_binary(self):
        self._check_identity()
        self._check_destination()
        self.temp_name = (
            f".{self.filename}.{secrets.token_hex(12)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.temp_name, flags, 0o600, dir_fd=self.parent_fd)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output temporary file could not be opened safely"
            ) from exc
        return os.fdopen(fd, "wb")

    def read_bytes(self) -> bytes | None:
        """Read an existing destination through the admitted parent FD."""

        self._check_identity()
        self._check_destination()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.filename, flags, dir_fd=self.parent_fd)
        except FileNotFoundError:
            if self.destination_existed:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination disappeared"
                )
            return None
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination cannot be read safely"
            ) from exc
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination is not a file"
                )
            if self.destination_identity != (file_stat.st_dev, file_stat.st_ino):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination was rebound"
                )
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                content = stream.read()
            self._check_destination_identity()
            return content
        finally:
            if fd != -1:
                os.close(fd)

    def write_bytes(self, content: bytes) -> Path:
        """Write and commit bytes without reopening a destination pathname."""

        with self.open_binary() as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return self.commit()

    def _create_destination_backup(self) -> None:
        """Snapshot an existing destination before replacing it."""

        if not self.destination_existed:
            return
        if self.destination_identity is None:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: existing formal output identity is missing"
            )
        backup_name = f".{self.filename}.{secrets.token_hex(12)}.bak"
        temp_name = f".{self.filename}.{secrets.token_hex(12)}.bak.tmp"
        source_fd: int | None = None
        backup_fd: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            source_fd = os.open(self.filename, flags, dir_fd=self.parent_fd)
            source_before = os.fstat(source_fd)
            source_before_identity = (source_before.st_dev, source_before.st_ino)
            if source_before_identity != self.destination_identity:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: existing formal output was rebound before backup"
                )
            temp_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            backup_fd = os.open(temp_name, temp_flags, 0o600, dir_fd=self.parent_fd)
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(backup_fd, view)
                    view = view[written:]
            os.fsync(backup_fd)
            source_after = os.fstat(source_fd)
            if (
                (source_after.st_dev, source_after.st_ino) != source_before_identity
                or source_after.st_size != source_before.st_size
                or source_after.st_mtime_ns != source_before.st_mtime_ns
                or source_after.st_ctime_ns != source_before.st_ctime_ns
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: existing formal output changed during backup"
                )
            os.close(source_fd)
            source_fd = None
            os.close(backup_fd)
            backup_fd = None
            os.replace(
                temp_name,
                backup_name,
                src_dir_fd=self.parent_fd,
                dst_dir_fd=self.parent_fd,
            )
            backup_stat = os.stat(
                backup_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(backup_stat.st_mode):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup is not a regular file"
                )
            self.destination_backup_name = backup_name
            self.destination_backup_identity = self.destination_identity
            self.destination_backup_file_identity = (
                backup_stat.st_dev,
                backup_stat.st_ino,
            )
        except WorkflowExecutionError:
            raise
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: existing formal output cannot be backed up safely"
            ) from exc
        finally:
            if source_fd is not None:
                try:
                    os.close(source_fd)
                except OSError:
                    pass
            if backup_fd is not None:
                try:
                    os.close(backup_fd)
                except OSError:
                    pass
            try:
                os.unlink(temp_name, dir_fd=self.parent_fd)
            except OSError:
                pass

    def commit(self) -> Path:
        if self.temp_name is None:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output was not opened"
            )
        self._check_identity()
        self._check_destination_identity()
        try:
            if self.destination_existed:
                self._create_destination_backup()
            os.replace(
                self.temp_name,
                self.filename,
                src_dir_fd=self.parent_fd,
                dst_dir_fd=self.parent_fd,
            )
            # A directory FD remains usable after a rename. Rechecking only
            # before os.replace therefore leaves a small race in which the
            # admitted parent can be moved outside the run immediately before
            # commit. Revalidate after the syscall and roll back a newly
            # created destination through the same FD if the path was rebound.
            self.temp_name = None
            destination_stat = os.stat(
                self.filename,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            self.destination_identity = (
                destination_stat.st_dev,
                destination_stat.st_ino,
            )
            self.committed = True
            try:
                self._check_identity()
            except WorkflowExecutionError:
                self.rollback_committed()
                raise
            os.fsync(self.parent_fd)
        except WorkflowExecutionError:
            if self.temp_name is not None:
                self.abort()
            if self.destination_backup_name is not None:
                self.rollback_committed()
            raise
        except OSError as exc:
            if self.temp_name is not None:
                self.abort()
            if self.destination_backup_name is not None:
                self.rollback_committed()
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output commit failed closed"
            ) from exc
        return self.path

    def rollback_committed(self) -> None:
        """Undo this target without following a rebound final pathname."""

        backup_name = self.destination_backup_name
        try:
            current = os.stat(
                self.filename,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            current_identity = (current.st_dev, current.st_ino)
        except FileNotFoundError:
            current_identity = None
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output rollback identity cannot be checked"
            ) from exc
        if backup_name is not None:
            original_identity = self.destination_backup_identity
            try:
                backup_stat = os.stat(
                    backup_name,
                    dir_fd=self.parent_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(backup_stat.st_mode)
                    or self.destination_backup_file_identity
                    != (backup_stat.st_dev, backup_stat.st_ino)
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup was rebound"
                    )
            except FileNotFoundError as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup disappeared"
                ) from exc
            if current_identity == original_identity and not self.committed:
                try:
                    os.unlink(backup_name, dir_fd=self.parent_fd)
                    os.fsync(self.parent_fd)
                except OSError as exc:
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup cleanup failed"
                    ) from exc
                self.destination_backup_name = None
                self.destination_backup_identity = None
                self.destination_backup_file_identity = None
                return
            if current_identity not in {None, self.destination_identity}:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination was rebound before rollback"
                )
            try:
                if current_identity == self.destination_identity:
                    os.unlink(self.filename, dir_fd=self.parent_fd)
                os.replace(
                    backup_name,
                    self.filename,
                    src_dir_fd=self.parent_fd,
                    dst_dir_fd=self.parent_fd,
                )
                os.fsync(self.parent_fd)
                self.destination_identity = original_identity
                self.destination_backup_name = None
                self.destination_backup_identity = None
                self.destination_backup_file_identity = None
                self.committed = False
            except OSError as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output rollback failed"
                ) from exc
            return
        if self.destination_existed or self.destination_identity is None:
            return
        if current_identity is None:
            self.committed = False
            self.destination_identity = None
            return
        if current_identity != self.destination_identity:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination was rebound before cleanup"
            )
        if current_identity == self.destination_identity:
            try:
                os.unlink(self.filename, dir_fd=self.parent_fd)
                os.fsync(self.parent_fd)
            except OSError as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output cleanup failed"
                ) from exc
            self.committed = False
            self.destination_identity = None

    def finalize_committed(self) -> None:
        """Discard a preserved original after the evidence transaction succeeds."""

        if self.destination_backup_name is None:
            self.committed = False
            return
        try:
            self._check_identity()
            backup_stat = os.stat(
                self.destination_backup_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(backup_stat.st_mode)
                or self.destination_backup_file_identity
                != (backup_stat.st_dev, backup_stat.st_ino)
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup was rebound"
                )
            os.unlink(self.destination_backup_name, dir_fd=self.parent_fd)
            os.fsync(self.parent_fd)
        except FileNotFoundError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup disappeared"
            ) from exc
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output backup cleanup failed"
            ) from exc
        self.destination_backup_name = None
        self.destination_backup_identity = None
        self.destination_backup_file_identity = None
        self.committed = False

    def abort(self) -> None:
        if self.temp_name is not None:
            try:
                os.unlink(self.temp_name, dir_fd=self.parent_fd)
            except OSError:
                pass
            self.temp_name = None

    def close(self) -> None:
        if self.closed:
            return
        self.abort()
        for fd in (self.parent_fd, self.root_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        self.closed = True


def prepare_formal_workflow_output(
    evidence_port: Any,
    admission_receipt: Any,
    *,
    run_root: Path,
    directory_name: str,
    filename: str,
) -> _FormalOutputTarget:
    """Validate receipt, root and every output parent before opening a file."""

    context = _require_active_write_context()
    if evidence_port is None and admission_receipt is None:
        evidence_port = context[0]
        admission_receipt = context[1]
    if (
        context[0] is not evidence_port
        or context[1] is not admission_receipt
        or type(evidence_port) is not EvidencePersistencePort
        or type(admission_receipt) is not WorkflowAdmissionReceipt
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: formal output requires the active server receipt"
        )
    evidence_port.require_receipt(admission_receipt)
    draft = context[2]
    run_id = _require_workflow_opaque_ref(
        draft.target.get("run_id"), "workflow target run_id"
    )
    expected_root = evidence_port.project_root / "runs" / run_id
    if Path(run_root) != expected_root:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output root is not the admitted target run"
        )
    directory = Path(directory_name) if isinstance(directory_name, str) else Path()
    directory_parts = () if directory == Path(".") else directory.parts
    if (
        not isinstance(directory_name, str)
        or not directory_name
        or directory.is_absolute()
        or any(component in {".", ".."} for component in directory_parts)
        or any("\x00" in component for component in directory_parts)
        or not isinstance(filename, str)
        or not filename
        or Path(filename).name != filename
        or filename in {".", ".."}
        or "\x00" in filename
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output path is invalid"
        )
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    runs_fd: int | None = None
    try:
        runs_fd = os.open(evidence_port.project_root / "runs", root_flags)
        root_fd = os.open(run_id, root_flags, dir_fd=runs_fd)
    except OSError as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output run cannot be admitted"
        ) from exc
    finally:
        if runs_fd is not None:
            os.close(runs_fd)
    try:
        root_stat = os.fstat(root_fd)
    except OSError as exc:
        os.close(root_fd)
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output run is unavailable"
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        os.close(root_fd)
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output run is not project-owned"
        )
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    parent_path = expected_root
    parent_fd: int | None = None
    try:
        parent_fd = os.dup(root_fd)
        for component in directory_parts:
            parent_path = parent_path / component
            try:
                child_fd = os.open(component, root_flags, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(component, root_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child_fd
        parent_stat = os.fstat(parent_fd)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output parent is not project-owned"
            )
        parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        target = _FormalOutputTarget(
            run_root=expected_root,
            parent_path=parent_path,
            parent_fd=parent_fd,
            root_fd=root_fd,
            parent_identity=parent_identity,
            root_identity=root_identity,
            filename=filename,
        )
        target._check_identity()
        return target
    except OSError as exc:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass
        try:
            os.close(root_fd)
        except OSError:
            pass
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output parent cannot be admitted"
        ) from exc
    except Exception:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass
        try:
            os.close(root_fd)
        except OSError:
            pass
        raise


def record_formal_workflow_artifact(
    evidence_port: Any,
    admission_receipt: Any,
    *,
    run_root: Path,
    artifact_id: str,
    path: Path,
    artifact_type: str = "formal_output",
    producer_step: str = "formal_output",
    inputs: Iterable[str] = (),
    output_target: Any | None = None,
) -> None:
    """Bridge a formal writer to the port-owned artifact registry."""

    context = _require_active_write_context()
    if evidence_port is None and admission_receipt is None:
        evidence_port = context[0]
        admission_receipt = context[1]
    if type(evidence_port) is not EvidencePersistencePort:
        raise WorkflowExecutionError(
            "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: formal artifact requires the server evidence port"
        )
    evidence_port.record_formal_artifact(
        evidence_port,
        admission_receipt,
        run_root=run_root,
        artifact_id=artifact_id,
        path=path,
        artifact_type=artifact_type,
        producer_step=producer_step,
        inputs=inputs,
        output_target=output_target,
    )


def _write_runtime_artifact_bytes(
    run_root: Path,
    relative_path: Path,
    content: bytes,
    *,
    occupied_message: str,
    retain_for_registry: bool = False,
) -> Path:
    """Persist a workflow-owned artifact only through an admitted FD target."""

    if relative_path.is_absolute() or not relative_path.parts:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: runtime artifact path is invalid"
        )
    output = prepare_formal_workflow_output(
        None,
        None,
        run_root=run_root,
        directory_name=relative_path.parent.as_posix()
        if relative_path.parent != Path(".")
        else ".",
        filename=relative_path.name,
    )
    try:
        existing = output.read_bytes()
        if existing is not None:
            if existing != content:
                raise WorkflowExecutionError(occupied_message)
        else:
            output.write_bytes(content)
        if retain_for_registry:
            pending = _PENDING_RUNTIME_OUTPUTS.get()
            if pending is None:
                pending = {}
                _PENDING_RUNTIME_OUTPUTS.set(pending)
            previous = pending.get(str(output.path))
            if previous is not None and previous[0] is not output:
                previous[0].rollback_committed()
                previous[0].close()
            pending[str(output.path)] = (output, output.destination_existed)
            return output.path
        output.finalize_committed()
        return output.path
    except Exception:
        output.abort()
        raise
    finally:
        if not retain_for_registry or str(output.path) not in (_PENDING_RUNTIME_OUTPUTS.get() or {}):
            output.close()


def _write_runtime_artifact_json(
    run_root: Path,
    relative_path: Path,
    payload: Any,
    *,
    occupied_message: str,
    retain_for_registry: bool = False,
) -> Path:
    """Persist JSON while comparing existing content without following links."""

    if relative_path.is_absolute() or not relative_path.parts:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: runtime artifact path is invalid"
        )
    output = prepare_formal_workflow_output(
        None,
        None,
        run_root=run_root,
        directory_name=relative_path.parent.as_posix()
        if relative_path.parent != Path(".")
        else ".",
        filename=relative_path.name,
    )
    serialized = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    try:
        existing = output.read_bytes()
        if existing is not None:
            try:
                existing_payload = json.loads(existing.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkflowExecutionError(occupied_message) from exc
            if existing_payload != payload:
                raise WorkflowExecutionError(occupied_message)
        else:
            output.write_bytes(serialized)
        if retain_for_registry:
            pending = _PENDING_RUNTIME_OUTPUTS.get()
            if pending is None:
                pending = {}
                _PENDING_RUNTIME_OUTPUTS.set(pending)
            previous = pending.get(str(output.path))
            if previous is not None and previous[0] is not output:
                previous[0].rollback_committed()
                previous[0].close()
            pending[str(output.path)] = (output, output.destination_existed)
            return output.path
        output.finalize_committed()
        return output.path
    except Exception:
        output.abort()
        raise
    finally:
        if not retain_for_registry or str(output.path) not in (_PENDING_RUNTIME_OUTPUTS.get() or {}):
            output.close()


def _read_runtime_artifact_json(
    run_root: Path,
    relative_path: Path,
    *,
    missing: Any = None,
) -> Any:
    """Read JSON through the same admitted, no-follow output boundary."""

    output = prepare_formal_workflow_output(
        None,
        None,
        run_root=run_root,
        directory_name=relative_path.parent.as_posix()
        if relative_path.parent != Path(".")
        else ".",
        filename=relative_path.name,
    )
    try:
        existing = output.read_bytes()
        if existing is None:
            return missing
        try:
            return json.loads(existing.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: runtime artifact JSON is unreadable"
            ) from exc
    finally:
        output.close()


@dataclass(frozen=True)
class WorkflowAdmissionReceipt:
    """Server-owned, one-step admission capability."""

    workflow_id: str
    step_id: str
    plan_fingerprint: str
    step_fingerprint: str
    scope_ref: str
    contract_fingerprint: str
    receipt_id: str
    attempt: int
    completed_result: WorkflowStepResult | None = None
    target_fingerprint: str = ""
    admission_fingerprint: str = ""
    receipt_owner: str = ""
    owner_pid: int = 0
    process_generation: str = ""


class EvidencePersistencePort:
    """The only workflow runtime port for admission and evidence completion.

    It owns a path-safe, append-only record under the workflow directory.  A
    step is admitted before its executor is called; an active admission cannot
    be replayed, while an identical completion is idempotent.
    """

    def __init__(self, project_root: Path | str) -> None:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: EvidencePersistencePort "
            "requires a real host workflow evidence endpoint"
        )

    def _initialize_from_host_endpoint(
        self, project_root: Path | str, host_endpoint: WorkflowHostEndpointV1
    ) -> None:
        normalized_root = Path(project_root).expanduser().resolve()
        if type(host_endpoint) is not WorkflowHostEndpointV1:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment resolver returned invalid workflow host input"
            )
        endpoint_root = host_endpoint.project_root
        endpoint_fd = host_endpoint.workflow_evidence_root_fd
        if isinstance(endpoint_fd, bool) or not isinstance(endpoint_fd, int):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment host must supply the workflow evidence directory fd"
            )
        try:
            if Path(endpoint_root).expanduser().resolve() != normalized_root:
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment host project binding changed"
                )
            endpoint_stat = os.fstat(endpoint_fd)
            if not stat.S_ISDIR(endpoint_stat.st_mode):
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment workflow evidence endpoint is not a directory"
                )
            owned_fd = os.dup(endpoint_fd)
        except (OSError, TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment workflow evidence endpoint is unavailable"
            ) from exc
        self.project_root = normalized_root
        self._host_endpoint_fd = owned_fd
        self._host_endpoint_identity = (endpoint_stat.st_dev, endpoint_stat.st_ino)
        self._owner_pid = os.getpid()
        self._process_generation = _PROCESS_GENERATION
        self._issued_receipts: dict[
            int, tuple[WorkflowAdmissionReceipt, tuple[Any, ...]]
        ] = {}
        self._server_artifact_registry: dict[
            tuple[str, str, str], dict[str, Any]
        ] = {}

    def _require_server_host(self) -> None:
        if (
            getattr(self, "_owner_pid", None) != os.getpid()
            or getattr(self, "_process_generation", None) != _PROCESS_GENERATION
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_PROCESS_BOUNDARY: workflow authority belongs to another process generation"
            )
        if _ISSUED_EVIDENCE_PORTS.get(id(self)) is not self:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: evidence port was not issued by the host endpoint factory"
            )
        endpoint_fd = getattr(self, "_host_endpoint_fd", None)
        expected_directory = self.project_root / "workbench" / "workflows"
        try:
            endpoint_stat = os.fstat(endpoint_fd)
            current_stat = os.stat(expected_directory, follow_symlinks=False)
        except (OSError, TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: real host workflow evidence endpoint is not wired"
            ) from exc
        if (
            not stat.S_ISDIR(endpoint_stat.st_mode)
            or not stat.S_ISDIR(current_stat.st_mode)
            or (endpoint_stat.st_dev, endpoint_stat.st_ino)
            != (current_stat.st_dev, current_stat.st_ino)
            or (endpoint_stat.st_dev, endpoint_stat.st_ino)
            != getattr(self, "_host_endpoint_identity", None)
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: real host endpoint is not the current workflow evidence directory"
            )

    def __getstate__(self):
        raise TypeError("EvidencePersistencePort is a process-local server capability")

    def __reduce__(self):
        raise TypeError("EvidencePersistencePort cannot be serialized")

    def close(self) -> None:
        if _ISSUED_EVIDENCE_PORTS.get(id(self)) is self:
            _ISSUED_EVIDENCE_PORTS.pop(id(self), None)
        endpoint_fd = getattr(self, "_host_endpoint_fd", None)
        if isinstance(endpoint_fd, int):
            self._host_endpoint_fd = None
            try:
                os.close(endpoint_fd)
            except OSError:
                pass

    def __del__(self):
        self.close()

    def _path(self, workflow_id: str) -> Path:
        if not workflow_id or Path(workflow_id).name != workflow_id:
            raise WorkflowExecutionError("workflow evidence workflow_id is not path-safe")
        return self.project_root / "workbench" / "workflows" / f"{workflow_id}.evidence.jsonl"

    @staticmethod
    def _scope_ref(draft: WorkflowDraft) -> str:
        return _workflow_scope_ref(draft.target, draft.preconditions)

    @staticmethod
    def _contract_fingerprint(step: WorkflowStep) -> str:
        return _workflow_contract_fingerprint(step)

    def _require_server_draft(self, draft: WorkflowDraft) -> str:
        self._require_server_host()
        _require_server_compiler_receipt(draft)
        return self._scope_ref(draft)

    def require_server_draft(self, draft: WorkflowDraft) -> str:
        """Validate compiler authority before any workflow state side effect."""

        return self._require_server_draft(draft)

    def _register_receipt(self, receipt: WorkflowAdmissionReceipt) -> None:
        self._issued_receipts[id(receipt)] = (receipt, self._receipt_snapshot(receipt))

    @staticmethod
    def _receipt_snapshot(receipt: WorkflowAdmissionReceipt) -> tuple[Any, ...]:
        return (
            receipt.workflow_id,
            receipt.step_id,
            receipt.plan_fingerprint,
            receipt.step_fingerprint,
            receipt.scope_ref,
            receipt.contract_fingerprint,
            receipt.receipt_id,
            receipt.attempt,
            receipt.completed_result,
            receipt.target_fingerprint,
            receipt.admission_fingerprint,
            receipt.receipt_owner,
            receipt.owner_pid,
            receipt.process_generation,
        )

    def _require_receipt(self, receipt: WorkflowAdmissionReceipt) -> None:
        self._require_server_host()
        if type(receipt) is not WorkflowAdmissionReceipt:
            raise WorkflowExecutionError(
                "WORKFLOW_RECEIPT_AUTHORITY_REQUIRED: a server-issued workflow receipt is required"
            )
        issued = self._issued_receipts.get(id(receipt))
        if (
            issued is None
            or issued[0] is not receipt
            or issued[1] != self._receipt_snapshot(receipt)
            or receipt.receipt_owner != _EVIDENCE_RECEIPT_OWNER
            or receipt.owner_pid != getattr(self, "_owner_pid", None)
            or receipt.process_generation != getattr(self, "_process_generation", None)
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_RECEIPT_AUTHORITY_REQUIRED: receipt was not issued by this EvidencePersistencePort"
            )

    def require_receipt(self, receipt: WorkflowAdmissionReceipt) -> None:
        self._require_receipt(receipt)

    def require_server_host(self) -> None:
        self._require_server_host()

    def _records(self, workflow_id: str) -> list[dict[str, Any]]:
        try:
            return read_jsonl(self._path(workflow_id))
        except (OSError, TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: workflow evidence history is unreadable"
            ) from exc

    @staticmethod
    def _read_file_snapshot(path: Path) -> tuple[str, tuple[int, int]]:
        """Hash and identify one regular file through an O_NOFOLLOW FD."""

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(path, flags)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: admitted artifact is unavailable"
            ) from exc
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: admitted artifact is not a regular file"
                )
            digest = hashlib.sha256()
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest(), (file_stat.st_dev, file_stat.st_ino)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: admitted artifact cannot be read"
            ) from exc
        finally:
            os.close(file_fd)

    @staticmethod
    def _read_file_snapshot_from_target(
        output_target: _FormalOutputTarget,
    ) -> tuple[str, tuple[int, int]]:
        """Read a formal output through the held parent FD, never its pathname."""

        output_target._check_identity()
        if output_target.destination_identity is None:
            output_target._check_destination()
        output_target._check_destination_identity()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(
                output_target.filename,
                flags,
                dir_fd=output_target.parent_fd,
            )
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal output is unavailable"
            ) from exc
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal output is not a regular file"
                )
            initial_signature = (
                file_stat.st_dev,
                file_stat.st_ino,
                file_stat.st_size,
                file_stat.st_mtime_ns,
                file_stat.st_ctime_ns,
            )
            if output_target.destination_identity != (
                file_stat.st_dev,
                file_stat.st_ino,
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output destination was rebound"
                )
            digest = hashlib.sha256()
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            final_stat = os.fstat(file_fd)
            final_signature = (
                final_stat.st_dev,
                final_stat.st_ino,
                final_stat.st_size,
                final_stat.st_mtime_ns,
                final_stat.st_ctime_ns,
            )
            if final_signature != initial_signature:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal output changed while it was being admitted"
                )
            identity = (final_stat.st_dev, final_stat.st_ino)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal output cannot be read"
            ) from exc
        finally:
            os.close(file_fd)
        output_target._check_identity()
        output_target._check_destination_identity()
        return digest.hexdigest(), identity

    def _admit_server_artifact(
        self,
        receipt: WorkflowAdmissionReceipt,
        *,
        run_id: str,
        artifact_id: str,
        path: Path,
        artifact_type: str,
        producer_step: str,
        inputs: Iterable[str] = (),
        provenance: Mapping[str, Any] | None = None,
        expected_artifacts: Iterable[str] = (),
        output_target: _FormalOutputTarget | None = None,
    ) -> None:
        """Freeze one artifact only from an active server-owned producer."""

        self._require_receipt(receipt)
        context = _WRITE_CONTEXT.get()
        if (
            context is None
            or len(context) != 4
            or context[0] is not self
            or context[1] is not receipt
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: artifact admission is not bound to the active workflow receipt"
            )
        _evidence_port, _active_receipt, draft, step = context
        _require_workflow_opaque_ref(run_id, "workflow artifact run_id")
        _require_workflow_artifact_ref(artifact_id, "workflow artifact_id")
        run_root, relative = _artifact_path_without_following(
            self.project_root, run_id, Path(path)
        )
        if output_target is not None:
            if type(output_target) is not _FormalOutputTarget or Path(path) != output_target.path:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_PATH_CHANGED: formal output target does not match the admitted artifact"
                )
            digest, file_identity = self._read_file_snapshot_from_target(output_target)
        else:
            digest, file_identity = self._read_file_snapshot(Path(path))
        target_run_id = _require_workflow_opaque_ref(
            draft.target.get("run_id"), "workflow target run_id"
        )
        row = {
            "receipt_id": receipt.receipt_id,
            "workflow_id": receipt.workflow_id,
            "workflow_step_id": receipt.step_id,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "path": relative.as_posix(),
            "content_sha256": digest,
            "file_identity": [int(file_identity[0]), int(file_identity[1])],
            "artifact_type": str(artifact_type),
            "producer_step": str(producer_step),
            "producer_operation_id": str(step.operation_id),
            "inputs": [str(item) for item in inputs],
            "expected_outputs": [str(item) for item in expected_artifacts if str(item)],
            "target_run_id": target_run_id,
            "producer": {
                "workflow_id": receipt.workflow_id,
                "step_id": receipt.step_id,
                "operation_id": str(step.operation_id),
            },
        }
        if provenance is not None:
            row["provenance"] = _snapshot_json(dict(provenance))
        if output_target is not None:
            output_target._check_destination_identity()
        key = (receipt.receipt_id, run_id, artifact_id)
        existing = self._server_artifact_registry.get(key)
        if existing is not None and existing != row:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: immutable server artifact admission changed"
            )
        self._server_artifact_registry[key] = row

    @staticmethod
    def _read_artifact_index_from_fd(
        root_fd: int,
    ) -> tuple[dict[str, Any], bytes | None, tuple[int, int] | None]:
        """Read the public index through the admitted run-root FD."""

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            index_fd = os.open("artifacts_index.json", flags, dir_fd=root_fd)
        except FileNotFoundError:
            return {"schema_version": 1, "artifacts": []}, None, None
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry is unavailable"
            ) from exc
        chunks: list[bytes] = []
        try:
            file_stat = os.fstat(index_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry is not a regular file"
                )
            while True:
                chunk = os.read(index_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry cannot be read"
            ) from exc
        finally:
            os.close(index_fd)
        raw = b"".join(chunks)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry is malformed"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry is malformed"
            )
        return payload, raw, (file_stat.st_dev, file_stat.st_ino)

    @staticmethod
    def _write_artifact_index_bytes(root_fd: int, content: bytes) -> tuple[int, int]:
        """Durably replace the index relative to the held run-root FD."""

        temp_name = f".artifacts_index.{secrets.token_hex(12)}.tmp"
        temp_fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            temp_fd = os.open(temp_name, flags, 0o600, dir_fd=root_fd)
            with os.fdopen(temp_fd, "wb") as stream:
                temp_fd = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(
                temp_name,
                "artifacts_index.json",
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            identity = os.stat(
                "artifacts_index.json",
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            os.fsync(root_fd)
            return identity.st_dev, identity.st_ino
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry cannot be committed safely"
            ) from exc
        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
            try:
                os.unlink(temp_name, dir_fd=root_fd)
            except OSError:
                pass

    @staticmethod
    def _restore_artifact_index(
        root_fd: int,
        previous: bytes | None,
        written_identity: tuple[int, int] | None,
    ) -> None:
        """Restore only the index object written by this transaction."""

        if written_identity is None:
            return
        try:
            current = os.stat(
                "artifacts_index.json",
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            if (current.st_dev, current.st_ino) != written_identity:
                return
            if previous is None:
                os.unlink("artifacts_index.json", dir_fd=root_fd)
                os.fsync(root_fd)
            else:
                EvidencePersistencePort._write_artifact_index_bytes(root_fd, previous)
        except OSError:
            return

    def _publish_formal_artifact_index(
        self,
        output_target: _FormalOutputTarget,
        row: Mapping[str, Any],
    ) -> None:
        """Publish one index row while the output target and root FD are held."""

        output_target._check_identity()
        artifact_id = _require_workflow_artifact_ref(
            row.get("artifact_id"), "formal artifact_id"
        )
        public_record = {
            "artifact_id": artifact_id,
            "path": str(row["path"]),
            "artifact_type": str(row["artifact_type"]),
            "step": str(row["producer_step"]),
            "sha256": str(row["content_sha256"]),
            "inputs": [str(item) for item in row.get("inputs", [])],
            "config_hash": "",
            "code_version": __version__,
        }
        previous: bytes | None = None
        previous_identity: tuple[int, int] | None = None
        written_identity: tuple[int, int] | None = None
        try:
            fcntl.flock(output_target.root_fd, fcntl.LOCK_EX)
            output_target._check_identity()
            index, previous, previous_identity = self._read_artifact_index_from_fd(
                output_target.root_fd
            )
            matches = [
                item
                for item in index["artifacts"]
                if isinstance(item, Mapping) and item.get("artifact_id") == artifact_id
            ]
            if len(matches) > 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal artifact identity is duplicated"
                )
            if matches:
                if dict(matches[0]) != public_record:
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal artifact identity is inconsistent"
                    )
                output_target._check_identity()
                return
            try:
                current_index = os.stat(
                    "artifacts_index.json",
                    dir_fd=output_target.root_fd,
                    follow_symlinks=False,
                )
                current_identity = (current_index.st_dev, current_index.st_ino)
            except FileNotFoundError:
                current_identity = None
            except OSError as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry changed concurrently"
                ) from exc
            if current_identity != previous_identity:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry changed concurrently"
                )
            index["artifacts"].append(public_record)
            encoded = json.dumps(index, indent=2, ensure_ascii=False).encode("utf-8")
            output_target._check_identity()
            written_identity = self._write_artifact_index_bytes(
                output_target.root_fd, encoded
            )
            output_target._check_identity()
        except Exception:
            self._restore_artifact_index(
                output_target.root_fd, previous, written_identity
            )
            raise
        finally:
            try:
                fcntl.flock(output_target.root_fd, fcntl.LOCK_UN)
            except OSError:
                pass

    def _validate_server_artifact_snapshot(
        self, row: Mapping[str, Any], *, receipt: WorkflowAdmissionReceipt
    ) -> tuple[Path, str]:
        """Validate the frozen server row without consulting the public index."""

        if (
            row.get("receipt_id") != receipt.receipt_id
            or row.get("workflow_id") != receipt.workflow_id
            or row.get("workflow_step_id") != receipt.step_id
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: server artifact admission is bound to another workflow step"
            )
        run_id = _require_workflow_opaque_ref(row.get("run_id"), "server artifact run_id")
        relative_value = row.get("path")
        if not isinstance(relative_value, str) or not relative_value:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: server artifact path is invalid"
            )
        relative = Path(relative_value)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: server artifact path escapes its run"
            )
        run_root = self.project_root / "runs" / run_id
        _artifact_path_without_following(self.project_root, run_id, run_root / relative)
        path = run_root / relative
        digest, file_identity = self._read_file_snapshot(path)
        expected_identity = row.get("file_identity")
        if (
            not isinstance(expected_identity, list)
            or len(expected_identity) != 2
            or [int(file_identity[0]), int(file_identity[1])] != expected_identity
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: admitted artifact path was rebound"
            )
        if row.get("content_sha256") != digest:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: admitted artifact content digest changed"
            )
        return path, digest

    def _artifact_index_record(
        self,
        run_id: str,
        artifact_id: str,
    ) -> tuple[dict[str, Any], Path]:
        """Read one index row only as metadata for a server admission.

        The public index is not itself authority.  The caller must reach this
        method from an admitted write context; the resulting row is then
        copied into the port-owned registry with the current receipt binding.
        """

        _require_workflow_opaque_ref(run_id, "workflow artifact run_id")
        artifact_id = _require_workflow_artifact_ref(
            artifact_id, "workflow artifact_id"
        )
        run_root = self.project_root / "runs" / run_id
        try:
            index = _read_artifacts_index(run_root)
        except (OSError, TypeError, ValueError, WorkbenchAPIError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: project artifact registry is unavailable"
            ) from exc
        matching = [
            item
            for item in index.get("artifacts", [])
            if isinstance(item, Mapping) and item.get("artifact_id") == artifact_id
        ]
        if len(matching) != 1:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact is not uniquely registered"
            )
        record = dict(matching[0])
        relative_path = record.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact path is invalid"
            )
        path = run_root / relative_path
        _artifact_path_without_following(self.project_root, run_id, path)
        actual_sha256, file_identity = self._read_file_snapshot(path)
        if not _digest_matches(record.get("sha256"), actual_sha256):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: registered artifact digest changed"
            )
        return record, path

    def _record_server_artifact(
        self,
        receipt: WorkflowAdmissionReceipt,
        *,
        run_id: str,
        artifact_id: str,
        record: Mapping[str, Any],
        path: Path,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        """Record an artifact admitted by this server-owned execution."""

        self._require_receipt(receipt)
        run_root, relative = _artifact_path_without_following(
            self.project_root, run_id, path
        )
        actual_sha256, file_identity = self._read_file_snapshot(path)
        if not _digest_matches(record.get("sha256"), actual_sha256):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: server artifact digest changed"
            )
        row = {
            "receipt_id": receipt.receipt_id,
            "workflow_id": receipt.workflow_id,
            "workflow_step_id": receipt.step_id,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "path": relative.as_posix(),
            "content_sha256": actual_sha256,
            "file_identity": [int(file_identity[0]), int(file_identity[1])],
            "artifact_type": record.get("artifact_type"),
            "producer_step": record.get("step"),
            "producer_operation_id": record.get("step"),
            "inputs": [str(item) for item in record.get("inputs", []) or []],
            "expected_outputs": [],
        }
        if provenance:
            row["provenance"] = _snapshot_json(dict(provenance))
        key = (receipt.receipt_id, run_id, artifact_id)
        existing = self._server_artifact_registry.get(key)
        if existing is not None and existing != row:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: server artifact admission changed"
            )
        self._server_artifact_registry[key] = row

    def admit_result_artifacts(
        self,
        receipt: WorkflowAdmissionReceipt,
        result: WorkflowStepResult,
    ) -> None:
        """Admit result artifacts after a receipt-gated producer returns."""

        self._require_receipt(receipt)
        if type(result) is not WorkflowStepResult:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_RESULT_REQUIRED: result artifact admission requires a typed step result"
            )
        context = _WRITE_CONTEXT.get()
        if (
            context is None
            or len(context) != 4
            or context[0] is not self
            or context[1] is not receipt
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: artifact admission is not bound to the active workflow receipt"
            )
        _evidence_port, _active_receipt, draft, step = context
        target_run_id = _require_workflow_opaque_ref(
            draft.target.get("run_id"), "workflow target run_id"
        )
        raw_branches = result.lineage.get("branches") if isinstance(result.lineage, Mapping) else None
        branches: dict[tuple[str, str], Mapping[str, Any]] = {}
        if isinstance(raw_branches, list):
            for branch in raw_branches:
                if not isinstance(branch, Mapping):
                    continue
                branch_run_id = branch.get("run_id")
                if not isinstance(branch_run_id, str):
                    continue
                for branch_artifact_id in branch.get("artifact_ids", []) or []:
                    if isinstance(branch_artifact_id, str):
                        branches[(branch_run_id, branch_artifact_id)] = branch

        for raw_artifact_id in _validated_artifact_ids(result.artifact_ids):
            if raw_artifact_id.count(":") > 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact identity is not an opaque reference"
                )
            if ":" in raw_artifact_id:
                run_id, artifact_id = raw_artifact_id.split(":", 1)
            else:
                run_id, artifact_id = target_run_id, raw_artifact_id
            _require_workflow_opaque_ref(run_id, "workflow artifact run_id")
            _require_workflow_artifact_ref(artifact_id, "workflow artifact_id")
            branch = branches.get((run_id, artifact_id))
            server_record = self._server_artifact_registry.get(
                (receipt.receipt_id, run_id, artifact_id)
            )
            if server_record is None:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: result artifact was not admitted by a server-owned producer"
                )
            if run_id != target_run_id:
                if branch is None:
                    raise WorkflowExecutionError(
                        "WORKFLOW_TARGET_RUN_MISMATCH: foreign artifact lacks an admitted model branch"
                    )
                if (
                    branch.get("workflow_id") != draft.workflow_id
                    or branch.get("workflow_step_id") != step.step_id
                    or branch.get("source_run_id") != target_run_id
                    or branch.get("source_artifact_id") != draft.target.get("artifact_id")
                    or branch.get("model_artifact_id") not in set(branch.get("artifact_ids", []) or [])
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_TARGET_RUN_MISMATCH: foreign model branch is not bound to the admitted target"
                    )
                provenance = server_record.get("provenance")
                if (
                    not isinstance(provenance, Mapping)
                    or provenance.get("branch_id") != branch.get("branch_id")
                    or provenance.get("model_run_id") != branch.get("run_id")
                    or provenance.get("model_artifact_id") != branch.get("model_artifact_id")
                    or provenance.get("source_run_id") != target_run_id
                    or provenance.get("source_artifact_id") != draft.target.get("artifact_id")
                    or artifact_id not in set(provenance.get("expected_artifacts", []) or [])
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: foreign artifact lacks a server-admitted model branch"
                    )
            self._validate_server_artifact_snapshot(server_record, receipt=receipt)

    def validate_completed_dependency_results(
        self,
        draft: WorkflowDraft,
        step: WorkflowStep,
        previous: Mapping[str, WorkflowStepResult],
    ) -> dict[str, dict[str, Any]]:
        """Project only previously completed, server-admitted dependencies.

        ``previous`` is a callback argument and is therefore not evidence by
        itself.  Report must not copy its artifact ids, row counts, or status
        into a formal collection until the corresponding prior completion and
        the in-memory server artifact admission have both been checked.  The
        method returns a bounded projection built from the server completion
        records, never from caller-supplied metadata.
        """

        self._require_server_host()
        if not isinstance(previous, Mapping):
            raise WorkflowExecutionError(
                "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: report dependencies are not a mapping"
            )
        declared_steps = {candidate.step_id: candidate for candidate in draft.steps}
        if step.step_id not in declared_steps:
            raise WorkflowExecutionError(
                "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: report step is not in the compiled workflow"
            )
        required_dependencies = set(step.depends_on)
        supplied_dependencies = {str(key) for key in previous}
        missing_dependencies = required_dependencies - supplied_dependencies
        if missing_dependencies:
            raise WorkflowExecutionError(
                "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: report is missing completed dependencies: "
                + ", ".join(sorted(missing_dependencies))
            )

        records = self._records(draft.workflow_id)
        projected: dict[str, dict[str, Any]] = {}
        for raw_step_id, candidate in previous.items():
            step_id = str(raw_step_id)
            dependency_step = declared_steps.get(step_id)
            if dependency_step is None or step_id == step.step_id:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: report dependency is not a compiled step"
                )
            if type(candidate) is not WorkflowStepResult:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: report dependency result is not typed"
                )

            completions = [
                item
                for item in records
                if item.get("record_type") == "workflow_completion"
                and item.get("status") == "completed"
                and item.get("step_id") == step_id
            ]
            if len(completions) != 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: dependency lacks one completed server record"
                )
            completion = completions[0]
            receipt_id = completion.get("receipt_id")
            issued = [
                item[0]
                for item in self._issued_receipts.values()
                if item[0].receipt_id == receipt_id
            ]
            if len(issued) != 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: dependency receipt is not active in the server registry"
                )
            dependency_receipt = issued[0]
            self._validate_completion_record(completion, dependency_receipt)
            admissions = [
                item
                for item in records
                if item.get("record_type") == "workflow_admission"
                and item.get("receipt_id") == receipt_id
            ]
            if len(admissions) != 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: dependency lacks its unique admission"
                )
            self._validate_admission_record(admissions[0], dependency_receipt)

            submitted_artifacts = _validated_artifact_ids(candidate.artifact_ids)
            completed_artifacts = _validated_artifact_ids(completion.get("artifact_ids", []))
            if submitted_artifacts != completed_artifacts:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: dependency artifacts differ from the completed server record"
                )

            for raw_artifact_id in completed_artifacts:
                if raw_artifact_id.count(":") > 1:
                    raise WorkflowExecutionError(
                        "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: dependency artifact identity is malformed"
                    )
                if ":" in raw_artifact_id:
                    run_id, artifact_id = raw_artifact_id.split(":", 1)
                else:
                    run_id = _require_workflow_opaque_ref(
                        draft.target.get("run_id"), "dependency artifact run_id"
                    )
                    artifact_id = raw_artifact_id
                _require_workflow_opaque_ref(run_id, "dependency artifact run_id")
                _require_workflow_artifact_ref(artifact_id, "dependency artifact_id")
                matching_registry = [
                    row
                    for row in self._server_artifact_registry.values()
                    if row.get("receipt_id") == receipt_id
                    and row.get("workflow_id") == draft.workflow_id
                    and row.get("workflow_step_id") == step_id
                    and row.get("run_id") == run_id
                    and row.get("artifact_id") == artifact_id
                ]
                if len(matching_registry) != 1:
                    raise WorkflowExecutionError(
                        "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: dependency artifact is not in the completed server registry"
                    )
                self._validate_server_artifact_snapshot(
                    matching_registry[0], receipt=dependency_receipt
                )

            row_counts = completion.get("row_counts")
            if not isinstance(row_counts, Mapping):
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: completed dependency row counts are malformed"
                )
            try:
                bounded_row_counts = {
                    str(key): int(value) for key, value in row_counts.items()
                }
            except (TypeError, ValueError, OverflowError) as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_DEPENDENCY_REGISTRY_REQUIRED: completed dependency row counts are invalid"
                ) from exc
            projected[step_id] = {
                "status": "completed",
                "artifact_ids": completed_artifacts,
                "row_counts": bounded_row_counts,
            }
        return projected

    def record_formal_artifact(
        self,
        evidence_port: Any,
        receipt: Any,
        *,
        run_root: Path,
        artifact_id: str,
        path: Path,
        artifact_type: str = "formal_output",
        producer_step: str = "formal_output",
        inputs: Iterable[str] = (),
        output_target: _FormalOutputTarget | None = None,
    ) -> None:
        """Record a report/export artifact through the active receipt."""

        if evidence_port is not self or receipt is not self._active_receipt():
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: formal artifact is not bound to the active workflow receipt"
            )
        run_id = _require_workflow_opaque_ref(
            self._active_draft().target.get("run_id"), "workflow target run_id"
        )
        expected_run_root = self.project_root / "runs" / run_id
        if run_root != expected_run_root:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal artifact root is not the admitted target run"
            )
        if type(output_target) is not _FormalOutputTarget:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_PATH_CHANGED: formal artifact requires its held output target"
            )
        key = (receipt.receipt_id, run_id, artifact_id)
        previous_row = self._server_artifact_registry.get(key)
        try:
            output_target._check_identity()
            self._admit_server_artifact(
                receipt,
                run_id=run_id,
                artifact_id=artifact_id,
                path=path,
                artifact_type=artifact_type,
                producer_step=producer_step,
                inputs=inputs,
                expected_artifacts=(),
                output_target=output_target,
            )
            row = self._server_artifact_registry.get(key)
            if row is None:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: formal artifact admission produced no server row"
                )
            self._publish_formal_artifact_index(output_target, row)
            output_target.finalize_committed()
        except Exception:
            if previous_row is None:
                self._server_artifact_registry.pop(key, None)
            else:
                self._server_artifact_registry[key] = previous_row
            output_target.rollback_committed()
            raise

    def _active_receipt(self) -> WorkflowAdmissionReceipt:
        context = _WRITE_CONTEXT.get()
        if context is None or len(context) != 4 or context[0] is not self:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: no active workflow receipt"
            )
        return context[1]

    def _active_draft(self) -> WorkflowDraft:
        context = _WRITE_CONTEXT.get()
        if context is None or len(context) != 4 or context[0] is not self:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: no active workflow draft"
            )
        return context[2]

    @staticmethod
    def _result_from_record(record: Mapping[str, Any]) -> WorkflowStepResult:
        outputs = record.get("output_bindings") or {}
        lineage = record.get("lineage") or {}
        if not isinstance(outputs, Mapping) or not isinstance(lineage, Mapping):
            raise WorkflowExecutionError("WORKFLOW_EVIDENCE_CORRUPT: completion metadata is malformed")
        if any(not isinstance(value, Mapping) for value in outputs.values()):
            raise WorkflowExecutionError("WORKFLOW_EVIDENCE_CORRUPT: output binding is malformed")
        if any("binding_type" not in value for value in outputs.values()):
            raise WorkflowExecutionError("WORKFLOW_EVIDENCE_CORRUPT: typed output binding lacks binding_type")
        payload: dict[str, Any] = {
            "output_bindings": {str(key): dict(value) for key, value in outputs.items() if isinstance(value, Mapping)},
            "lineage": dict(lineage),
        }
        produced = outputs.get("produced_dataset")
        if isinstance(produced, Mapping):
            payload["produced_dataset"] = _binding_body(produced)
        branches = lineage.get("branches")
        if isinstance(branches, list):
            payload["branches"] = branches
        return WorkflowStepResult(
            artifact_ids=_validated_artifact_ids(record.get("artifact_ids", [])),
            row_counts={str(key): int(value) for key, value in (record.get("row_counts") or {}).items()},
            result_fingerprint=record.get("result_fingerprint"),
            payload=payload,
            output_bindings={str(key): dict(value) for key, value in outputs.items() if isinstance(value, Mapping)},
            lineage=dict(lineage),
            restored_from_state=True,
        )

    @staticmethod
    def _target_snapshot(draft: WorkflowDraft) -> dict[str, Any]:
        try:
            snapshot = _snapshot_json(draft.target)
        except (TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_TARGET_MISSING: workflow target identity is incomplete"
            ) from exc
        if not isinstance(snapshot, dict) or any(
            not snapshot.get(key) for key in ("run_id", "node_ref", "artifact_id")
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_TARGET_MISSING: workflow target identity is incomplete"
            )
        return snapshot

    def _validate_admission_record(
        self,
        record: Mapping[str, Any],
        receipt: WorkflowAdmissionReceipt,
    ) -> None:
        if record.get("receipt_owner") != receipt.receipt_owner:
            raise WorkflowExecutionError(
                "WORKFLOW_RESTART_AUTHORITY_REQUIRED: persisted admission belongs to another worker"
            )
        if (
            record.get("owner_pid") != receipt.owner_pid
            or record.get("process_generation") != receipt.process_generation
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_PROCESS_BOUNDARY: persisted admission belongs to another process generation"
            )
        if record.get("workflow_id") != receipt.workflow_id:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: receipt workflow identity changed"
            )
        if record.get("step_id") != receipt.step_id:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: receipt step identity changed"
            )
        if record.get("execution_key") != (
            f"{receipt.workflow_id}:{receipt.step_id}:{receipt.step_fingerprint}"
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: receipt execution identity changed"
            )
        target = record.get("target")
        if not isinstance(target, Mapping):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: persisted admission target is malformed"
            )
        if record.get("target_fingerprint") != _fingerprint(dict(target)):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: persisted admission target digest is invalid"
            )
        if record.get("target_fingerprint") != receipt.target_fingerprint:
            raise WorkflowExecutionError(
                "WORKFLOW_TARGET_MISMATCH: receipt target identity changed"
            )
        workflow_template = record.get("workflow_template")
        preconditions = record.get("preconditions")
        bindings = record.get("bindings")
        plan_steps = record.get("plan_steps")
        if (
            not isinstance(workflow_template, str)
            or not isinstance(preconditions, Mapping)
            or not isinstance(bindings, Mapping)
            or not isinstance(plan_steps, list)
            or any(not isinstance(item, Mapping) for item in plan_steps)
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: persisted admission plan is malformed"
            )
        if record.get("scope_ref") != receipt.scope_ref:
            raise WorkflowExecutionError(
                "WORKFLOW_CROSS_SCOPE: receipt scope belongs to another workflow"
            )
        if record.get("plan_fingerprint") != receipt.plan_fingerprint:
            raise WorkflowExecutionError(
                "WORKFLOW_STALE: receipt plan fingerprint changed"
            )
        if record.get("step_fingerprint") != receipt.step_fingerprint:
            raise WorkflowExecutionError(
                "WORKFLOW_CHANGED_CONTRACT: receipt step fingerprint changed"
            )
        if record.get("contract_fingerprint") != receipt.contract_fingerprint:
            raise WorkflowExecutionError(
                "WORKFLOW_CHANGED_CONTRACT: receipt contract fingerprint changed"
            )
        if record.get("admission_fingerprint") != _persisted_admission_fingerprint(record):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: persisted admission digest is invalid"
            )
        if record.get("admission_fingerprint") != receipt.admission_fingerprint:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: immutable admission inputs changed"
            )
        persisted_step = record.get("step")
        if not isinstance(persisted_step, Mapping):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: persisted admission step is malformed"
            )
        if _workflow_contract_fingerprint_from_dict(persisted_step) != record.get(
            "contract_fingerprint"
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: persisted admission contract digest is invalid"
            )

    def validate_execution_snapshot(
        self,
        receipt: WorkflowAdmissionReceipt,
        draft: WorkflowDraft,
        step: WorkflowStep,
    ) -> None:
        """Revalidate the complete admitted snapshot immediately before dispatch."""

        self._require_receipt(receipt)
        try:
            _require_server_compiler_receipt(draft)
            scope_ref = self._scope_ref(draft)
            matching = next(
                (candidate for candidate in draft.steps if candidate.step_id == step.step_id),
                None,
            )
            contract_fingerprint = self._contract_fingerprint(step)
            compiler_receipt = draft.compiler_receipt
        except (KeyError, TypeError, ValueError, WorkflowExecutionError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: current draft snapshot is not server-issued"
            ) from exc
        if (
            matching is None
            or matching.to_dict() != step.to_dict()
            or compiler_receipt is None
            or scope_ref != receipt.scope_ref
            or receipt.workflow_id != draft.workflow_id
            or receipt.plan_fingerprint != draft.plan_fingerprint
            or receipt.target_fingerprint != _fingerprint(dict(draft.target))
            or receipt.admission_fingerprint
            != _workflow_admission_fingerprint(
                workflow_id=draft.workflow_id,
                workflow_template=draft.workflow_template,
                target=draft.target,
                preconditions=draft.preconditions,
                bindings=draft.bindings,
                steps=draft.steps,
                plan_fingerprint=draft.plan_fingerprint,
            )
            or receipt.step_id != step.step_id
            or receipt.step_fingerprint != step.fingerprint
            or receipt.contract_fingerprint != contract_fingerprint
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: current execution snapshot differs from admission"
            )

        path = self._path(receipt.workflow_id)
        with _evidence_lock(
            path, admitted_directory_fd=self._host_endpoint_fd
        ) as lock:
            admissions = [
                item
                for item in self._records(receipt.workflow_id)
                if item.get("record_type") == "workflow_admission"
                and item.get("receipt_id") == receipt.receipt_id
            ]
            if len(admissions) != 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_REQUIRED: execution snapshot lacks a unique admission"
                )
            admission = admissions[0]
            self._validate_admission_record(admission, receipt)
            expected = {
                "workflow_id": draft.workflow_id,
                "workflow_template": draft.workflow_template,
                "target": _snapshot_json(draft.target),
                "preconditions": _snapshot_json(draft.preconditions),
                "bindings": _snapshot_json(draft.bindings),
                "plan_steps": _snapshot_json([candidate.to_dict() for candidate in draft.steps]),
                "plan_fingerprint": draft.plan_fingerprint,
                "step": step.to_dict(),
            }
            if any(admission.get(key) != value for key, value in expected.items()):
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_MISMATCH: persisted admission snapshot differs from draft"
                )

    def _validate_completion_artifacts(
        self,
        admission: Mapping[str, Any],
        *,
        receipt: WorkflowAdmissionReceipt,
        artifact_ids: list[str],
        output_bindings: Mapping[str, Any],
        lineage: Mapping[str, Any],
    ) -> None:
        """Require every completion artifact to be owned, registered and bound."""

        if not artifact_ids:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: completion produced no registered project artifact"
            )
        target = admission.get("target")
        step = admission.get("step")
        if not isinstance(target, Mapping) or not isinstance(step, Mapping):
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: admission lacks artifact ownership proof"
            )
        target_run_id = _require_workflow_opaque_ref(
            target.get("run_id"), "workflow target run_id"
        )
        workflow_id = str(admission.get("workflow_id", ""))
        workflow_step_id = str(admission.get("step_id", ""))
        operation_id = str(step.get("operation_id", ""))
        expected_artifacts = {
            str(item) for item in (step.get("expected_artifacts") or []) if str(item)
        }
        bindings = [
            value for value in output_bindings.values() if isinstance(value, Mapping)
        ] if isinstance(output_bindings, Mapping) else []
        branch_proof: dict[str, Mapping[str, Any]] = {}
        raw_branches = lineage.get("branches") if isinstance(lineage, Mapping) else None
        if isinstance(raw_branches, list):
            for branch in raw_branches:
                if not isinstance(branch, Mapping):
                    continue
                if (
                    branch.get("workflow_id") != workflow_id
                    or branch.get("workflow_step_id") != workflow_step_id
                ):
                    continue
                branch_run_id = branch.get("run_id")
                if not isinstance(branch_run_id, str):
                    continue
                for branch_artifact_id in branch.get("artifact_ids", []) or []:
                    if isinstance(branch_artifact_id, str):
                        branch_proof[f"{branch_run_id}:{branch_artifact_id}"] = branch

        seen_expected: set[str] = set()
        for raw_artifact_id in artifact_ids:
            if not isinstance(raw_artifact_id, str) or not raw_artifact_id:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact identity is malformed"
                )
            if raw_artifact_id.count(":") > 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact identity is not an opaque reference"
                )
            if ":" in raw_artifact_id:
                raw_run_id, raw_id = raw_artifact_id.split(":", 1)
            else:
                raw_run_id, raw_id = target_run_id, raw_artifact_id
            binding = next(
                (
                    candidate
                    for candidate in bindings
                    if candidate.get("artifact_id") in {raw_id, raw_artifact_id}
                ),
                None,
            )
            run_id = raw_run_id
            if binding is not None and binding.get("run_id") is not None:
                bound_run_id = _require_workflow_opaque_ref(
                    binding.get("run_id"), "completion artifact run_id"
                )
                if bound_run_id != run_id:
                    raise WorkflowExecutionError(
                        "WORKFLOW_TARGET_RUN_MISMATCH: output binding is not bound to the "
                        "admitted artifact run"
                    )
                run_id = bound_run_id
            _require_workflow_opaque_ref(run_id, "completion artifact run_id")
            artifact_id = _require_workflow_artifact_ref(raw_id, "completion artifact_id")
            server_record = self._server_artifact_registry.get(
                (receipt.receipt_id, run_id, artifact_id)
            )
            if server_record is None:
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: completion artifact is missing from the server-owned artifact registry; a registered project artifact is required"
                )
            if (
                server_record.get("workflow_id") != workflow_id
                or server_record.get("workflow_step_id") != workflow_step_id
                or server_record.get("receipt_id") != receipt.receipt_id
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: server artifact admission is bound to another workflow step"
                )
            branch_record = branch_proof.get(f"{run_id}:{artifact_id}")
            if run_id != target_run_id:
                if branch_record is None:
                    raise WorkflowExecutionError(
                        "WORKFLOW_TARGET_RUN_MISMATCH: completion artifact belongs to "
                        "another run without an admitted model branch"
                    )
                if (
                    branch_record.get("source_run_id") != target_run_id
                    or branch_record.get("source_artifact_id") != target.get("artifact_id")
                    or branch_record.get("workflow_id") != workflow_id
                    or branch_record.get("workflow_step_id") != workflow_step_id
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_TARGET_RUN_MISMATCH: model branch is not bound to the "
                        "admitted workflow target"
                    )
                provenance = server_record.get("provenance")
                if (
                    not isinstance(provenance, Mapping)
                    or provenance.get("model_run_id") != run_id
                    or provenance.get("model_artifact_id") != branch_record.get("model_artifact_id")
                    or provenance.get("source_run_id") != target_run_id
                    or provenance.get("source_artifact_id") != target.get("artifact_id")
                    or artifact_id not in set(provenance.get("expected_artifacts", []) or [])
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: foreign model artifact lacks server-owned branch provenance"
                    )
            _artifact_path, actual_sha256 = self._validate_server_artifact_snapshot(
                server_record,
                receipt=receipt,
            )
            if binding is not None and binding.get("content_sha256") is not None and not _digest_matches(
                binding.get("content_sha256"), actual_sha256
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: output artifact digest does not match its binding"
                )
            record_step = str(server_record.get("producer_step", ""))
            producer_operation = str(server_record.get("producer_operation_id", ""))
            direct_step_proof = record_step in {operation_id, workflow_step_id} or producer_operation in {
                operation_id,
                workflow_step_id,
            }
            branch_step_proof = (
                raw_artifact_id in branch_proof
                or f"{run_id}:{artifact_id}" in branch_proof
            )
            canonical_statistical_proof = False
            canonical_aliases = _WORKFLOW_ARTIFACT_STEP_ALIASES.get(operation_id, frozenset())
            if record_step in canonical_aliases:
                inputs = {
                    str(item)
                    for item in (server_record.get("inputs") or [])
                    if isinstance(item, str)
                }
                canonical_statistical_proof = (
                    record_step not in {"reporting", "export"}
                    or bool(inputs & set(artifact_ids))
                )
            if not (direct_step_proof or branch_step_proof or canonical_statistical_proof):
                raise WorkflowExecutionError(
                    "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: artifact is not produced by the admitted step contract"
                )
            if binding is not None:
                if binding.get("operation_id") not in {None, operation_id}:
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: output operation is not bound to the admitted step"
                    )
                if binding.get("workflow_step_id") not in {None, workflow_step_id}:
                    raise WorkflowExecutionError(
                        "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: output step is not bound to the admission"
                    )
            seen_expected.add(artifact_id)

        missing_expected = expected_artifacts - seen_expected
        if missing_expected:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: completion is missing expected outputs: "
                + ", ".join(sorted(missing_expected))
            )

    @staticmethod
    def _validate_completion_record(
        record: Mapping[str, Any], receipt: WorkflowAdmissionReceipt
    ) -> None:
        if record.get("completion_seal") != _completion_seal(record):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: completion integrity seal is invalid"
            )
        expected = {
            "record_type": "workflow_completion",
            "status": "completed",
            "execution_key": f"{receipt.workflow_id}:{receipt.step_id}:{receipt.step_fingerprint}",
            "workflow_id": receipt.workflow_id,
            "step_id": receipt.step_id,
            "target_fingerprint": receipt.target_fingerprint,
            "plan_fingerprint": receipt.plan_fingerprint,
            "step_fingerprint": receipt.step_fingerprint,
            "scope_ref": receipt.scope_ref,
            "contract_fingerprint": receipt.contract_fingerprint,
            "receipt_owner": receipt.receipt_owner,
            "owner_pid": receipt.owner_pid,
            "process_generation": receipt.process_generation,
            "receipt_id": receipt.receipt_id,
            "attempt": receipt.attempt,
            "admission_fingerprint": receipt.admission_fingerprint,
        }
        if any(record.get(key) != value for key, value in expected.items()):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_CORRUPT: completion identity is not bound to admission"
            )

    def admit(self, draft: WorkflowDraft, step: WorkflowStep) -> WorkflowAdmissionReceipt:
        path = self._path(draft.workflow_id)
        scope_ref = self._require_server_draft(draft)
        compiler_receipt = _require_server_compiler_receipt(draft)
        matching = next((item for item in draft.steps if item.step_id == step.step_id), None)
        contract_fingerprint = self._contract_fingerprint(step)
        server_binding = next(
            (
                (step_id, step_fingerprint, compiled_contract)
                for step_id, step_fingerprint, compiled_contract in compiler_receipt.step_contracts
                if step_id == step.step_id
            ),
            None,
        )
        if (
            matching is None
            or matching.to_dict() != step.to_dict()
            or server_binding
            != (step.step_id, step.fingerprint, contract_fingerprint)
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_CHANGED_CONTRACT: admission step is not the server-compiled step"
            )
        target_snapshot = self._target_snapshot(draft)
        target_fingerprint = _fingerprint(target_snapshot)
        execution_key = f"{draft.workflow_id}:{step.step_id}:{step.fingerprint}"
        with _evidence_lock(
            path, admitted_directory_fd=self._host_endpoint_fd
        ) as lock:
            records = self._records(draft.workflow_id)
            relevant = [item for item in records if item.get("execution_key") == execution_key]
            if any(
                item.get("plan_fingerprint") not in {None, draft.plan_fingerprint}
                for item in relevant
            ):
                raise WorkflowExecutionError("WORKFLOW_STALE: workflow admission plan is stale")
            completions = [
                item for item in relevant if item.get("record_type") == "workflow_completion"
            ]
            if completions:
                if len(completions) > 1 and any(
                    item != completions[0] for item in completions[1:]
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_EVIDENCE_CORRUPT: duplicate completion identity"
                    )
                completion = completions[-1]
                if completion.get("receipt_owner") != _EVIDENCE_RECEIPT_OWNER:
                    raise WorkflowExecutionError(
                        "WORKFLOW_RESTART_AUTHORITY_REQUIRED: persisted completion belongs to another worker"
                    )
                if completion.get("target_fingerprint") != target_fingerprint:
                    raise WorkflowExecutionError(
                        "WORKFLOW_TARGET_MISMATCH: completion belongs to another target"
                    )
                if completion.get("scope_ref") != scope_ref:
                    raise WorkflowExecutionError(
                        "WORKFLOW_CROSS_SCOPE: completion belongs to another scope"
                    )
                if completion.get("contract_fingerprint") != contract_fingerprint:
                    raise WorkflowExecutionError(
                        "WORKFLOW_CHANGED_CONTRACT: completion binding changed"
                    )
                if completion.get("plan_fingerprint") != draft.plan_fingerprint:
                    raise WorkflowExecutionError(
                        "WORKFLOW_STALE: completion plan is stale"
                    )
                completion_admissions = [
                    item
                    for item in relevant
                    if item.get("record_type") == "workflow_admission"
                    and item.get("receipt_id") == completion.get("receipt_id")
                ]
                if len(completion_admissions) != 1:
                    raise WorkflowExecutionError(
                        "WORKFLOW_EVIDENCE_CORRUPT: completion lacks its unique admission"
                    )
                receipt = WorkflowAdmissionReceipt(
                    workflow_id=draft.workflow_id,
                    step_id=step.step_id,
                    plan_fingerprint=draft.plan_fingerprint,
                    step_fingerprint=step.fingerprint,
                    scope_ref=scope_ref,
                    contract_fingerprint=contract_fingerprint,
                    receipt_id=str(completion["receipt_id"]),
                    attempt=int(completion.get("attempt", 1)),
                    completed_result=self._result_from_record(completion),
                    target_fingerprint=target_fingerprint,
                    admission_fingerprint=compiler_receipt.admission_fingerprint,
                    receipt_owner=_EVIDENCE_RECEIPT_OWNER,
                    owner_pid=self._owner_pid,
                    process_generation=self._process_generation,
                )
                self._validate_completion_record(completion, receipt)
                self._validate_admission_record(completion_admissions[0], receipt)
                if any(
                    item.get("record_type") == "workflow_abort"
                    and item.get("receipt_id") == receipt.receipt_id
                    for item in relevant
                ):
                    raise WorkflowExecutionError(
                        "WORKFLOW_ADMISSION_ABORTED: aborted receipt cannot replay"
                    )
                self._validate_completion_artifacts(
                    completion_admissions[0],
                    receipt=receipt,
                    artifact_ids=_validated_artifact_ids(completion.get("artifact_ids", [])),
                    output_bindings=completion.get("output_bindings") or {},
                    lineage=completion.get("lineage") or {},
                )
                self._register_receipt(receipt)
                return receipt
            aborted_receipts = {
                str(item.get("receipt_id"))
                for item in relevant
                if item.get("record_type") == "workflow_abort"
            }
            active = [
                item
                for item in relevant
                if item.get("record_type") == "workflow_admission"
                and item.get("status") == "admitted"
                and str(item.get("receipt_id")) not in aborted_receipts
            ]
            if active:
                for item in active:
                    active_receipt = WorkflowAdmissionReceipt(
                        workflow_id=draft.workflow_id,
                        step_id=step.step_id,
                        plan_fingerprint=draft.plan_fingerprint,
                        step_fingerprint=step.fingerprint,
                        scope_ref=scope_ref,
                        contract_fingerprint=contract_fingerprint,
                        receipt_id=str(item["receipt_id"]),
                        attempt=int(item.get("attempt", 1)),
                        target_fingerprint=target_fingerprint,
                        admission_fingerprint=compiler_receipt.admission_fingerprint,
                        receipt_owner=_EVIDENCE_RECEIPT_OWNER,
                        owner_pid=self._owner_pid,
                        process_generation=self._process_generation,
                    )
                    self._validate_admission_record(item, active_receipt)
                raise WorkflowExecutionError(
                    "WORKFLOW_DUPLICATE_EXECUTION: an admitted workflow step has no completion"
                )
            attempts = [int(item.get("attempt", 0)) for item in relevant]
            attempt = max(attempts, default=0) + 1
            receipt_id = f"workflow-admission:{secrets.token_hex(16)}"
            record = {
                "record_type": "workflow_admission",
                "status": "admitted",
                "execution_key": execution_key,
                "workflow_id": draft.workflow_id,
                "step_id": step.step_id,
                "step": step.to_dict(),
                "target": target_snapshot,
                "target_fingerprint": target_fingerprint,
                "workflow_template": _snapshot_json(draft.workflow_template),
                "preconditions": _snapshot_json(draft.preconditions),
                "bindings": _snapshot_json(draft.bindings),
                "plan_steps": _snapshot_json([item.to_dict() for item in draft.steps]),
                "plan_fingerprint": draft.plan_fingerprint,
                "step_fingerprint": step.fingerprint,
                "scope_ref": scope_ref,
                "contract_fingerprint": contract_fingerprint,
                "admission_fingerprint": compiler_receipt.admission_fingerprint,
                "receipt_owner": _EVIDENCE_RECEIPT_OWNER,
                "owner_pid": self._owner_pid,
                "process_generation": self._process_generation,
                "receipt_id": receipt_id,
                "attempt": attempt,
            }
            _append_evidence_record(path, record, directory_fd=lock.directory_fd)
            receipt = WorkflowAdmissionReceipt(
                workflow_id=draft.workflow_id,
                step_id=step.step_id,
                plan_fingerprint=draft.plan_fingerprint,
                step_fingerprint=step.fingerprint,
                scope_ref=scope_ref,
                contract_fingerprint=contract_fingerprint,
                receipt_id=receipt_id,
                attempt=attempt,
                target_fingerprint=target_fingerprint,
                admission_fingerprint=compiler_receipt.admission_fingerprint,
                receipt_owner=_EVIDENCE_RECEIPT_OWNER,
                owner_pid=self._owner_pid,
                process_generation=self._process_generation,
            )
            self._register_receipt(receipt)
            return receipt

    def complete(self, receipt: WorkflowAdmissionReceipt, result: WorkflowStepResult) -> None:
        self._require_receipt(receipt)
        if type(result) is not WorkflowStepResult:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_RESULT_REQUIRED: completion requires a typed step result"
            )
        outputs = _typed_output_bindings(result)
        lineage = _persisted_lineage(result)
        path = self._path(receipt.workflow_id)
        record = {
            "record_type": "workflow_completion",
            "status": "completed",
            "execution_key": f"{receipt.workflow_id}:{receipt.step_id}:{receipt.step_fingerprint}",
            "workflow_id": receipt.workflow_id,
            "step_id": receipt.step_id,
            "target_fingerprint": receipt.target_fingerprint,
            "plan_fingerprint": receipt.plan_fingerprint,
            "step_fingerprint": receipt.step_fingerprint,
            "scope_ref": receipt.scope_ref,
            "contract_fingerprint": receipt.contract_fingerprint,
            "admission_fingerprint": receipt.admission_fingerprint,
            "receipt_owner": receipt.receipt_owner,
            "owner_pid": receipt.owner_pid,
            "process_generation": receipt.process_generation,
            "receipt_id": receipt.receipt_id,
            "attempt": receipt.attempt,
            "artifact_ids": _validated_artifact_ids(result.artifact_ids),
            "row_counts": {str(key): int(value) for key, value in result.row_counts.items()},
            "result_fingerprint": result.result_fingerprint,
            "output_bindings": outputs,
            "lineage": lineage,
        }
        record["completion_seal"] = _completion_seal(record)
        with _evidence_lock(
            path, admitted_directory_fd=self._host_endpoint_fd
        ) as lock:
            records = self._records(receipt.workflow_id)
            admissions = [
                item
                for item in records
                if item.get("record_type") == "workflow_admission"
                and item.get("receipt_id") == receipt.receipt_id
            ]
            if len(admissions) != 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_REQUIRED: evidence completion lacks a unique admission"
                )
            admission = admissions[0]
            self._validate_admission_record(admission, receipt)
            if any(
                item.get("record_type") == "workflow_abort"
                and item.get("receipt_id") == receipt.receipt_id
                for item in records
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_ABORTED: aborted receipt cannot complete"
                )
            self._validate_completion_artifacts(
                admission,
                receipt=receipt,
                artifact_ids=_validated_artifact_ids(record["artifact_ids"]),
                output_bindings=record["output_bindings"],
                lineage=record["lineage"],
            )
            existing = [
                item
                for item in records
                if item.get("record_type") == "workflow_completion"
                and item.get("receipt_id") == receipt.receipt_id
            ]
            if existing:
                self._validate_completion_record(existing[0], receipt)
                if existing[0] != record:
                    raise WorkflowExecutionError(
                        "WORKFLOW_EVIDENCE_CORRUPT: completion is not idempotent"
                    )
                return
            if admission.get("status") != "admitted":
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_REQUIRED: evidence completion lacks an active admission"
                )
            _append_evidence_record(path, record, directory_fd=lock.directory_fd)

    def abort(self, receipt: WorkflowAdmissionReceipt, error: str) -> None:
        self._require_receipt(receipt)
        path = self._path(receipt.workflow_id)
        with _evidence_lock(
            path, admitted_directory_fd=self._host_endpoint_fd
        ) as lock:
            records = self._records(receipt.workflow_id)
            admissions = [
                item
                for item in records
                if item.get("record_type") == "workflow_admission"
                and item.get("receipt_id") == receipt.receipt_id
            ]
            if len(admissions) != 1:
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_REQUIRED: abort lacks a unique admission"
                )
            self._validate_admission_record(admissions[0], receipt)
            if any(
                item.get("record_type") == "workflow_completion"
                and item.get("receipt_id") == receipt.receipt_id
                for item in records
            ):
                return
            if any(
                item.get("record_type") == "workflow_abort"
                and item.get("receipt_id") == receipt.receipt_id
                for item in records
            ):
                return
            if admissions[0].get("status") != "admitted":
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_ABORTED: receipt is already aborted"
                )
            _append_evidence_record(path, {
                "record_type": "workflow_abort",
                "status": "aborted",
                "execution_key": f"{receipt.workflow_id}:{receipt.step_id}:{receipt.step_fingerprint}",
                "workflow_id": receipt.workflow_id,
                "step_id": receipt.step_id,
                "target_fingerprint": receipt.target_fingerprint,
                "plan_fingerprint": receipt.plan_fingerprint,
                "step_fingerprint": receipt.step_fingerprint,
                "scope_ref": receipt.scope_ref,
                "contract_fingerprint": receipt.contract_fingerprint,
                "admission_fingerprint": receipt.admission_fingerprint,
                "receipt_owner": receipt.receipt_owner,
                "owner_pid": receipt.owner_pid,
                "process_generation": receipt.process_generation,
                "receipt_id": receipt.receipt_id,
                "attempt": receipt.attempt,
                "error": str(error)[:2000],
            }, directory_fd=lock.directory_fd)


def issue_server_evidence_port(
    project_root: Path | str, host_endpoint: Any = None
) -> EvidencePersistencePort:
    """Issue a port only from the deployment-owned host resolver.

    ``host_endpoint`` remains in the signature for a narrow compatibility
    rejection.  Request or caller-supplied mappings, paths, descriptors and
    sockets are never a trust root.  The server/OS adapter must replace
    ``_deployment_host_endpoint_from_supervisor`` with a resolver that returns
    the admitted endpoint identity.
    """

    if host_endpoint is not None:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: caller-selected workflow host endpoint is not a trust root"
        )
    normalized_root = Path(project_root).expanduser().resolve()
    try:
        resolved_endpoint = _deployment_host_endpoint_from_supervisor(normalized_root)
    except WorkflowExecutionError:
        raise
    except BaseException as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment workflow host resolver failed closed"
        ) from exc
    if type(resolved_endpoint) is not WorkflowHostEndpointV1:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: deployment workflow host resolver returned invalid input"
        )
    _require_supervisor_host_endpoint(resolved_endpoint)
    port = object.__new__(EvidencePersistencePort)
    try:
        port._initialize_from_host_endpoint(normalized_root, resolved_endpoint)
        _ISSUED_EVIDENCE_PORTS[id(port)] = port
        port._require_server_host()
    except Exception:
        port.close()
        raise
    return port


def _require_active_write_context() -> tuple[
    EvidencePersistencePort,
    WorkflowAdmissionReceipt,
    WorkflowDraft,
    WorkflowStep,
]:
    """Require the exact receipt-bound context installed by the gated callback."""

    context = _WRITE_CONTEXT.get()
    if context is None or len(context) != 4:
        raise WorkflowExecutionError(
            "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: write-capable workflow helper "
            "requires an admitted server receipt"
        )
    evidence_port, receipt, draft, step = context
    if (
        type(evidence_port) is not EvidencePersistencePort
        or type(receipt) is not WorkflowAdmissionReceipt
        or type(draft) is not WorkflowDraft
        or type(step) is not WorkflowStep
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: write context is not server-issued"
        )
    evidence_port.require_receipt(receipt)
    evidence_port.validate_execution_snapshot(receipt, draft, step)
    return evidence_port, receipt, draft, step


def _p7_result_status(
    result: Mapping[str, Any],
) -> tuple[object, Mapping[str, Any]]:
    """Read the status from either supported P7 result-envelope shape."""

    status = result.get("status")
    details: Mapping[str, Any] = result
    nested = result.get("result")
    if status is None and isinstance(nested, Mapping) and "status" in nested:
        status = nested.get("status")
        details = nested
    return status, details


def _read_post_estimation_artifact_records(run_dir: Path) -> list[Any]:
    """Read the registry shape needed by the post-estimation projection."""

    try:
        index = _read_artifacts_index(run_dir)
    except (
        AttributeError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
        WorkbenchAPIError,
    ) as exc:
        raise WorkflowExecutionError(
            "registered post-estimation artifact index cannot be read"
        ) from exc
    if not isinstance(index, Mapping):
        raise WorkflowExecutionError(
            "registered post-estimation artifact index must be an object"
        )
    records = index.get("artifacts", [])
    if not isinstance(records, list):
        raise WorkflowExecutionError(
            "registered post-estimation artifact index must contain an artifacts list"
        )
    return records


def collect_post_estimation_results(
    root: Path,
    run_id: str,
    *,
    limit: int = MAX_PROJECTED_POST_ESTIMATION_RESULTS,
) -> list[dict[str, Any]]:
    """Project durable workflow-analysis evidence that belongs to one run.

    A completed workflow is not an answered question: the step writes a
    provenance-carrying artifact, but nothing renders it, so the user who
    asked never sees the number. This is the read side that product and Agent
    surfaces consume. P7 pack results use the same projection so a composed
    statistical call is not executable-but-invisible.

    Relevance has two identities on purpose. The artifact is persisted on the
    workflow's *source* run, while the model it describes is a *child* run --
    and the child is what the user opens to read the result. Matching only the
    storing run would keep the answer invisible exactly where it is looked for.

    Only artifacts registered in a run's index are read. The index is the
    admission record; trusting loose files on disk would let anything able to
    write into the run directory publish a finding through the product surface.
    """

    if limit <= 0:
        return []
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return []

    collected: list[dict[str, Any]] = []
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        for record in _read_post_estimation_artifact_records(run_dir):
            if not isinstance(record, Mapping):
                raise WorkflowExecutionError(
                    "registered post-estimation artifact record must be an object"
                )
            artifact_type = record.get("artifact_type")
            if artifact_type not in POST_ESTIMATION_ARTIFACT_TYPES:
                continue
            # The ordinary statistical-tests stage uses the historical
            # artifact type but has no workflow source/result envelope. It is
            # consumed by the run's statistical-evidence projection, not by
            # this post-estimation result list. Model post-estimation tests
            # use the same type with their operation step and remain included.
            if artifact_type == "statistical_test" and record.get("step") == "statistical_tests":
                continue
            entry = _read_post_estimation_entry(run_dir, record)
            if entry["run_id"] != run_id and entry["model_run_id"] != run_id:
                continue
            collected.append(entry)

    collected.sort(key=lambda item: (item["run_id"], item["artifact_id"]))
    if len(collected) > limit:
        raise WorkflowExecutionError(
            f"post-estimation evidence count {len(collected)} exceeds projection limit {limit}; "
            "request a narrower evidence scope"
        )
    return collected[:limit]


def _read_post_estimation_entry(
    run_dir: Path, record: Mapping[str, Any]
) -> dict[str, Any]:
    """Read one registered post-estimation artifact and fail closed on damage.

    The artifacts index is the admission record.  Once an evidence artifact is
    registered, omitting it from a public projection would turn corruption into
    a false-looking successful analysis.  Loose, unregistered files remain
    ignored by the caller.
    """

    relative = str(record.get("path", ""))
    if not relative:
        raise WorkflowExecutionError(
            "registered post-estimation artifact has no path"
        )
    path = (run_dir / relative).resolve()
    # The index stores repository-relative paths; a traversal escape means the
    # record is not describing this run's own evidence.
    if not path.is_file() or run_dir.resolve() not in path.parents:
        raise WorkflowExecutionError(
            "registered post-estimation artifact is missing or escapes its run"
        )
    expected_sha256 = record.get("sha256")
    if not isinstance(expected_sha256, str) or not expected_sha256:
        raise WorkflowExecutionError(
            "registered post-estimation artifact has no file fingerprint"
        )
    try:
        actual_sha256 = sha256_file(path)
    except OSError as exc:
        raise WorkflowExecutionError(
            "registered post-estimation artifact fingerprint cannot be read"
        ) from exc
    if actual_sha256 != expected_sha256:
        raise WorkflowExecutionError(
            "registered post-estimation artifact fingerprint changed"
        )
    try:
        payload = read_json(path)
    except (OSError, ValueError) as exc:
        raise WorkflowExecutionError(
            "registered post-estimation artifact cannot be read"
        ) from exc
    if not isinstance(payload, Mapping):
        raise WorkflowExecutionError(
            "registered post-estimation artifact payload must be an object"
        )
    source = payload.get("source")
    result = payload.get("result")
    if not isinstance(source, Mapping) or not isinstance(result, Mapping):
        raise WorkflowExecutionError(
            "registered post-estimation artifact must contain source and result objects"
        )
    artifact_type = str(record.get("artifact_type", ""))
    if artifact_type == "p7_analysis":
        required_source = {
            "run_id",
            "node_ref",
            "artifact_id",
            "sha256",
            "workflow_id",
            "workflow_step_id",
            "workflow_step_fingerprint",
            "operation_id",
            "pack_family",
        }
        if payload.get("schema_version") != "workbench.workflow.p7-pack/v1":
            raise WorkflowExecutionError("registered P7 analysis artifact has an invalid schema")
        if set(required_source) - set(source):
            raise WorkflowExecutionError("registered P7 analysis artifact has incomplete provenance")
        if any(not isinstance(source.get(field_name), str) or not source[field_name] for field_name in required_source):
            raise WorkflowExecutionError("registered P7 analysis artifact has invalid provenance")
        if result.get("operation_id") != source.get("operation_id"):
            raise WorkflowExecutionError("registered P7 analysis artifact operation identity is inconsistent")
    if artifact_type == "workflow_capability_result":
        required_source = {
            "run_id",
            "node_ref",
            "artifact_id",
            "sha256",
            "workflow_id",
            "workflow_step_id",
            "workflow_step_fingerprint",
            "operation_id",
        }
        if payload.get("schema_version") != "workbench.workflow.capability/v1":
            raise WorkflowExecutionError("registered workflow capability artifact has an invalid schema")
        if set(required_source) - set(source):
            raise WorkflowExecutionError("registered workflow capability artifact has incomplete provenance")
        if not isinstance(payload.get("request"), Mapping) or not payload.get("request_fingerprint"):
            raise WorkflowExecutionError("registered workflow capability artifact has no replayable request")
        if result.get("operation_id") != source.get("operation_id"):
            raise WorkflowExecutionError("registered workflow capability artifact operation identity is inconsistent")
        expected_result_digest = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        if payload.get("result_sha256") != expected_result_digest:
            raise WorkflowExecutionError("registered workflow capability artifact result digest is inconsistent")
    return {
        "artifact_id": str(record.get("artifact_id", "")),
        "artifact_type": artifact_type,
        "operation_id": str(source.get("operation_id") or record.get("step", "")),
        "run_id": str(source.get("run_id", "")),
        "model_run_id": str(source.get("model_run_id", "")),
        "workflow_id": str(source.get("workflow_id", "")),
        "workflow_step_id": str(source.get("workflow_step_id", "")),
        **(
            {"pack_family": str(source["pack_family"]), "source_sha256": str(source["sha256"])}
            if artifact_type == "p7_analysis"
            else (
                {
                    "source_sha256": str(source["sha256"]),
                    "request_fingerprint": str(payload["request_fingerprint"]),
                    "result_sha256": str(payload["result_sha256"]),
                    "result_schema": str(payload["result_schema"]),
                }
                if artifact_type == "workflow_capability_result"
                else {}
            )
        ),
        "result": dict(result),
    }


def _apply_numeric_recipes(
    frame: pd.DataFrame,
    recipes: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply the closed transform vocabulary to a copy of a source frame.

    Contract validation owns recipe shape; runtime validation owns actual data
    domain checks.  In particular, a log is never silently evaluated on zero,
    negative, or non-numeric values, and arithmetic cannot produce infinities.
    """

    derived = frame.copy()
    summaries: list[dict[str, Any]] = []
    for recipe in recipes:
        operator = str(recipe["operator"])
        inputs = [str(column) for column in recipe["input_columns"]]
        output_name = str(recipe["output_name"])
        if output_name in derived.columns:
            raise WorkflowExecutionError(
                f"numeric derivation output already exists: {output_name}"
            )
        missing = [column for column in inputs if column not in derived.columns]
        if missing:
            raise WorkflowExecutionError(
                "numeric derivation source column is unavailable: " + ", ".join(missing)
            )
        numeric_inputs: list[pd.Series] = []
        for column in inputs:
            original = derived[column]
            converted = pd.to_numeric(original, errors="coerce")
            if bool((original.notna() & converted.isna()).any()):
                raise WorkflowExecutionError(
                    f"numeric derivation input is not numeric: {column}"
                )
            numeric_inputs.append(converted.astype(float))
        if operator == "natural_log":
            value = numeric_inputs[0]
            if bool((value.dropna() <= 0).any()):
                raise WorkflowExecutionError(
                    f"natural_log requires strictly positive values: {inputs[0]}"
                )
            result = np.log(value)
        elif operator == "multiply":
            result = numeric_inputs[0] * numeric_inputs[1]
        else:  # contract validation should make this unreachable
            raise WorkflowExecutionError(f"numeric derivation operator is unsupported: {operator}")
        finite = result.notna()
        if bool((~np.isfinite(result[finite])).any()):
            raise WorkflowExecutionError(
                f"numeric derivation produced non-finite values: {output_name}"
            )
        derived[output_name] = result
        summaries.append(
            {
                "operator": operator,
                "input_columns": inputs,
                "output_name": output_name,
                "nonmissing_count": int(finite.sum()),
                "missing_count": int(result.isna().sum()),
            }
        )
    return derived, summaries


def _upstream_numeric_steps(
    draft: WorkflowDraft,
    step_id: str,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> tuple[Any, ...]:
    """Return declared numeric ancestors in compiled topological order."""

    seen: set[str] = set()

    def visit(current: str) -> None:
        for dependency in dependency_graph.get(current, ()):
            if dependency in seen:
                continue
            seen.add(dependency)
            visit(dependency)

    visit(step_id)
    return tuple(
        item
        for item in draft.steps
        # Read from the contract rather than naming the operation here. The
        # compile-time rule that refuses an unreplayable producer upstream of a
        # sourceless step is derived from the same declaration, so the two
        # cannot drift apart into a plan that compiles and then skips a
        # transform.
        if item.step_id in seen and item.operation_id in STEP_REPLAYABLE_BY_RECIPE
    )


def _workflow_input_frame(
    source_frame: pd.DataFrame,
    draft: WorkflowDraft,
    step: Any,
    dependency_graph: Mapping[str, tuple[str, ...]],
    previous: Mapping[str, WorkflowStepResult],
    root: Path,
) -> pd.DataFrame:
    """Rebuild the exact input for a step from its declared DAG.

    A step that committed to another step's output resolves that persisted
    dataset -- and stops there. Replaying the declared recipes afterwards would
    apply the same derivations a second time onto a frame that already carries
    them, which is why this returns early rather than layering the two.
    Everything else keeps the original behaviour: start from the workflow's own
    target and replay the declared numeric derivations.
    """

    if "source" in step.spec:
        return _resolve_committed_source_frame(
            step, previous, root, workflow_run_id=str(draft.target["run_id"])
        )
    frame = source_frame
    for transform_step in _upstream_numeric_steps(draft, str(step.step_id), dependency_graph):
        frame, _ = _apply_numeric_recipes(frame, transform_step.spec["recipes"])
    return frame


_PRODUCED_DATASET_FIELDS = ("run_id", "node_ref", "artifact_id", "content_sha256")


def _require_binding_shape(
    step: Any, from_step: str, produced: Mapping[str, Any], workflow_run_id: str
) -> None:
    """Refuse a binding this runtime cannot read, naming what is wrong.

    The binding is read back from persisted state on resume, so it can outlive
    the code that wrote it. Without this the first sign of a version skew is a
    bare KeyError swallowed by the executor into `error="'node_ref'"`, which
    tells whoever reads it nothing at all -- and the schema version would be a
    field nobody ever compared.

    The run is checked here too, because this step's own output is persisted on
    the workflow's target run and its lineage names the binding's node as the
    parent. A binding from another run would therefore write an edge pointing at
    a node that does not exist in the mutated graph -- a dangling lineage claim
    with no error attached. No plan can currently produce one, since the only
    dataset producer publishes the target run's id; that is a property of
    today's operations, not a guarantee of this contract.
    """

    version = produced.get("schema_version")
    if version != _PRODUCED_DATASET_SCHEMA:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published a "
            f"{version!r} binding, but this runtime reads {_PRODUCED_DATASET_SCHEMA!r}"
        )
    missing = [field for field in _PRODUCED_DATASET_FIELDS if not produced.get(field)]
    if missing:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published an incomplete "
            "binding, missing: " + ", ".join(missing)
        )
    if str(produced["run_id"]) != workflow_run_id:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published a binding on "
            f"run {produced['run_id']}, but this workflow runs on run "
            f"{workflow_run_id}; consuming it would give this step a parent node "
            "that the mutated graph does not contain"
        )
    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(step.operation_id)
    accepted_roles = contract.accepted_dataset_kinds if contract is not None else ()
    if accepted_roles:
        dataset_kind = produced.get("dataset_kind")
        if not isinstance(dataset_kind, str) or not dataset_kind:
            raise WorkflowExecutionError(
                f"workflow step {step.step_id} source {from_step} published an incomplete binding, missing: dataset_kind"
            )
        if dataset_kind not in accepted_roles:
            raise WorkflowExecutionError(
                f"workflow step {step.step_id} source {from_step} published dataset role "
                f"{dataset_kind!r}; accepted roles: " + ", ".join(accepted_roles)
            )


def _committed_source_binding(
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
    workflow_run_id: str,
) -> Mapping[str, Any]:
    """Return the validated binding a step committed to consuming.

    One resolution shared by the two halves that must agree: the frame a step
    computes from, and the lineage it then claims. Resolving them separately is
    how a step ends up correctly consuming an upstream dataset while reporting
    the original table as its parent.
    """

    commitment = step.spec["source"]
    from_step = str(commitment["from_step"])
    upstream = previous.get(from_step)
    if upstream is None:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} has not completed"
        )
    output_name = str(commitment["output"])
    produced = upstream.payload.get(output_name)
    if not isinstance(produced, Mapping):
        typed_outputs = upstream.output_bindings or upstream.payload.get("output_bindings")
        if isinstance(typed_outputs, Mapping):
            candidate = typed_outputs.get(output_name)
            if isinstance(candidate, Mapping):
                produced = {
                    key: value for key, value in candidate.items() if key != "binding_type"
                }
    if not isinstance(produced, Mapping):
        # Two different faults, two different places to look. A live upstream
        # result without the binding means the producing step really published
        # nothing. A result the executor rebuilt from persisted state without it
        # means the state record never carried the binding -- the producing step
        # is fine, and sending the reader to audit its output wastes the whole
        # investigation on a step that is working.
        if upstream.restored_from_state:
            # What is known: the result was rebuilt from the state record, and
            # the record carried no binding. Why it carried none is not known
            # here, and naming one cause would send readers of the other causes
            # to the wrong place -- including toward a re-run that fails
            # identically. So the branch reports the fact and lists what can
            # produce it, rather than asserting which one happened.
            raise WorkflowExecutionError(
                f"workflow step {step.step_id} source {from_step} completed in an "
                f"earlier pass, but its {commitment['output']!r} binding did not "
                "survive into the persisted workflow state. Two things can cause "
                "this and they need different fixes: the state record was written "
                "before bindings were persisted, in which case re-running the plan "
                "from the start resolves it; or the producing step completes "
                "without publishing the binding, in which case a re-run fails the "
                "same way and the producer is what to fix"
            )
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published no "
            f"{commitment['output']!r} binding"
        )
    _require_binding_shape(step, from_step, produced, workflow_run_id)
    return produced


def _lineage_source(
    draft: WorkflowDraft,
    step: Any,
    source_context: Mapping[str, Any],
    previous: Mapping[str, WorkflowStepResult],
) -> dict[str, str]:
    """Where this step's output is actually derived from, for the record.

    A step that declared a `source` computed from the upstream dataset, so the
    graph edge, the recipe's source block and the artifact inputs must all name
    that dataset. Naming `draft.target` instead produces no error and no red
    test -- it just makes the lineage say the original table produced a node it
    did not, which misdirects rerun, comparison, explanation and reporting
    alike. A step without a `source` really is derived from the target, and
    keeps naming it.

    This is resolved once per step in the executor and handed to whatever
    persists the step's output, rather than left for each persist function to
    remember. The persist functions no longer receive `source_context` at all,
    so a new one cannot reach for the target's digest by habit: the only source
    identity in scope is the one this returns.
    """

    if "source" not in step.spec:
        return {
            "artifact_id": str(draft.target["artifact_id"]),
            "node_ref": str(draft.target["node_ref"]),
            "sha256": str(source_context["source_sha256"]),
        }
    produced = _committed_source_binding(
        step, previous, str(draft.target["run_id"])
    )
    return {
        "artifact_id": str(produced["artifact_id"]),
        "node_ref": str(produced["node_ref"]),
        "sha256": str(produced["content_sha256"]),
    }


def _resolve_committed_source_frame(
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
    root: Path,
    *,
    workflow_run_id: str,
) -> pd.DataFrame:
    """Load the dataset the upstream step actually persisted."""

    commitment = step.spec["source"]
    from_step = str(commitment["from_step"])
    produced = _committed_source_binding(step, previous, workflow_run_id)
    context, frame = resolve_statistical_source(
        root,
        source_run_id=str(produced["run_id"]),
        source_node_id=str(produced["node_ref"]),
        source_artifact_id=str(produced["artifact_id"]),
    )
    # Execution-time half of the guarantee: compare the bytes that actually
    # arrived against the bytes the upstream step published. Comparing step
    # fingerprints here would look like a check and never fire -- the binding
    # carries the producing step's own fingerprint, so both sides are the same
    # value no matter which artifact the binding points at.
    if str(produced["content_sha256"]) != str(context["source_sha256"]):
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} resolved to different "
            "content than the completed step published"
        )
    return frame


def _ensure_runtime_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> None:
    evidence_port, _receipt, draft, _step = _require_active_write_context()
    run_id = _require_workflow_opaque_ref(
        draft.target.get("run_id"), "workflow target run_id"
    )
    expected_run_root = evidence_port.project_root / "runs" / run_id
    if run_root != expected_run_root:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_PATH_CHANGED: runtime artifact root is not the admitted target run"
        )
    _artifact_path_without_following(evidence_port.project_root, run_id, path)
    pending = _PENDING_RUNTIME_OUTPUTS.get() or {}
    pending_item = pending.pop(str(path), None)
    output_target = pending_item[0] if pending_item is not None else None
    if output_target is None:
        output_target = prepare_formal_workflow_output(
            evidence_port,
            _receipt,
            run_root=run_root,
            directory_name=path.relative_to(run_root).parent.as_posix()
            if path.relative_to(run_root).parent != Path(".")
            else ".",
            filename=path.name,
        )
    try:
        evidence_port.record_formal_artifact(
            evidence_port,
            _receipt,
            run_root=run_root,
            artifact_id=artifact_id,
            path=path,
            artifact_type=artifact_type,
            producer_step=step,
            inputs=inputs,
            output_target=output_target,
        )
    finally:
        output_target.close()


def _persist_numeric_derivation(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    frame: pd.DataFrame,
    step: Any,
) -> WorkflowStepResult:
    """Persist a derived dataset + recipe and add one visible graph child."""

    _require_active_write_context()

    derived, summaries = _apply_numeric_recipes(frame, step.spec["recipes"])
    # The output is written into the workflow's target run regardless of which
    # dataset it derives from; only the lineage references follow the real
    # source. `_lineage_source` refuses a binding from any other run, so the
    # parent node named below always exists in the graph mutated here.
    source_run_id = str(draft.target["run_id"])
    run_root = root / "runs" / source_run_id
    result_fingerprint = str(step.fingerprint)
    fingerprint = result_fingerprint.replace(":", "_")
    relative_dir = Path("derived") / "workflow_numeric" / fingerprint
    data_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    recipe = {
        "schema_version": _NUMERIC_DERIVATION_SCHEMA,
        "workflow_id": draft.workflow_id,
        "workflow_step_id": str(step.step_id),
        "workflow_step_fingerprint": result_fingerprint,
        "source": {
            "artifact_id": lineage["artifact_id"],
            "sha256": lineage["sha256"],
        },
        "recipes": [dict(recipe) for recipe in step.spec["recipes"]],
        "result": {"path": data_rel, "output_columns": summaries},
    }
    serialized_data = derived.to_csv(index=False)
    recipe_path = _write_runtime_artifact_json(
        run_root,
        Path(recipe_rel),
        recipe,
        occupied_message="numeric derivation recipe path is occupied",
        retain_for_registry=True,
    )
    data_path = _write_runtime_artifact_bytes(
        run_root,
        Path(data_rel),
        serialized_data.encode("utf-8"),
        occupied_message="numeric derivation data path is occupied",
        retain_for_registry=True,
    )
    data_artifact_id = f"workflow_derived_numeric_{fingerprint[:24]}"
    recipe_artifact_id = f"workflow_derived_numeric_recipe_{fingerprint[:24]}"
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type="derived_data",
        step="workflow.derive_numeric",
        inputs=[lineage["artifact_id"]],
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="workflow.derive_numeric",
        inputs=[lineage["artifact_id"], data_artifact_id],
    )
    child_node_id = f"data-derive-numeric:{fingerprint[:24]}"
    branch_id = f"workflow-numeric:{fingerprint[:20]}"
    source_node_id = lineage["node_ref"]

    def add_child(graph: Graph) -> Graph:
        if child_node_id in graph.nodes:
            return graph
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label="Derived numeric columns",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=source_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=(
                f"{len(summaries)} declared numeric transform(s); "
                f"{len(derived)} rows"
            ),
            annotations=(
                {
                    "type": "workflow_numeric_derivation",
                    "workflow_id": draft.workflow_id,
                    "workflow_step_id": str(step.step_id),
                    "recipe_path": recipe_rel,
                },
            ),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=source_node_id,
                    target_id=child_node_id,
                    op="workflow.derive_numeric",
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=source_node_id,
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(source_run_id, add_child)
    data_sha256 = sha256_file(data_path)
    node_index_relative = Path("node_index.json")
    node_index = _read_runtime_artifact_json(
        run_root, node_index_relative, missing={}
    )
    if not isinstance(node_index, Mapping):
        raise WorkflowExecutionError("numeric derivation node index is not an object")
    entry = {
        "node_hash": data_sha256,
        "producing_stage": "workflow.derive_numeric",
        "cas_ref": {"node_hash": data_sha256, "artifact": data_rel},
    }
    existing = node_index.get(child_node_id)
    if existing is not None and existing != entry:
        raise WorkflowExecutionError("numeric derivation node identity is not deterministic")
    if existing is None:
        _write_runtime_artifact_json(
            run_root,
            node_index_relative,
            {**node_index, child_node_id: entry},
            occupied_message="numeric derivation node identity is not deterministic",
        )
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, recipe_artifact_id],
        row_counts={item["output_name"]: item["nonmissing_count"] for item in summaries},
        result_fingerprint=fingerprint,
        payload={
            "output_columns": summaries,
            # The standard binding a later step commits to consuming. Every
            # dataset-producing step publishes this exact shape, so resolution
            # never branches on which operation produced the input.
            "produced_dataset": {
                "schema_version": _PRODUCED_DATASET_SCHEMA,
                "run_id": source_run_id,
                "node_ref": child_node_id,
                "artifact_id": data_artifact_id,
                # The two hashes are not interchangeable. content_sha256 digests
                # the bytes on disk, so a consumer comparing it against what it
                # actually read detects a binding that points at the wrong
                # artifact, or a run directory rewritten between resumes.
                # result_fingerprint is the producing step's own fingerprint and
                # is provenance only: a consumer that re-derives it from the same
                # step record is comparing a value against itself, which no input
                # can falsify. Verify with content_sha256, attribute with this.
                "content_sha256": data_sha256,
                "dataset_kind": "derived_data",
                "result_fingerprint": fingerprint,
            },
        },
    )


def _persist_workflow_dataset_frame(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
    dataset_label: str,
    producer_step: str,
    summary: Mapping[str, Any],
) -> WorkflowStepResult:
    """Persist one prepared frame and publish the standard source binding."""

    _require_active_write_context()

    source_run_id = str(draft.target["run_id"])
    run_root = root / "runs" / source_run_id
    result_fingerprint = str(step.fingerprint)
    fingerprint = result_fingerprint.replace(":", "_")
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", dataset_label)
    relative_dir = Path("derived") / "workflow_datasets" / fingerprint[:24]
    data_rel = (relative_dir / f"{safe_label}.parquet").as_posix()
    metadata_rel = (relative_dir / f"{safe_label}.json").as_posix()
    serialized = frame.to_parquet(index=False)
    data_path = _write_runtime_artifact_bytes(
        run_root,
        Path(data_rel),
        serialized,
        occupied_message=f"{producer_step} dataset path is occupied by different content",
        retain_for_registry=True,
    )
    metadata = {
        "schema_version": "workflow-prepared-dataset.v1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": str(step.step_id),
        "workflow_step_fingerprint": result_fingerprint,
        "producer": producer_step,
        "source": {
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
        },
        "summary": dict(summary),
        "row_count": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "data_path": data_rel,
    }
    metadata_path = _write_runtime_artifact_json(
        run_root,
        Path(metadata_rel),
        metadata,
        occupied_message=f"{producer_step} metadata path is occupied by different content",
        retain_for_registry=True,
    )
    data_artifact_id = f"workflow_{safe_label}_{fingerprint[:24]}"
    metadata_artifact_id = f"workflow_{safe_label}_metadata_{fingerprint[:24]}"
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type="derived_data",
        step=producer_step,
        inputs=[str(lineage["artifact_id"])],
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="metadata",
        step=producer_step,
        inputs=[str(lineage["artifact_id"]), data_artifact_id],
    )
    child_node_id = f"data-{safe_label}:{fingerprint[:24]}"
    branch_id = f"workflow-{safe_label}:{fingerprint[:20]}"
    source_node_id = str(lineage["node_ref"])

    def add_child(graph: Graph) -> Graph:
        existing = graph.nodes.get(child_node_id)
        if existing is not None:
            if existing.payload_ref != data_rel or existing.parent_stage_id != source_node_id:
                raise WorkflowExecutionError(
                    f"{producer_step} graph child identity is not deterministic"
                )
            return graph
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=f"{dataset_label.title()} dataset",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=source_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=f"{producer_step}: {len(frame)} rows",
            annotations=(
                {
                    "type": "workflow_prepared_dataset",
                    "producer": producer_step,
                    "workflow_id": draft.workflow_id,
                    "workflow_step_id": str(step.step_id),
                    "metadata_path": metadata_rel,
                },
            ),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=source_node_id,
                    target_id=child_node_id,
                    op=producer_step,
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=source_node_id,
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(source_run_id, add_child)
    data_sha256 = sha256_file(data_path)
    node_index_relative = Path("node_index.json")
    node_index = _read_runtime_artifact_json(
        run_root, node_index_relative, missing={}
    )
    if not isinstance(node_index, Mapping):
        raise WorkflowExecutionError(f"{producer_step} node index is not an object")
    entry = {
        "node_hash": data_sha256,
        "producing_stage": producer_step,
        "cas_ref": {"node_hash": data_sha256, "artifact": data_rel},
    }
    existing = node_index.get(child_node_id)
    if existing is not None and existing != entry:
        raise WorkflowExecutionError(
            f"{producer_step} node identity is not deterministic"
        )
    if existing is None:
        _write_runtime_artifact_json(
            run_root,
            node_index_relative,
            {**node_index, child_node_id: entry},
            occupied_message=f"{producer_step} node identity is not deterministic",
        )
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, metadata_artifact_id],
        row_counts={"source": int(len(frame))},
        result_fingerprint=result_fingerprint,
        payload={
            "summary": dict(summary),
            "produced_dataset": {
                "schema_version": _PRODUCED_DATASET_SCHEMA,
                "run_id": source_run_id,
                "node_ref": child_node_id,
                "artifact_id": data_artifact_id,
                "content_sha256": data_sha256,
                "dataset_kind": "derived_data",
                "result_fingerprint": result_fingerprint,
            },
        },
    )


def _exploration_spec(spec: Mapping[str, Any]) -> ExplorationSpec:
    return ExplorationSpec(
        operation=str(spec["operation"]),
        selected_columns=tuple(str(item) for item in spec.get("selected_columns", [])),
        filters=tuple(
            FilterSpec(
                column=str(item["column"]),
                operator=str(item["operator"]),
                value=item.get("value"),
            )
            for item in spec.get("filters", [])
        ),
        options=dict(spec.get("options") or {}),
        derived_definitions=tuple(spec.get("derived_definitions") or []),
    )


def _record_artifact_ids(record: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("artifact_id", "transcript_artifact_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            ids.append(value)
    for value in record.get("exports", []) or []:
        if isinstance(value, Mapping) and isinstance(value.get("artifact_id"), str):
            ids.append(value["artifact_id"])
    for key in ("derived", "plot"):
        value = record.get(key)
        if isinstance(value, Mapping):
            for nested_key in ("artifact_id", "recipe_artifact_id"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested:
                    ids.append(nested)
    return list(dict.fromkeys(ids))


def _result_from_artifact_ids(
    run_root: Path, artifact_ids: list[str] | tuple[str, ...]
) -> dict[str, Any] | None:
    """Read a step's result block back off disk, or None if it holds none.

    Returning None rather than raising, because the caller is searching a
    dependency chain rather than fetching one known artifact. A dataset
    producer upstream carries a CSV and a recipe and no result block at all --
    a legitimate shape now that a step can declare another step's output as its
    source, which puts that producer in its `depends_on`. Aborting here would
    end the search at the first such dependency instead of continuing to the
    step that does hold the evidence; the caller still refuses when the whole
    chain yields nothing.
    """

    index = _read_artifacts_index(run_root)
    wanted = set(artifact_ids)
    for item in index.get("artifacts", []):
        if item.get("artifact_id") not in wanted:
            continue
        path = run_root / str(item.get("path", ""))
        # Only JSON documents can carry a result block; a derived data.csv read
        # as JSON is a decode error, not an answer.
        if path.is_file() and path.suffix == ".json":
            payload = read_json(path)
            if isinstance(payload, Mapping) and isinstance(payload.get("result"), Mapping):
                return dict(payload["result"])
    return None


def _detail_result(
    previous: Mapping[str, WorkflowStepResult],
    run_root: Path,
    depends_on: tuple[str, ...] | list[str],
    dependency_graph: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Find the percentile evidence this step transitively depends on.

    Resolved through the dependency graph rather than a fixed step id. The
    search is transitive because a plan may legitimately route the evidence
    through an intermediate step — a live agent composed exactly that shape:
    the group comparison depended on the derivation, which depended on the
    detail statistics. Requiring a direct edge would reject a correct plan.
    """

    visited: set[str] = set()
    frontier = list(depends_on)
    while frontier:
        step_id = frontier.pop(0)
        if step_id in visited:
            continue
        visited.add(step_id)
        if dependency_graph is not None:
            frontier.extend(dependency_graph.get(step_id, ()))
        cached = previous.get(step_id)
        if cached is None:
            continue
        result = (
            dict(cached.payload["result"])
            if isinstance(cached.payload.get("result"), Mapping)
            else _result_from_artifact_ids(run_root, cached.artifact_ids)
        )
        if result is None:
            continue
        variables = result.get("variables")
        if isinstance(variables, Mapping) and any(
            isinstance(entry, Mapping) and "percentiles" in entry
            for entry in variables.values()
        ):
            return result, step_id, cached.result_fingerprint or ""
    raise WorkflowExecutionError(
        "no dependency of this step provides percentile evidence: "
        + ", ".join(visited)
    )


def _result_row_counts(result: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "source": int(result.get("source_row_count", 0) or 0),
        "filtered": int(result.get("filtered_row_count", 0) or 0),
    }
    if isinstance(result.get("groups"), list):
        counts["groups"] = len(result["groups"])
    if result.get("correlation_n") is not None:
        counts["correlation_n"] = int(result["correlation_n"])
    return counts


def _persist_workflow_exploration(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    *,
    spec: ExplorationSpec,
    result: Mapping[str, Any],
    frame: pd.DataFrame,
) -> tuple[dict[str, Any], str]:
    """The single place a workflow exploration record names its source.

    Four dispatch branches persist exploration records -- the plain explore,
    the plots explore, derive_boolean and derived_group_summarize -- and each
    used to spell out `draft.target` for itself. Four copies of a source
    reference is four chances to write the wrong one, and the numbers stay
    right when it happens, so nothing complains.

    The fingerprint is derived from the same digest, which is not decoration:
    it is the record's identity on disk. Keying it on the target while
    computing from a derived dataset makes two different explorations collide
    on one artifact path.
    """

    _require_active_write_context()
    fingerprint = exploration_fingerprint(str(lineage["sha256"]), spec)
    record = persist_exploration(
        root,
        source_run_id=str(draft.target["run_id"]),
        source_node_id=str(lineage["node_ref"]),
        source_artifact_id=str(lineage["artifact_id"]),
        source_sha256=str(lineage["sha256"]),
        spec=spec,
        result=dict(result),
        fingerprint=fingerprint,
        source_frame=frame,
    )
    _admit_persisted_workflow_artifacts(root, draft, record)
    return record, fingerprint


def _admit_persisted_workflow_artifacts(
    root: Path,
    draft: WorkflowDraft,
    record: Mapping[str, Any],
) -> None:
    """Bind legacy exploration persistence to the active server registry.

    The statistical exploration service predates the receipt-gated workflow
    port and still writes its JSON/index records through its own helper. A
    workflow callback may consume those files only after the current server
    admission has frozen the exact indexed path and digest. Existing formal
    writers and runtime producers may already have inserted their row; those
    rows are revalidated rather than duplicated with a weaker shape.
    """

    evidence_port, receipt, active_draft, _active_step = _require_active_write_context()
    if active_draft is not draft:
        raise WorkflowExecutionError(
            "WORKFLOW_ADMISSION_MISMATCH: persisted exploration is outside the active workflow"
        )
    run_id = _require_workflow_opaque_ref(
        draft.target.get("run_id"), "workflow exploration run_id"
    )
    run_root = root / "runs" / run_id
    try:
        index = _read_artifacts_index(run_root)
    except (OSError, TypeError, ValueError, WorkbenchAPIError) as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: exploration artifact registry is unavailable"
        ) from exc
    for artifact_id in _record_artifact_ids(record):
        matching = [
            item
            for item in index.get("artifacts", [])
            if isinstance(item, Mapping) and item.get("artifact_id") == artifact_id
        ]
        if len(matching) != 1:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: exploration artifact is not uniquely registered"
            )
        index_record = matching[0]
        relative_value = index_record.get("path")
        if not isinstance(relative_value, str) or not relative_value:
            raise WorkflowExecutionError(
                "WORKFLOW_ARTIFACT_REGISTRY_REQUIRED: exploration artifact path is invalid"
            )
        path = run_root / relative_value
        key = (receipt.receipt_id, run_id, artifact_id)
        existing = evidence_port._server_artifact_registry.get(key)
        if existing is None:
            evidence_port._record_server_artifact(
                receipt,
                run_id=run_id,
                artifact_id=artifact_id,
                record=index_record,
                path=path,
            )
        else:
            evidence_port._validate_server_artifact_snapshot(
                existing, receipt=receipt
            )


def _exploration_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    spec: ExplorationSpec,
    frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    _require_active_write_context()
    evaluated_frame = source_frame if frame is None else frame
    result = execute_exploration(evaluated_frame, spec)
    record, fingerprint = _persist_workflow_exploration(
        root, draft, lineage, spec=spec, result=result, frame=evaluated_frame
    )
    return WorkflowStepResult(
        artifact_ids=_record_artifact_ids(record),
        row_counts=_result_row_counts(result),
        empty_group_values=list(result.get("empty_group_values", [])),
        result_fingerprint=fingerprint,
        payload={"result": result, "record": record},
    )


def _persist_data_management_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
) -> WorkflowStepResult:
    """Execute every declared P4 data producer through one service adapter."""
    _require_active_write_context()
    operation_id = str(step.operation_id)
    operation = operation_id.removeprefix("data.")
    source_run_id = str(draft.target["run_id"])
    source_node_id = str(lineage["node_ref"])
    source_artifact_id = str(lineage["artifact_id"])
    run_root = root / "runs" / source_run_id
    execution_key = f"exec_{step.fingerprint}"
    if operation == "feature_recipe":
        recipe = FeatureRecipeV1(
            recipe_id=str(step.spec["recipe_id"]),
            operation_id=str(step.spec["recipe_operation_id"]),
            operation_version=1,
            inputs=tuple(str(item) for item in step.spec["inputs"]),
            outputs=(str(step.spec["output"]),),
            output_types=(str(step.spec.get("output_type", "numeric")),),
            parameters=dict(step.spec["parameters"]),
            fit_scope=str(step.spec.get("fit_scope", "stateless")),
            source_artifact=source_artifact_id,
            lineage_parent=source_node_id,
            missing_policy=str(step.spec.get("missing_policy", "fail_closed")),
            outlier_policy=str(step.spec.get("outlier_policy", "preserve")),
        )
        typed_spec = FeatureRecipeOperationSpecV1(
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            recipe=recipe,
        )
        preview = preview_feature_recipe(root, typed_spec)
        effect = apply_feature_recipe_operation(
            root, typed_spec, preview, execution_key_value=execution_key
        )
        output_columns = list(preview.output_columns)
        row_count_before = preview.row_count
        row_count_after = preview.row_count
        fingerprint = preview.fingerprint
    else:
        parameters = {
            key: value
            for key, value in step.spec.items()
            if key
            not in {
                "secondary_run_id",
                "secondary_node_id",
                "secondary_artifact_id",
                "source_artifact_fingerprint",
                "source",
            }
        }
        typed_spec = DataTransformSpecV1(
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            operation=operation,
            parameters=parameters,
            secondary_run_id=step.spec.get("secondary_run_id"),
            secondary_node_id=step.spec.get("secondary_node_id"),
            secondary_artifact_id=step.spec.get("secondary_artifact_id"),
        )
        preview = preview_data_transform(root, typed_spec)
        effect = apply_data_transform(
            root, typed_spec, preview, execution_key_value=execution_key
        )
        output_columns = list(preview.output_columns)
        row_count_before = preview.row_count_before
        row_count_after = preview.row_count_after
        fingerprint = preview.fingerprint
    data_path = run_root / effect.artifact_path
    if not data_path.is_file():
        raise WorkflowExecutionError(
            f"{operation_id} service returned a missing persisted dataset: {effect.artifact_path}"
        )
    content_sha256 = sha256_file(data_path)
    return WorkflowStepResult(
        artifact_ids=[effect.artifact_id, effect.recipe_artifact_id],
        row_counts={"source": int(row_count_before), "output": int(row_count_after)},
        result_fingerprint=fingerprint,
        payload={
            "operation_id": operation_id,
            "output_columns": output_columns,
            "produced_dataset": {
                "schema_version": _PRODUCED_DATASET_SCHEMA,
                "run_id": source_run_id,
                "node_ref": effect.child_node_id,
                "artifact_id": effect.artifact_id,
                "content_sha256": content_sha256,
                "dataset_kind": "derived_data",
                "result_fingerprint": fingerprint,
            },
        },
    )
def _execute_named_statistical_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    _require_active_write_context()
    from ..statistical_tests import run_named_statistical_test
    family = str(step.operation_id).removeprefix("test.")
    result = run_named_statistical_test(
        frame,
        family=family,
        analysis_columns=list(step.spec["analysis_columns"]),
        dataset_sha256=str(lineage["sha256"]),
        lineage_parent=str(lineage["artifact_id"]),
        reference_means=step.spec.get("reference_means"),
        paired_columns=[tuple(pair) for pair in step.spec.get("paired_columns", []) or []],
    )
    run_root = root / "runs" / str(draft.target["run_id"])
    fingerprint = str(step.fingerprint).replace(":", "_")
    artifact_id = f"statistical_tests_named_{family}_{fingerprint[:24]}"
    relative = Path("statistical_tests") / f"{artifact_id}.json"
    envelope = {
        "payload_schema": "workbench.statistical_tests.named-family",
        "schema_version": 1,
        "artifact_id": artifact_id,
        "execution_mode": "named",
        "source": {
            "artifact_id": str(lineage["artifact_id"]),
            "node_ref": str(lineage["node_ref"]),
            "sha256": str(lineage["sha256"]),
        },
        "result": result,
    }
    path = _write_runtime_artifact_json(
        run_root,
        relative,
        envelope,
        occupied_message=f"named statistical artifact {artifact_id} is not deterministic",
        retain_for_registry=True,
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=artifact_id,
        path=path,
        artifact_type="statistical_test",
        step=f"test.{family}",
        inputs=[str(lineage["artifact_id"])],
    )
    return WorkflowStepResult(
        artifact_ids=[artifact_id],
        row_counts={"results": int(len(result.get("results", [])))},
        result_fingerprint=str(step.fingerprint),
        payload={"result": result, "execution_mode": "named"},
    )
def _execute_imputation_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    _require_active_write_context()
    if step.operation_id != "imputation.mice":
        raise WorkflowExecutionError(
            f"{step.operation_id} has no registered imputation owner"
        )
    from ..imputation import run_mice_imputation
    run_root = root / "runs" / str(draft.target["run_id"])
    summary = run_mice_imputation(
        frame,
        run_root,
        list(step.spec["columns"]),
        m=int(step.spec.get("m", 5)),
        max_iter=int(step.spec.get("max_iter", 10)),
        random_seed=int(step.spec.get("random_seed", 20260429)),
        max_missing_rate=float(step.spec.get("max_missing_rate", 0.4)),
    )
    skipped = list(summary.get("skipped_columns", []))
    if skipped:
        raise WorkflowExecutionError(
            "imputation.mice refused to silently drop declared column(s): "
            + ", ".join(str(column) for column in skipped)
        )
    if summary.get("status") != "completed":
        raise WorkflowExecutionError(
            "imputation.mice did not produce a changed dataset; inspect the "
            "persisted MICE summary before retrying"
        )
    imputed_path = run_root / "processed" / "imputed_dataset.parquet"
    if not imputed_path.is_file():
        raise WorkflowExecutionError(
            "imputation.mice reported completion without its imputed_dataset artifact"
        )
    imputed = pd.read_parquet(imputed_path)
    return _persist_workflow_dataset_frame(
        root=root,
        draft=draft,
        lineage=lineage,
        step=step,
        frame=imputed,
        dataset_label="imputation_mice",
        producer_step="imputation.mice",
        summary=summary,
    )
def _execute_resampling_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    _require_active_write_context()
    method = str(step.operation_id).removeprefix("resample.")
    from ..prediction import build_sampler
    target = str(step.spec["target_column"])
    features = [str(column) for column in step.spec["feature_columns"]]
    missing = [column for column in [target, *features] if column not in frame.columns]
    if missing:
        raise WorkflowExecutionError(
            f"{step.operation_id} source columns are missing: " + ", ".join(missing)
        )
    selected = frame[[*features, target]].copy()
    if selected.isna().any().any():
        raise WorkflowExecutionError(
            f"{step.operation_id} refuses missing target/features; impute first"
        )
    sampler = build_sampler(
        method,
        model_type="prediction_resampling",
        random_seed=int(step.spec.get("random_seed", 0)),
    )
    if sampler is None:
        raise WorkflowExecutionError(
            f"{step.operation_id} did not resolve a sampler; no-op resampling is forbidden"
        )
    x_resampled, y_resampled = sampler.fit_resample(
        selected[features], selected[target]
    )
    output = pd.DataFrame(x_resampled, columns=features)
    output[target] = y_resampled
    if output.empty:
        raise WorkflowExecutionError(f"{step.operation_id} produced an empty training dataset")
    return _persist_workflow_dataset_frame(
        root=root,
        draft=draft,
        lineage=lineage,
        step=step,
        frame=output,
        dataset_label=f"resample_{method}",
        producer_step=step.operation_id,
        summary={
            "method": method,
            "source_row_count": int(len(frame)),
            "output_row_count": int(len(output)),
            "target_column": target,
            "feature_columns": features,
        },
    )
def _execute_prediction_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    _require_active_write_context()
    from ..prediction import run_prediction_model_v186
    from ..predictive_research.contracts import SamplingSpecV1
    model_type = str(step.operation_id).removeprefix("prediction.")
    sampling_value = step.spec.get("sampling")
    sampling = None
    if sampling_value is not None:
        try:
            sampling = SamplingSpecV1(**dict(sampling_value))
        except (TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                f"{step.operation_id} sampling does not match SamplingSpecV1"
            ) from exc
    fingerprint = str(step.fingerprint).replace(":", "_")
    model_id = f"workflow_{model_type}_{fingerprint[:24]}"
    run_root = root / "runs" / str(draft.target["run_id"])
    result = run_prediction_model_v186(
        frame,
        run_root,
        y=str(step.spec["y"]),
        x=[str(column) for column in step.spec["x"]],
        model_type=model_type,
        model_id=model_id,
        final_holdout_fraction=float(step.spec["final_holdout_fraction"]),
        cv_folds=int(step.spec["cv_folds"]),
        shuffle=bool(step.spec["shuffle"]),
        random_seed=int(step.spec["random_seed"]),
        data_structure=str(step.spec["data_structure"]),
        entity_column=step.spec.get("entity_column"),
        group_column=step.spec.get("group_column"),
        time_column=step.spec.get("time_column"),
        sampling=sampling,
        inputs=[str(lineage["artifact_id"])],
        imputation_method=step.spec.get("imputation_method"),
        imputation_max_iter=int(step.spec.get("imputation_max_iter", 10)),
        imputation_max_missing_rate=float(
            step.spec.get("imputation_max_missing_rate", 0.4)
        ),
    )
    records = _read_artifacts_index(run_root).get("artifacts", [])
    artifact_ids = [
        str(item["artifact_id"])
        for item in records
        if isinstance(item.get("artifact_id"), str)
        and (
            item["artifact_id"] == model_id
            or item["artifact_id"].startswith(f"{model_id}_")
        )
    ]
    if not artifact_ids:
        raise WorkflowExecutionError(
            f"{step.operation_id} completed without registered prediction artifacts"
        )
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": int(len(frame))},
        result_fingerprint=str(step.fingerprint),
        payload={"result": result, "model_type": model_type, "source": dict(lineage)},
    )
class _WorkflowPackRecorder:
    """No-op recorder for pack-owned evidence; workflow lineage is separate."""
    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None
def _execute_time_series_recipe(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    _require_active_write_context()
    recipe_id = str(step.operation_id).removeprefix("model.")
    options = dict(step.spec["model_options"])
    if recipe_id == "time_series.arma_garch":
        options["dataset_ref"] = str(lineage["artifact_id"])
        from ..engine.packs.arma_garch.runner import fit_from_context
    elif recipe_id == "time_series.ets":
        from ..engine.packs.ets.runner import fit_from_context
    else:
        raise WorkflowExecutionError(f"{step.operation_id} has no registered Recipe owner")
    from ..engine.context import DataHandle, ModelingContext, RunEnv
    source_artifact = str(lineage["artifact_id"])
    context = ModelingContext(
        data=DataHandle.of(
            frame,
            artifact_id=source_artifact,
            provenance=(source_artifact,),
        ),
        y_col=str(options.get("value_column", "")),
        x_cols=[],
        requested_model_type=recipe_id,
        artifacts={
            "_model_options": options,
            "_frames": {source_artifact: frame},
            "_raw_inputs": [source_artifact],
            "_upload_hash": str(lineage["sha256"]),
        },
    )
    run_root = root / "runs" / str(draft.target["run_id"])
    env = RunEnv(
        run_root=run_root,
        run_id=str(draft.target["run_id"]),
        recorder=_WorkflowPackRecorder(),
    )
    model_id, result, _fitted = fit_from_context(context, env)
    artifact_ids: list[str]
    if recipe_id == "time_series.ets":
        fingerprint = str(step.fingerprint).replace(":", "_")
        artifact_id = f"workflow_{recipe_id.replace('.', '_')}_{fingerprint[:24]}"
        relative = Path("artifacts") / "time_series" / f"{artifact_id}.json"
        envelope = {
            "artifact_id": artifact_id,
            "payload_schema": "workbench.recipe.time_series.ets",
            "schema_version": 1,
            "model_id": model_id,
            "source": dict(lineage),
            "result": result,
        }
        path = _write_runtime_artifact_json(
            run_root,
            relative,
            envelope,
            occupied_message=f"{step.operation_id} result artifact is not deterministic",
            retain_for_registry=True,
        )
        _ensure_runtime_artifact(
            run_root,
            artifact_id=artifact_id,
            path=path,
            artifact_type="model_result",
            step=step.operation_id,
            inputs=[source_artifact],
        )
        artifact_ids = [artifact_id]
    else:
        records = _read_artifacts_index(run_root).get("artifacts", [])
        artifact_ids = [
            str(item["artifact_id"])
            for item in records
            if isinstance(item.get("artifact_id"), str)
            and item["artifact_id"].startswith("ts.")
            and item.get("step") == "arma_garch"
        ]
        if "ts.artifact_manifest" not in artifact_ids:
            raise WorkflowExecutionError(
                "time_series.arma_garch owner returned without ts.artifact_manifest"
            )
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": int(len(frame))},
        result_fingerprint=str(step.fingerprint),
        payload={
            "recipe_id": recipe_id,
            "model_id": model_id,
            "result": result,
            "source": dict(lineage),
        },
    )
def _execute_model_auto(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
    admission_receipt: WorkflowAdmissionReceipt,
    evidence_port: EvidencePersistencePort,
) -> WorkflowStepResult:
    _require_active_write_context()
    from ..engine.packs.loader import bootstrap_builtin_packs
    from ..engine.registry import DEFAULT_BY_Y_TYPE
    from ..router import detect_y_kind
    outcomes = {
        str(branch["outcome"])
        for branch in step.spec.get("branches", [])
        if isinstance(branch, Mapping) and branch.get("outcome")
    }
    if len(outcomes) != 1:
        raise WorkflowExecutionError(
            "model.auto requires exactly one target column across its branches"
        )
    outcome = next(iter(outcomes))
    if outcome not in frame.columns:
        raise WorkflowExecutionError(
            f"model.auto target column is missing from the resolved frame: {outcome}"
        )
    bootstrap_builtin_packs()
    y_type = detect_y_kind(frame, outcome).value
    resolved_family = DEFAULT_BY_Y_TYPE.get(y_type)
    if not isinstance(resolved_family, str) or not resolved_family:
        raise WorkflowExecutionError(
            f"model.auto has no registered model family for target type {y_type!r}"
        )
    resolved_spec = {**step.spec, "model_family": resolved_family}
    resolved_step = replace(step, spec=resolved_spec)
    result = _execute_model_genesis_branches(
        root,
        draft,
        lineage,
        frame,
        resolved_step,
        raw_source_frame=frame,
        admission_receipt=admission_receipt,
        evidence_port=evidence_port,
    )
    return WorkflowStepResult(
        artifact_ids=list(result.artifact_ids),
        row_counts=dict(result.row_counts),
        empty_group_values=list(result.empty_group_values),
        result_fingerprint=result.result_fingerprint,
        payload={
            **result.payload,
            "resolved_model_family": resolved_family,
            "resolved_y_type": y_type,
        },
        lineage=dict(result.lineage),
    )


class _ReceiptGatedWorkflowExecutor:
    """Internal callback facade that cannot execute without an admission."""

    def __init__(self, callback, draft: WorkflowDraft) -> None:
        self._callback = callback
        self._draft = draft
        self._evidence_port: EvidencePersistencePort | None = None

    def _bind_evidence_port(self, evidence_port: EvidencePersistencePort) -> None:
        if type(evidence_port) is not EvidencePersistencePort:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_PORT_REQUIRED: callback requires the server evidence port"
            )
        if self._evidence_port is not None and self._evidence_port is not evidence_port:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_PORT_REQUIRED: callback is bound to another evidence port"
            )
        self._evidence_port = evidence_port

    def __call__(
        self,
        step: WorkflowStep,
        previous: Mapping[str, WorkflowStepResult],
        *,
        admission_receipt: WorkflowAdmissionReceipt | None = None,
    ) -> WorkflowStepResult:
        if self._evidence_port is None or type(admission_receipt) is not WorkflowAdmissionReceipt:
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: write-capable workflow callback requires an admission receipt"
            )
        self._evidence_port.require_receipt(admission_receipt)
        if (
            admission_receipt.workflow_id != self._draft.workflow_id
            or admission_receipt.step_id != step.step_id
            or admission_receipt.step_fingerprint != step.fingerprint
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_ADMISSION_MISMATCH: callback receipt is not bound to this step"
            )
        self._evidence_port.validate_execution_snapshot(
            admission_receipt,
            self._draft,
            step,
        )
        context_token = _WRITE_CONTEXT.set(
            (self._evidence_port, admission_receipt, self._draft, step)
        )
        pending_token = _PENDING_RUNTIME_OUTPUTS.set({})
        try:
            result = self._callback(
                step,
                previous,
                admission_receipt=admission_receipt,
                evidence_port=self._evidence_port,
            )
            if not isinstance(result, WorkflowStepResult):
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_RESULT_REQUIRED: workflow callback returned an invalid typed result"
                )
            self._evidence_port.admit_result_artifacts(admission_receipt, result)
            return result
        finally:
            pending = _PENDING_RUNTIME_OUTPUTS.get() or {}
            for output_target, _destination_existed in list(pending.values()):
                try:
                    output_target.rollback_committed()
                finally:
                    output_target.close()
            _PENDING_RUNTIME_OUTPUTS.reset(pending_token)
            _WRITE_CONTEXT.reset(context_token)


def build_workflow_step_executor(
    project_root: Path | str,
    draft: WorkflowDraft,
    *,
    custom_step_executor=None,
    evidence_port: EvidencePersistencePort | None = None,
):
    """Return one callback that dispatches only the compiled step identities.

    ``model.custom`` is intentionally an injected gateway.  The default
    runtime has no authority to reserve, spawn, or dispatch it; the caller
    must supply a gateway that has already joined Proposal/Risk authorization,
    the exact binding, and the B1 broker.
    """

    root = Path(project_root).expanduser().resolve()
    if evidence_port is not None:
        evidence_port.require_server_host()
    source_context, source_frame = resolve_statistical_source(
        root,
        source_run_id=str(draft.target["run_id"]),
        source_node_id=str(draft.target["node_ref"]),
        source_artifact_id=str(draft.target["artifact_id"]),
    )
    source_run_root = root / "runs" / str(draft.target["run_id"])
    dependency_graph = {item.step_id: item.depends_on for item in draft.steps}

    def execute(
        step,
        previous: Mapping[str, WorkflowStepResult],
        *,
        admission_receipt: WorkflowAdmissionReceipt,
        evidence_port: EvidencePersistencePort,
    ) -> WorkflowStepResult:
        # Dispatch on the declared operation identity, never on a step number:
        # a plan with a different shape or length must run on the same runtime.
        operation_id = step.operation_id
        dispatcher_key = workflow_dispatcher_key(operation_id)
        step_frame = _workflow_input_frame(
            source_frame, draft, step, dependency_graph, previous, root
        )
        # Resolved here, beside the frame, so the data a step reads and the
        # source its output claims come from one decision. `source_context` is
        # deliberately not forwarded past this point: every branch below
        # receives `lineage` and nothing else that could name the target.
        lineage = _lineage_source(draft, step, source_context, previous)
        if dispatcher_key == "workbench.agent.workflow_runtime.p7_pack":
            from .p7_pack_registry import p7_pack_registry

            operation = p7_pack_registry.get(operation_id)
            request = {
                "operation_id": operation_id,
                "input_mode": step.spec.get("input_mode"),
                "column_bindings": step.spec.get("column_bindings"),
                "options": step.spec.get("options"),
            }
            try:
                operation.preflight(step_frame, request)
                result = operation.execute(step_frame, request)
                operation.validate_result(result)
                result_status, result_details = _p7_result_status(result)
                if result_status is not None and result_status != "completed":
                    reason_code = result_details.get("reason_code")
                    message = result_details.get("message")
                    detail_parts = [
                        str(value)
                        for value in (reason_code, message)
                        if value is not None
                    ]
                    if len(detail_parts) == 2 and detail_parts[1].startswith(
                        detail_parts[0] + ": "
                    ):
                        detail_parts[1] = detail_parts[1][len(detail_parts[0]) + 2 :]
                    detail = ": ".join(detail_parts)
                    raise WorkflowExecutionError(
                        f"P7 pack {operation_id} returned non-completed result "
                        f"status {result_status!r}"
                        + (f" ({detail})" if detail else "")
                    )
            except Exception as exc:
                raise WorkflowExecutionError(
                    f"P7 pack {operation_id} failed closed: {exc}"
                ) from exc
            return _persist_p7_pack_result(
                root,
                draft,
                step,
                result=result,
                lineage=lineage,
                pack_family=operation.pack_family,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.workflow_capability":
            from .workflow_capability_registry import workflow_capability_registry

            operation = workflow_capability_registry().require(operation_id)
            request = {
                "operation_id": operation_id,
                "input_mode": step.spec.get("input_mode"),
                "column_bindings": step.spec.get("column_bindings"),
                "options": step.spec.get("options"),
            }
            try:
                normalized_request, execution = operation.execute_with_context(
                    step_frame, request
                )
            except Exception as exc:
                from ..econometrics.optional_deps import OptionalDependencyNotInstalled

                if isinstance(exc, OptionalDependencyNotInstalled):
                    raise WorkflowExecutionError(
                        f"workflow capability {operation_id} blocked/optional_dependency: {exc}"
                    ) from exc
                raise WorkflowExecutionError(
                    f"workflow capability {operation_id} failed closed: {exc}"
                ) from exc
            return _persist_workflow_capability_result(
                root,
                draft,
                step,
                lineage=lineage,
                request=normalized_request,
                execution=execution,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.data_operation":
            return _persist_data_management_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_explore" and "plots" not in step.spec:
            return _exploration_step(
                root=root,
                draft=draft,
                lineage=lineage,
                source_frame=step_frame,
                spec=_exploration_spec(step.spec),
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derive_numeric":
            return _persist_numeric_derivation(
                root=root,
                draft=draft,
                lineage=lineage,
                frame=step_frame,
                step=step,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derive_boolean":
            detail, detail_step_id, detail_fingerprint = _detail_result(
                previous, source_run_root, step.depends_on, dependency_graph
            )
            if not detail_fingerprint:
                raise WorkflowExecutionError(
                    f"{detail_step_id} detail result fingerprint is unavailable"
                )
            artifact_ids: list[str] = []
            row_counts: dict[str, int] = {}
            for recipe in step.spec["recipes"]:
                variable = detail.get("variables", {}).get(recipe["source_column"], {})
                expected = variable.get("percentiles", {}).get(f"p{recipe['percentile']}")
                if expected is None:
                    raise WorkflowExecutionError(
                        f"{detail_step_id} has no p{recipe['percentile']} "
                        f"for {recipe['source_column']}"
                    )
                spec = ExplorationSpec(
                    operation="derive_boolean",
                    selected_columns=(recipe["source_column"],),
                    options={
                        "source_column": recipe["source_column"],
                        "percentile": recipe["percentile"],
                        "comparison": recipe["comparison"],
                        "output_name": recipe["output_name"],
                        "quantile_method": step.spec.get(
                            "quantile_method", STATA_QUANTILE_METHOD
                        ),
                    },
                )
                result = execute_exploration(step_frame, spec)
                actual = result.get("derived", {}).get("threshold")
                if actual is None or abs(float(actual) - float(expected)) > 1e-12:
                    raise WorkflowExecutionError(
                        f"{step.step_id} threshold for {recipe['output_name']} "
                        f"is not sourced from {detail_step_id}"
                    )
                record, _fingerprint = _persist_workflow_exploration(
                    root, draft, lineage, spec=spec, result=result, frame=step_frame
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[recipe["output_name"]] = int(
                    result.get("source_row_count", len(step_frame))
                )
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
                result_fingerprint=step.fingerprint,
                payload={
                    "detail": detail,
                    "threshold_source": {
                        "step_id": detail_step_id,
                        "artifact_role": "result",
                        "result_fingerprint": detail_fingerprint,
                    },
                },
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derived_group_summarize":
            detail, detail_step_id, _detail_fp = _detail_result(
                previous, source_run_root, step.depends_on, dependency_graph
            )
            grouped = step_frame.copy()
            artifact_ids: list[str] = []
            row_counts: dict[str, int] = {}
            summarize_columns = tuple(
                str(column) for column in step.spec["summarize_columns"]
            )
            for recipe in step.spec["groups"]:
                threshold = detail["variables"][recipe["source_column"]]["percentiles"][f"p{recipe['percentile']}"]
                series = grouped[recipe["source_column"]]
                values = pd.Series(pd.NA, index=grouped.index, dtype="boolean")
                if recipe["comparison"] == "lte":
                    values.loc[series.notna()] = series.loc[series.notna()] <= threshold
                else:
                    values.loc[series.notna()] = series.loc[series.notna()] >= threshold
                grouped[recipe["output_name"]] = values
                spec = ExplorationSpec(
                    operation="summarize",
                    selected_columns=summarize_columns,
                    filters=(FilterSpec(column=recipe["output_name"], operator="eq", value=True),),
                )
                result = execute_exploration(grouped, spec)
                if int(result.get("filtered_row_count", 0)) == 0:
                    raise WorkflowExecutionError(
                        f"{step.step_id} empty derived group: {recipe['output_name']}"
                    )
                record, _fingerprint = _persist_workflow_exploration(
                    root, draft, lineage, spec=spec, result=result, frame=grouped
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[recipe["output_name"]] = int(result["filtered_row_count"])
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
                payload={"groups": row_counts},
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_explore" and "plots" in step.spec:
            artifact_ids: list[str] = []
            row_counts: dict[str, int] = {}
            for plot in step.spec["plots"]:
                spec = ExplorationSpec(
                    operation="scatter",
                    selected_columns=(plot["x_column"], plot["y_column"]),
                    options={"x_column": plot["x_column"], "y_column": plot["y_column"]},
                )
                result = execute_exploration(step_frame, spec)
                record, _fingerprint = _persist_workflow_exploration(
                    root, draft, lineage, spec=spec, result=result, frame=step_frame
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[f"{plot['x_column']}->{plot['y_column']}"] = int(
                    result.get("plot", {}).get("plotted_row_count", 0)
                )
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_named_test":
            return _execute_named_statistical_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.imputation":
            return _execute_imputation_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.resampling":
            return _execute_resampling_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.prediction_model":
            return _execute_prediction_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.time_series_recipe":
            return _execute_time_series_recipe(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_auto":
            return _execute_model_auto(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
                admission_receipt=admission_receipt,
                evidence_port=evidence_port,
            )
        if dispatcher_key == "workbench.services.genesis":
            return _execute_model_genesis_branches(
                root,
                draft,
                lineage,
                step_frame,
                step,
                raw_source_frame=source_frame,
                admission_receipt=admission_receipt,
                evidence_port=evidence_port,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_joint_f_test":
            return _execute_model_joint_f_test(
                root, draft, lineage, step_frame, step, previous
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_white_test":
            return _execute_model_white_test(
                root, draft, lineage, step_frame, step, previous
            )
        if dispatcher_key == (
            "workbench.agent.workflow_runtime.model_quadratic_stationary_point"
        ):
            return _execute_model_quadratic_stationary_point(
                root, draft, lineage, step_frame, step, previous
            )
        if dispatcher_key == "capability_factory.custom_dispatcher":
            if not callable(custom_step_executor):
                raise WorkflowExecutionError(
                    "model.custom requires an authorized custom capability gateway"
                )
            result = custom_step_executor(
                project_root=root,
                draft=draft,
                step=step,
                previous=previous,
                admission_receipt=admission_receipt,
                evidence_port=evidence_port,
            )
            if not isinstance(result, WorkflowStepResult):
                raise WorkflowExecutionError(
                    "authorized custom capability gateway returned an invalid result"
                )
            return result
        if dispatcher_key == "workbench.agent.workflow_runtime.report":
            return _execute_workflow_report(root, draft, previous, step)
        raise WorkflowExecutionError(
            f"unsupported workflow operation: {step.operation_id}"
        )

    gated = _ReceiptGatedWorkflowExecutor(execute, draft)
    if evidence_port is not None:
        gated._bind_evidence_port(evidence_port)
    return gated


def _execute_model_genesis_branches(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any = None,
    *,
    raw_source_frame: pd.DataFrame | None = None,
    admission_receipt: WorkflowAdmissionReceipt | None = None,
    evidence_port: EvidencePersistencePort | None = None,
) -> WorkflowStepResult:
    _require_active_write_context()
    if (
        type(evidence_port) is not EvidencePersistencePort
        or type(admission_receipt) is not WorkflowAdmissionReceipt
        or step is None
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: model family workflow requires an admitted server receipt"
        )
    evidence_port.require_receipt(admission_receipt)
    evidence_port.validate_execution_snapshot(admission_receipt, draft, step)
    source_run_id = str(draft.target["run_id"])
    source_run_root = root / "runs" / source_run_id
    inputs = read_run_inputs(source_run_root)
    upload = inputs.get("upload") or {}
    upload_sha = upload.get("sha256")
    filename = upload.get("filename") or "dataset.csv"
    if not isinstance(upload_sha, str) or not upload_sha:
        raise WorkflowExecutionError("raw source upload is unavailable for model genesis")
    upload_bytes = verify_upload(root, upload_sha).read_bytes()
    store = PipelineDraftStore(root)
    branch_outputs: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    # Read the branches off the step being executed. Indexing draft.steps[7]
    # tied the executor to one plan's length and ordering.
    branch_spec = step.spec if step is not None else draft.steps[7].spec
    model_family = str(branch_spec["model_family"])
    family_contract = model_family_contract(model_family)
    family_source_columns = family_context_columns(family_contract, branch_spec)
    primary_model_artifact_id = family_contract.expected_artifacts[0]
    workflow_step_id = str(step.step_id) if step is not None else "legacy-model-genesis"
    for branch in branch_spec["branches"]:
        branch_id = str(branch["branch_id"])
        branch_covariance = branch.get("covariance") or branch_spec.get("covariance") or "unadjusted"
        # Genesis estimates from an uploaded dataset, not from a formula, so a
        # dummy set or a squared term has to exist as a real column first. When
        # a branch declares derived terms, materialize an augmented upload and
        # point this branch at it; branches without them keep the original
        # upload untouched, so their lineage is unchanged.
        try:
            branch_frame, branch_predictors, references = expand_branch_terms(
                source_frame, branch
            )
        except ModelTermError as exc:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} derived terms: {exc}"
            ) from exc
        if family_contract.validate_branch_frame is not None:
            family_contract.validate_branch_frame(branch_frame, branch)
        # A branch can have no branch-local dummy/polynomial expansion and
        # still depend on an upstream numeric derivation.  Reusing the original
        # upload in that case would silently discard a declared column before
        # Genesis runs.  Only retain the original upload when the final design
        # is exactly the immutable raw source; otherwise store the complete,
        # server-derived table for this branch.
        raw_frame = source_frame if raw_source_frame is None else raw_source_frame
        source_is_workflow_target = (
            str(lineage["artifact_id"]) == str(draft.target["artifact_id"])
            and str(lineage["node_ref"]) == str(draft.target["node_ref"])
        )
        use_original_upload = (
            source_is_workflow_target
            and list(branch_frame.columns) == list(raw_frame.columns)
            and branch_frame.equals(raw_frame)
        )
        if use_original_upload:
            branch_upload_sha = upload_sha
            branch_filename = filename
        else:
            branch_upload_sha = store_upload_bytes(
                root,
                branch_frame.to_csv(index=False).encode(),
                filename=f"{Path(filename).stem}__{branch_id}.csv",
            )
            branch_filename = f"{Path(filename).stem}__{branch_id}.csv"
        stored = None
        for summary in store.list():
            candidate = store.get(summary["draft_id"])
            context = candidate.draft.get("exploration_context") or {}
            # Legacy keys are still read so a draft created before the rename
            # still resumes instead of re-estimating under a new identity.
            context_workflow = context.get("workflow_id", context.get("class3_workflow_id"))  # legacy-compat
            context_branch = context.get("branch_id", context.get("class3_branch_id"))  # legacy-compat
            context_step = context.get("workflow_step_id")
            if (
                context_workflow == draft.workflow_id
                and context_branch == branch_id
                and context_step == workflow_step_id
            ):
                stored = candidate
                break
        if stored is None:
            spec = ExplorationSpec(
                operation="summarize_detail",
                # Source columns only: this describes the variables the model is
                # built from, and it is evaluated against the original data
                # where a derived dummy or power column does not exist.
                selected_columns=tuple(
                    branch_spec.get("context_columns")
                    or (
                        str(branch["outcome"]),
                        *[str(c) for c in branch["predictors"]],
                        *family_source_columns,
                    )
                ),
                options={"quantile_method": STATA_QUANTILE_METHOD},
            )
            context = {
                "workflow_id": draft.workflow_id,
                "workflow_step_id": workflow_step_id,
                "branch_id": branch_id,
                "source_run_id": source_run_id,
                # The dataset this branch was actually built from. A branch
                # reading an upstream step's output is estimated on that table;
                # naming the workflow target here would hand every reader of
                # this draft -- resume, comparison, the report -- a digest that
                # belongs to data the model never saw.
                "source_node_id": str(lineage["node_ref"]),
                "source_artifact_id": str(lineage["artifact_id"]),
                "source_sha256": str(lineage["sha256"]),
                "exploration_fingerprint": exploration_fingerprint(str(lineage["sha256"]), spec),
                "filters": [],
                "spec": spec.to_dict(),
                "outcome_column": branch["outcome"],
                # The design actually estimated, so a reader can tell a dummy
                # set from a linear effect on the same source column.
                "predictor_columns": list(branch_predictors),
                "source_predictor_columns": [str(item) for item in branch["predictors"]],
                "categorical_reference_levels": references,
                "model_family": model_family,
                "covariance": branch_covariance,
                "workflow_plan_fingerprint": draft.plan_fingerprint,
            }
            model_params = family_contract.build_model_params(
                branch_spec, branch, list(branch_predictors), branch_covariance
            )
            # Run-level declarations belong to the data, not to the family, so
            # they are merged once here instead of in eighteen parameter
            # builders -- which is where they were being dropped.
            model_params.update(genesis_run_params(branch_spec))
            stored = create_genesis_draft(
                root,
                upload_sha256=branch_upload_sha,
                filename=branch_filename,
                sheet_names=(),
                columns=tuple(str(column) for column in branch_frame.columns),
                model_params=model_params,
                exploration_context=context,
                notebook_provenance=(
                    dict(draft.bindings["notebook_provenance"])
                    if isinstance(draft.bindings.get("notebook_provenance"), Mapping)
                    else None
                ),
            )
        validation = validate_draft_for_execution(stored.draft, execution_mode="genesis")
        if not validation.get("executable"):
            raise WorkflowExecutionError(
                f"{model_family} Draft validation failed for {branch_id}: {validation.get('checks')}"
            )
        result = execute_genesis_draft(
            stored.draft["draft_id"],
            root,
            store,
            stored,
            validated_draft_hash=compute_executable_draft_hash(stored.draft),
            execution_mode="genesis",
            idempotency_key=f"{draft.workflow_id}:{workflow_step_id}:{branch_id}",
        )
        run_id = str(result["run_id"])
        _wait_for_run(root, run_id)
        run_root = root / "runs" / run_id
        manifest = read_json(run_root / "run_manifest.json")
        if manifest.get("status") != "completed":
            raise WorkflowExecutionError(f"{model_family} branch {branch_id} did not complete")
        run_artifacts = _read_artifacts_index(run_root).get("artifacts", [])
        ids = [str(item["artifact_id"]) for item in run_artifacts if item.get("artifact_id")]
        missing_artifacts = sorted(set(family_contract.expected_artifacts) - set(ids))
        if missing_artifacts:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing required evidence: "
                + ", ".join(missing_artifacts)
            )
        model_result = read_json(
            run_root / "model_results" / f"{primary_model_artifact_id}.json"
        )
        if (
            family_contract.result_shape == "coefficient_intervals"
            and ("ci_lower" not in json.dumps(model_result) or "ci_upper" not in json.dumps(model_result))
        ):
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing coefficient confidence intervals"
            )
        missing_figures = sorted(required_branch_figures(branch_predictors) - set(ids))
        if family_contract.requires_branch_figures and missing_figures:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing required diagnostics: "
                + ", ".join(missing_figures)
            )
        # Genesis runs are child runs, so their artifacts do not pass through
        # the parent workflow's legacy persistence helper. Freeze every file
        # that the typed result is about to expose in the active server-owned
        # registry first; otherwise admit_result_artifacts must (correctly)
        # reject a legitimate child-run reference as untrusted.
        for item in run_artifacts:
            if not isinstance(item, Mapping) or not item.get("artifact_id"):
                continue
            child_artifact_id = str(item["artifact_id"])
            relative_path = item.get("path")
            if not isinstance(relative_path, str) or not relative_path:
                raise WorkflowExecutionError(
                    f"{model_family} branch {branch_id} has an artifact with no persisted path"
                )
            evidence_port._admit_server_artifact(
                admission_receipt,
                run_id=run_id,
                artifact_id=child_artifact_id,
                path=run_root / relative_path,
                artifact_type=str(item.get("artifact_type") or "model_output"),
                producer_step=str(item.get("step") or f"genesis:{branch_id}"),
                inputs=item.get("inputs", []) or [],
                provenance={
                    "branch_id": branch_id,
                    "model_run_id": run_id,
                    "model_artifact_id": primary_model_artifact_id,
                    "source_run_id": source_run_id,
                    "source_artifact_id": str(lineage["artifact_id"]),
                    "expected_artifacts": list(ids),
                },
                expected_artifacts=ids,
            )
        artifact_ids.extend(f"{run_id}:{artifact_id}" for artifact_id in ids)
        branch_outputs.append(
            {
                "branch_id": branch_id,
                "run_id": run_id,
                "artifact_ids": ids,
                "model_artifact_id": primary_model_artifact_id,
                "workflow_id": draft.workflow_id,
                "workflow_step_id": workflow_step_id,
                "source_run_id": source_run_id,
                "source_artifact_id": str(lineage["artifact_id"]),
                "source_sha256": str(lineage["sha256"]),
                "branch_spec": {
                    "model_family": model_family,
                    # Post-estimation refits this branch, and the covariance
                    # estimator changes what a joint test answers. Without it
                    # recorded here the refit could only guess, and would
                    # report inference for a model nobody estimated.
                    "covariance": branch_covariance,
                    **{
                        field_name: branch_spec.get(field_name)
                        for field_name in family_contract.context_spec_fields
                    },
                    "outcome": str(branch["outcome"]),
                    "predictors": [str(item) for item in branch["predictors"]],
                    "categorical": [str(item) for item in branch.get("categorical", []) or []],
                    "polynomials": [dict(item) for item in branch.get("polynomials", []) or []],
                },
                "predictor_columns": list(branch_predictors),
                "term_groups": _declared_branch_term_groups(
                    branch,
                    branch_frame,
                    branch_predictors,
                    references,
                ),
            }
        )
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": len(source_frame)},
        payload={"branches": branch_outputs},
        lineage={"branches": branch_outputs},
    )


def _execute_ols_branches(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any = None,
    *,
    raw_source_frame: pd.DataFrame | None = None,
    admission_receipt: WorkflowAdmissionReceipt | None = None,
    evidence_port: EvidencePersistencePort | None = None,
) -> WorkflowStepResult:
    """Compatibility name for callers that historically imported the OLS-only executor."""

    return _execute_model_genesis_branches(
        root,
        draft,
        lineage,
        source_frame,
        step,
        raw_source_frame=raw_source_frame,
        admission_receipt=admission_receipt,
        evidence_port=evidence_port,
    )


def _declared_branch_term_groups(
    branch: Mapping[str, Any],
    branch_frame: pd.DataFrame,
    branch_predictors: list[str],
    references: Mapping[str, Any],
) -> dict[str, dict[str, list[str]]]:
    """Map only a branch's declared source terms to its fitted columns."""

    groups: dict[str, dict[str, list[str]]] = {
        "linear": {},
        "categorical": {},
        "polynomial": {},
    }
    available = set(branch_predictors)
    for column in [str(item) for item in branch.get("predictors", []) or []]:
        if column in available:
            groups["linear"][column] = [column]
    for column in [str(item) for item in branch.get("categorical", []) or []]:
        reference = references.get(column)
        if reference is None or column not in branch_frame.columns:
            continue
        levels = branch_frame[column].dropna().unique().tolist()
        levels.sort(key=lambda value: (str(type(value)), value))
        terms = [
            dummy_column_name(column, level)
            for level in levels
            if level != reference and dummy_column_name(column, level) in available
        ]
        if terms:
            groups["categorical"][column] = terms
    for entry in branch.get("polynomials", []) or []:
        if not isinstance(entry, Mapping):
            continue
        column = entry.get("column")
        degree = entry.get("degree")
        if not isinstance(column, str) or isinstance(degree, bool) or not isinstance(degree, int):
            continue
        terms = [
            polynomial_column_name(column, power)
            for power in range(2, degree + 1)
            if polynomial_column_name(column, power) in available
        ]
        if terms:
            groups["polynomial"][column] = terms
    return groups


def _validate_persisted_model_branch(
    root: Path,
    draft: WorkflowDraft,
    model_step_id: str,
    branch: Mapping[str, Any],
) -> None:
    if branch.get("workflow_id") != draft.workflow_id:
        raise WorkflowExecutionError(
            "completed model branch belongs to another workflow scope"
        )
    if branch.get("workflow_step_id") != model_step_id:
        raise WorkflowExecutionError(
            "completed model branch belongs to another workflow step"
        )
    if branch.get("source_run_id") != str(draft.target["run_id"]):
        raise WorkflowExecutionError(
            "completed model branch source belongs to another workflow scope"
        )
    source_artifact_id = branch.get("source_artifact_id")
    source_sha256 = branch.get("source_sha256")
    if not isinstance(source_artifact_id, str) or not source_artifact_id:
        raise WorkflowExecutionError(
            "completed model branch lacks its persisted source artifact identity"
        )
    if not isinstance(source_sha256, str) or not source_sha256:
        raise WorkflowExecutionError(
            "completed model branch lacks its persisted source digest"
        )
    branch_spec = branch.get("branch_spec")
    if not isinstance(branch_spec, Mapping):
        raise WorkflowExecutionError("completed model branch lacks its family identity")
    family = branch_spec.get("model_family")
    if not isinstance(family, str) or not family:
        raise WorkflowExecutionError("completed model branch lacks its family identity")
    try:
        family_contract = model_family_contract(family)
    except Exception as exc:
        raise WorkflowExecutionError(
            "completed model branch family identity is not registered"
        ) from exc
    model_run_id = branch.get("run_id")
    model_run_id = _require_workflow_opaque_ref(
        model_run_id, "opaque model run reference"
    )
    runs_root = (root / "runs").resolve()
    model_root = root / "runs" / model_run_id
    if not model_root.is_dir() and not model_root.is_symlink():
        raise WorkflowExecutionError(
            "completed model branch is not backed by a persisted model run"
        )
    if model_root.is_symlink():
        raise WorkflowExecutionError(
            "completed model branch model run is not project-owned"
        )
    try:
        model_root.resolve().relative_to(runs_root)
    except ValueError as exc:
        raise WorkflowExecutionError(
            "completed model branch model run escapes the project"
        ) from exc
    manifest_path = model_root / "run_manifest.json"
    index_path = model_root / "artifacts_index.json"
    try:
        manifest = read_json(manifest_path)
        index = _read_artifacts_index(model_root)
    except (OSError, TypeError, ValueError, WorkbenchAPIError) as exc:
        raise WorkflowExecutionError(
            "completed model branch is not backed by a persisted model run"
        ) from exc
    if not isinstance(manifest, Mapping) or manifest.get("status") != "completed":
        raise WorkflowExecutionError(
            "completed model branch model run is not completed"
        )
    if manifest.get("run_id") not in {None, model_run_id}:
        raise WorkflowExecutionError(
            "completed model branch model run identity is inconsistent"
        )
    source_run_root = root / "runs" / str(draft.target["run_id"])
    try:
        source_index = _read_artifacts_index(source_run_root)
    except (OSError, TypeError, ValueError, WorkbenchAPIError) as exc:
        raise WorkflowExecutionError(
            "completed model branch source artifact registry cannot be read"
        ) from exc
    source_matches = [
        item
        for item in source_index.get("artifacts", [])
        if isinstance(item, Mapping)
        and item.get("artifact_id") == draft.target.get("artifact_id")
    ]
    if len(source_matches) != 1:
        raise WorkflowExecutionError(
            "completed model branch source artifact is not uniquely registered"
        )
    source_record = source_matches[0]
    source_relative_value = source_record.get("path")
    if not isinstance(source_relative_value, str) or not source_relative_value:
        raise WorkflowExecutionError(
            "completed model branch source artifact path is invalid"
        )
    source_relative = Path(source_relative_value)
    if source_relative.is_absolute() or ".." in source_relative.parts:
        raise WorkflowExecutionError(
            "completed model branch source artifact path escapes its run"
        )
    source_path = (source_run_root / source_relative).resolve()
    if source_run_root.is_symlink() or not source_run_root.is_dir():
        raise WorkflowExecutionError(
            "completed model branch source run is not project-owned"
        )
    try:
        source_path.relative_to(source_run_root.resolve())
    except ValueError as exc:
        raise WorkflowExecutionError(
            "completed model branch source artifact path escapes its run"
        ) from exc
    if source_path.is_symlink() or not source_path.is_file():
        raise WorkflowExecutionError(
            "completed model branch source artifact is unavailable"
        )
    try:
        actual_source_sha256 = sha256_file(source_path)
    except OSError as exc:
        raise WorkflowExecutionError(
            "completed model branch source artifact digest cannot be read"
        ) from exc
    registered_source_sha256 = source_record.get("sha256")
    if (
        source_artifact_id != draft.target.get("artifact_id")
        or not _digest_matches(registered_source_sha256, actual_source_sha256)
        or not _digest_matches(source_sha256, actual_source_sha256)
    ):
        raise WorkflowExecutionError(
            "completed model branch source artifact or content digest does not match the workflow target"
        )
    model_artifact_id = _model_artifact_id(branch)
    artifact_ids = branch.get("artifact_ids")
    if not isinstance(artifact_ids, list) or model_artifact_id not in artifact_ids:
        raise WorkflowExecutionError(
            "completed model branch model artifact identity is not declared"
        )
    if model_artifact_id != str(family_contract.expected_artifacts[0]):
        raise WorkflowExecutionError(
            "completed model branch model artifact does not match its family"
        )
    matching = [
        item
        for item in index.get("artifacts", [])
        if isinstance(item, Mapping) and item.get("artifact_id") == model_artifact_id
    ]
    if len(matching) != 1:
        raise WorkflowExecutionError(
            "completed model branch model artifact is not uniquely persisted"
        )
    artifact_path_value = matching[0].get("path")
    if not isinstance(artifact_path_value, str) or not artifact_path_value:
        raise WorkflowExecutionError(
            "completed model branch model artifact path is invalid"
        )
    artifact_relative = Path(artifact_path_value)
    if artifact_relative.is_absolute() or ".." in artifact_relative.parts:
        raise WorkflowExecutionError(
            "completed model branch model artifact path escapes its run"
        )
    raw_artifact_path = model_root / artifact_relative
    if raw_artifact_path.is_symlink():
        raise WorkflowExecutionError(
            "completed model branch model artifact is not project-owned"
        )
    artifact_path = raw_artifact_path.resolve()
    try:
        artifact_path.relative_to(model_root.resolve())
    except ValueError as exc:
        raise WorkflowExecutionError(
            "completed model branch model artifact escapes its run scope"
        ) from exc
    if not artifact_path.is_file():
        raise WorkflowExecutionError(
            "completed model branch model artifact is not persisted"
        )
    try:
        actual_model_artifact_sha256 = sha256_file(artifact_path)
    except OSError as exc:
        raise WorkflowExecutionError(
            "completed model branch model artifact digest cannot be read"
        ) from exc
    if not _digest_matches(matching[0].get("sha256"), actual_model_artifact_sha256):
        raise WorkflowExecutionError(
            "completed model branch model artifact digest changed"
        )
    try:
        model_result = read_json(artifact_path)
    except (OSError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            "completed model branch model artifact is unreadable"
        ) from exc
    if isinstance(model_result, Mapping):
        declared_family = model_result.get("model_family")
        if declared_family is not None and declared_family != family:
            raise WorkflowExecutionError(
                "completed model branch artifact family identity changed"
            )


def _dependent_model_branch(
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
    *,
    root: Path | None = None,
    draft: WorkflowDraft | None = None,
) -> dict[str, Any]:
    """Resolve a branch only from a direct completed model dependency."""

    branch_id = str(step.spec["branch_id"])
    matches: list[dict[str, Any]] = []
    matched_dependency_id: str | None = None
    for dependency_id in step.depends_on:
        dependency = previous.get(dependency_id)
        branches = dependency.payload.get("branches") if dependency is not None else None
        if not isinstance(branches, list) and dependency is not None:
            lineage = dependency.lineage or dependency.payload.get("lineage")
            branches = lineage.get("branches") if isinstance(lineage, Mapping) else None
        if not isinstance(branches, list) and dependency is not None:
            typed_outputs = dependency.output_bindings or dependency.payload.get("output_bindings")
            model_output = typed_outputs.get("model_branches") if isinstance(typed_outputs, Mapping) else None
            branches = model_output.get("branches") if isinstance(model_output, Mapping) else None
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if isinstance(branch, Mapping) and branch.get("branch_id") == branch_id:
                matches.append(dict(branch))
                matched_dependency_id = dependency_id
    if not matches:
        raise WorkflowExecutionError(
            f"{step.step_id} must directly depend on a completed model branch: {branch_id}"
        )
    if len(matches) != 1:
        raise WorkflowExecutionError(
            f"{step.step_id} has an ambiguous completed model branch: {branch_id}"
        )
    branch = matches[0]
    if not isinstance(branch.get("branch_spec"), Mapping) or not isinstance(
        branch.get("term_groups"), Mapping
    ):
        raise WorkflowExecutionError(
            f"completed model branch {branch_id} lacks declared-term provenance"
        )
    try:
        post_estimation_registry.require_from_branch(
            branch,
            operation_id=str(step.operation_id),
            output_id=str(step.spec.get("output_id", "result")),
        )
    except PostEstimationRegistryError as exc:
        # The stable code is part of the refusal contract; do not let an
        # unsupported family fall through to the OLS refit helper.
        raise WorkflowExecutionError(str(exc)) from exc
    if root is not None and draft is not None and matched_dependency_id is not None:
        _validate_persisted_model_branch(root, draft, matched_dependency_id, branch)
    return branch


def _branch_covariance(branch_spec: Mapping[str, Any]) -> str:
    """The covariance estimator the completed branch was actually fitted under.

    Fails closed rather than defaulting. Silently refitting under `unadjusted`
    is what produced a joint test whose p-value belonged to a model the user
    never estimated, while carrying that model's provenance.
    """

    covariance = branch_spec.get("covariance")
    if not isinstance(covariance, str) or not covariance:
        raise WorkflowExecutionError(
            "completed model branch does not record its covariance estimator, so "
            "post-estimation inference cannot reproduce it"
        )
    if covariance not in {"unadjusted", "robust", "clustered"}:
        raise WorkflowExecutionError(
            f"completed model branch has an unsupported covariance estimator: {covariance}"
        )
    return covariance


def _model_artifact_id(branch: Mapping[str, Any]) -> str:
    declared = branch.get("model_artifact_id")
    if isinstance(declared, str) and declared:
        return declared
    raise WorkflowExecutionError("completed model branch lacks its model artifact identity")


def _refit_completed_ols_branch(
    source_frame: pd.DataFrame,
    branch: Mapping[str, Any],
) -> tuple[Any, list[str], pd.DataFrame]:
    """Reconstruct the completed OLS design and covariance from source data."""

    branch_spec = branch.get("branch_spec")
    if not isinstance(branch_spec, Mapping):
        raise WorkflowExecutionError("completed model branch lacks a branch specification")
    try:
        branch_frame, predictor_columns, _references = expand_branch_terms(
            source_frame,
            branch_spec,
        )
    except ModelTermError as exc:
        raise WorkflowExecutionError(
            f"completed model branch cannot be reconstructed: {exc}"
        ) from exc
    expected = branch.get("predictor_columns")
    if not isinstance(expected, list) or predictor_columns != [str(item) for item in expected]:
        raise WorkflowExecutionError(
            "completed model branch design no longer matches its declared provenance"
        )
    covariance = _branch_covariance(branch_spec)
    cluster_col: str | None = None
    if covariance == "clustered":
        entity_col = branch_spec.get("entity_col")
        if not isinstance(entity_col, str) or not entity_col:
            raise WorkflowExecutionError(
                "clustered post-estimation requires the branch's cluster column"
            )
        cluster_col = entity_col
    try:
        # run_ols returns the *plain* fit, so the declared estimator is applied
        # here through the shared helper. Reading `fitted` straight from
        # run_ols would silently do post-estimation inference under nonrobust.
        _normalized, plain_fit = run_ols(
            branch_frame,
            str(branch_spec["outcome"]),
            predictor_columns,
            robust=covariance == "robust",
            model_id="ols_1",
            cluster_col=cluster_col,
            covariance=covariance,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            f"completed model branch cannot be refit for post-estimation: {exc}"
        ) from exc
    model_frame = branch_frame.copy()
    if not model_frame.index.is_unique:
        model_frame.index = pd.RangeIndex(len(model_frame), name="__ols_position__")
    row_labels = getattr(plain_fit.model.data, "row_labels", None)
    if row_labels is None:
        raise WorkflowExecutionError("completed model does not expose its analysis sample")
    try:
        analysis_frame = model_frame.loc[row_labels].copy()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            "completed model analysis sample cannot be recovered from immutable source data"
        ) from exc
    if len(analysis_frame) != int(plain_fit.nobs):
        raise WorkflowExecutionError(
            "completed model analysis sample does not match its fitted observation count"
        )
    groups = (
        analysis_frame[cluster_col].to_numpy(copy=True) if cluster_col is not None else None
    )
    try:
        fitted = apply_ols_covariance(plain_fit, covariance, groups=groups)
    except ValueError as exc:
        raise WorkflowExecutionError(
            f"completed model covariance cannot be reproduced: {exc}"
        ) from exc
    return fitted, predictor_columns, analysis_frame


def _fitted_term_positions(fitted: Any, terms: list[str]) -> list[int]:
    names = [str(item) for item in getattr(fitted.model, "exog_names", [])]
    positions: list[int] = []
    for term in terms:
        fitted_name = f"Q({term!r})"
        try:
            positions.append(names.index(fitted_name))
        except ValueError as exc:
            raise WorkflowExecutionError(
                f"completed model is missing the declared coefficient term: {term}"
            ) from exc
    return positions


def _selected_model_terms(branch: Mapping[str, Any], selectors: list[Any]) -> list[str]:
    groups = branch.get("term_groups")
    if not isinstance(groups, Mapping):
        raise WorkflowExecutionError("completed model branch lacks declared term groups")
    selected: list[str] = []
    for selector in selectors:
        if not isinstance(selector, Mapping):
            raise WorkflowExecutionError("joint F test selector is invalid")
        kind = str(selector.get("kind"))
        column = str(selector.get("column"))
        by_column = groups.get(kind)
        terms = by_column.get(column) if isinstance(by_column, Mapping) else None
        if not isinstance(terms, list) or not terms:
            raise WorkflowExecutionError(
                "joint F test selector is not declared by the completed model branch: "
                f"{kind}:{column}"
            )
        selected.extend(str(item) for item in terms)
    return list(dict.fromkeys(selected))


def _persist_model_post_estimation_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    artifact_type: str,
    result: Mapping[str, Any],
    model_run_id: str,
    model_artifact_id: str,
    lineage: Mapping[str, str],
) -> WorkflowStepResult:
    """Persist one durable, idempotent post-estimation artifact on the source run."""

    _require_active_write_context()

    run_root = root / "runs" / str(draft.target["run_id"])
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    artifact_id = f"workflow_{operation_token}_{token}"
    artifact_path = run_root / "artifacts" / artifact_type / f"{artifact_id}.json"
    payload = {
        "schema_version": "workbench.workflow.post-estimation/v1",
        "source": {
            # run_id stays the workflow's target run because that is where this
            # artifact is written; the node, artifact and digest name the data
            # the test was computed on, which a `source` commitment moves.
            "run_id": str(draft.target["run_id"]),
            "node_ref": str(lineage["node_ref"]),
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
            "model_run_id": model_run_id,
            "model_artifact_id": model_artifact_id,
            "workflow_id": draft.workflow_id,
            "workflow_step_id": step.step_id,
            "workflow_step_fingerprint": step.fingerprint,
        },
        "result": dict(result),
    }
    artifact_path = _write_runtime_artifact_json(
        run_root,
        artifact_path.relative_to(run_root),
        payload,
        occupied_message="post-estimation artifact path is occupied",
        retain_for_registry=True,
    )
    # This is a workflow-owned output, so use the common registration bridge:
    # it checks the public index for deterministic identity and then freezes
    # the path, digest, producer and expected outputs in the active server
    # registry before the typed result is admitted.
    _ensure_runtime_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type=artifact_type,
        step=str(step.operation_id),
        inputs=[str(lineage["artifact_id"])],
    )
    return WorkflowStepResult(
        artifact_ids=[artifact_id],
        row_counts={},
        result_fingerprint=str(step.fingerprint),
        payload={"result": dict(result), "model_run_id": model_run_id},
        output_bindings={
            "result": {
                "binding_type": "post_estimation",
                "run_id": str(draft.target["run_id"]),
                "node_ref": str(lineage["node_ref"]),
                "artifact_id": artifact_id,
                "content_sha256": sha256_file(artifact_path),
                "operation_id": str(step.operation_id),
                "model_run_id": model_run_id,
                "model_artifact_id": model_artifact_id,
            }
        },
        lineage={
            "output_identity": {
                "operation_id": str(step.operation_id),
                "artifact_id": artifact_id,
                "model_run_id": model_run_id,
                "model_artifact_id": model_artifact_id,
            }
        },
    )


def _persist_p7_pack_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    result: Mapping[str, Any],
    lineage: Mapping[str, str],
    pack_family: str,
) -> WorkflowStepResult:
    """Persist one bounded P7 result with deterministic source provenance."""

    _require_active_write_context()

    run_root = root / "runs" / str(draft.target["run_id"])
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    workflow_token = hashlib.sha256(draft.workflow_id.encode("utf-8")).hexdigest()[:16]
    artifact_id = f"workflow_p7_{operation_token}_{workflow_token}_{token}"
    artifact_path = run_root / "artifacts" / "p7_analysis" / f"{artifact_id}.json"
    payload = {
        "schema_version": "workbench.workflow.p7-pack/v1",
        "source": {
            "run_id": str(draft.target["run_id"]),
            "node_ref": str(lineage["node_ref"]),
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
            "workflow_id": draft.workflow_id,
            "workflow_step_id": step.step_id,
            "workflow_step_fingerprint": step.fingerprint,
            "operation_id": step.operation_id,
            "pack_family": pack_family,
        },
        "result": dict(result),
    }
    artifact_path = _write_runtime_artifact_json(
        run_root,
        artifact_path.relative_to(run_root),
        payload,
        occupied_message="P7 analysis artifact path is occupied",
        retain_for_registry=True,
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="p7_analysis",
        step=str(step.operation_id),
        inputs=[str(lineage["artifact_id"])],
    )
    row_counts: dict[str, int] = {}
    for field_name in ("n_observations", "n_rows", "n_units"):
        value = result.get(field_name)
        if type(value) is int and value >= 0:
            row_counts[field_name] = value
    return WorkflowStepResult(
        artifact_ids=[artifact_id],
        row_counts=row_counts,
        result_fingerprint=str(step.fingerprint),
        payload={"result": dict(result)},
    )


def _workflow_request_fingerprint(request: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _persist_workflow_capability_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    lineage: Mapping[str, str],
    request: Mapping[str, Any],
    execution: Any,
) -> WorkflowStepResult:
    """Persist one generic capability result or one typed dataset child.

    The adapter decides whether it produced a dataset.  This function owns the
    common durability boundary: normalized request, source binding, result
    digest, registered artifact, and (for datasets) a graph/node binding that a
    later step can resolve without reopening the original target.
    """

    _require_active_write_context()

    run_id = str(draft.target["run_id"])
    run_root = root / "runs" / run_id
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    request_fingerprint = _workflow_request_fingerprint(request)
    result_payload = dict(execution.payload)
    if execution.output_frame is None:
        artifact_id = f"workflow_capability_{operation_token}_{token}"
        artifact_path = run_root / "artifacts" / "workflow_capability" / f"{artifact_id}.json"
        result_digest = hashlib.sha256(
            json.dumps(result_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        envelope = {
            "schema_version": "workbench.workflow.capability/v1",
            "contract_version": "v1",
            "source": {
                "run_id": run_id,
                "node_ref": str(lineage["node_ref"]),
                "artifact_id": str(lineage["artifact_id"]),
                "sha256": str(lineage["sha256"]),
                "workflow_id": draft.workflow_id,
                "workflow_step_id": str(step.step_id),
                "workflow_step_fingerprint": str(step.fingerprint),
                "operation_id": str(step.operation_id),
            },
            "request": dict(request),
            "request_fingerprint": request_fingerprint,
            "result_schema": str(step.contract.output_schema_ref) if hasattr(step, "contract") else str(
                WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id].output_schema_ref
            ),
            "result_sha256": result_digest,
            "result": result_payload,
        }
        artifact_path = _write_runtime_artifact_json(
            run_root,
            artifact_path.relative_to(run_root),
            envelope,
            occupied_message="workflow capability artifact path is occupied",
            retain_for_registry=True,
        )
        _ensure_runtime_artifact(
            run_root,
            artifact_id=artifact_id,
            path=artifact_path,
            artifact_type="workflow_capability_result",
            step=str(step.operation_id),
            inputs=[str(lineage["artifact_id"])],
        )
        row_counts = {
            key: int(result_payload[key])
            for key in ("n_observations", "n_rows", "input_rows", "output_rows", "row_count")
            if type(result_payload.get(key)) is int and result_payload[key] >= 0
        }
        return WorkflowStepResult(
            artifact_ids=[artifact_id],
            row_counts=row_counts,
            result_fingerprint=str(step.fingerprint),
            payload={"result": result_payload, "record": envelope},
        )

    output_frame = execution.output_frame
    if not isinstance(output_frame, pd.DataFrame) or output_frame.empty:
        raise WorkflowExecutionError(
            f"workflow capability {step.operation_id} declared a dataset but returned no non-empty frame"
        )
    dataset_kind = execution.dataset_kind
    if not isinstance(dataset_kind, str) or not dataset_kind:
        raise WorkflowExecutionError(
            f"workflow capability {step.operation_id} returned a dataset without a server-owned dataset role"
        )
    capability_dir = Path("derived") / "workflow_capability" / token
    data_rel = (capability_dir / "data.csv").as_posix()
    data_path = _write_runtime_artifact_bytes(
        run_root,
        Path(data_rel),
        output_frame.to_csv(index=False).encode("utf-8"),
        occupied_message="workflow capability dataset path is occupied",
        retain_for_registry=True,
    )
    schema_rel = Path(data_rel).with_name(Path(data_rel).stem + ".schema.json")
    schema = {"dtypes": {str(column): str(output_frame[column].dtype) for column in output_frame.columns}}
    schema_path = _write_runtime_artifact_json(
        run_root,
        schema_rel,
        schema,
        occupied_message="workflow capability dataset schema path is occupied",
        retain_for_registry=True,
    )
    data_sha256 = sha256_file(data_path)
    data_artifact_id = f"workflow_capability_dataset_{operation_token}_{token}"
    metadata_artifact_id = f"workflow_capability_dataset_metadata_{operation_token}_{token}"
    metadata_rel = (capability_dir / "metadata.json").as_posix()
    metadata = {
        "schema_version": "workbench.workflow.capability-dataset/v1",
        "operation_id": str(step.operation_id),
        "dataset_kind": dataset_kind,
        "source": {
            "run_id": run_id,
            "node_ref": str(lineage["node_ref"]),
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
        },
        "request": dict(request),
        "request_fingerprint": request_fingerprint,
        "result": result_payload,
        "data_sha256": data_sha256,
    }
    metadata_path = _write_runtime_artifact_json(
        run_root,
        Path(metadata_rel),
        metadata,
        occupied_message="workflow capability dataset metadata path is occupied",
        retain_for_registry=True,
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type=str(execution.artifact_type),
        step=str(step.operation_id),
        inputs=[str(lineage["artifact_id"])],
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="workflow_capability_metadata",
        step=str(step.operation_id),
        inputs=[str(lineage["artifact_id"]), data_artifact_id],
    )
    child_node_id = f"workflow-capability:{operation_token}:{token}"
    branch_id = f"workflow-capability:{token[:20]}"

    def add_child(graph: Graph) -> Graph:
        if child_node_id in graph.nodes:
            return graph
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=f"{step.operation_id} dataset",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=str(lineage["node_ref"]),
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=f"{dataset_kind}; {len(output_frame)} rows",
            annotations=({
                "type": "workflow_capability_dataset",
                "operation_id": str(step.operation_id),
                "workflow_id": draft.workflow_id,
                "workflow_step_id": str(step.step_id),
                "dataset_kind": dataset_kind,
                "metadata_path": metadata_rel,
            },),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=str(lineage["node_ref"]),
                    target_id=child_node_id,
                    op=str(step.operation_id),
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=str(lineage["node_ref"]),
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(run_id, add_child)
    node_index_relative = Path("node_index.json")
    node_index = _read_runtime_artifact_json(
        run_root, node_index_relative, missing={}
    )
    if not isinstance(node_index, Mapping):
        raise WorkflowExecutionError("workflow capability dataset node index is not an object")
    node_entry = {
        "node_hash": data_sha256,
        "producing_stage": str(step.operation_id),
        "cas_ref": {"node_hash": data_sha256, "artifact": data_rel},
    }
    existing_node = node_index.get(child_node_id)
    if existing_node is not None and existing_node != node_entry:
        raise WorkflowExecutionError("workflow capability dataset node identity is not deterministic")
    if existing_node is None:
        _write_runtime_artifact_json(
            run_root,
            node_index_relative,
            {**node_index, child_node_id: node_entry},
            occupied_message="workflow capability dataset node identity is not deterministic",
        )
    result_payload = {
        **result_payload,
        "produced_dataset": {
            "schema_version": _PRODUCED_DATASET_SCHEMA,
            "run_id": run_id,
            "node_ref": child_node_id,
            "artifact_id": data_artifact_id,
            "content_sha256": data_sha256,
            "dataset_kind": dataset_kind,
            "result_fingerprint": str(step.fingerprint),
        },
    }
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, metadata_artifact_id],
        row_counts={
            "input_rows": int(result_payload.get("input_rows", 0) or 0),
            "output_rows": int(len(output_frame)),
        },
        result_fingerprint=str(step.fingerprint),
        payload={"result": result_payload, "produced_dataset": result_payload["produced_dataset"]},
    )


def _execute_model_joint_f_test(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    _require_active_write_context()
    branch = _dependent_model_branch(step, previous, root=root, draft=draft)
    selectors = step.spec.get("term_selectors")
    if not isinstance(selectors, list):
        raise WorkflowExecutionError("joint F test term selectors are unavailable")
    terms = _selected_model_terms(branch, selectors)
    fitted, _predictor_columns, _analysis_frame = _refit_completed_ols_branch(
        source_frame, branch
    )
    positions = _fitted_term_positions(fitted, terms)
    restriction = np.zeros((len(positions), len(fitted.model.exog_names)))
    for row, position in enumerate(positions):
        restriction[row, position] = 1.0
    test = fitted.f_test(restriction)
    f_statistic = float(np.asarray(test.fvalue).squeeze())
    p_value = float(np.asarray(test.pvalue).squeeze())
    denominator_df = float(np.asarray(test.df_denom).squeeze())
    numerator_df = float(np.asarray(test.df_num).squeeze())
    if not all(math.isfinite(value) for value in (f_statistic, p_value, denominator_df, numerator_df)):
        raise WorkflowExecutionError("joint F test produced a non-finite result")
    result = {
        "schema_version": "workbench.model.joint-f-test/v1",
        "test": "joint_f_test",
        "branch_id": str(branch["branch_id"]),
        "term_selectors": [dict(item) for item in selectors if isinstance(item, Mapping)],
        "coefficient_terms": terms,
        "f_statistic": f_statistic,
        "p_value": p_value,
        "numerator_df": numerator_df,
        "denominator_df": denominator_df,
        "nobs": int(fitted.nobs),
        "covariance": _branch_covariance(branch["branch_spec"]),
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="statistical_test",
        result=result,
        model_run_id=str(branch["run_id"]),
        model_artifact_id=_model_artifact_id(branch),
        lineage=lineage,
    )


def _white_test_statistics(
    residuals: Any,
    exog: Any,
) -> tuple[float, float, float, float, int, int]:
    """Calculate White's test with one explicit auxiliary-design rank policy.

    The auxiliary design contains every square and pairwise product of the
    completed OLS design.  Its columns can differ widely in scale when a model
    mixes polynomials and categorical expansions.  Normalize non-zero columns
    before choosing the rank and use that exact tolerance for the least-squares
    solve, so statistical validity does not depend on a third-party assertion
    comparing two incompatible rank estimates.
    """

    errors = np.asarray(residuals, dtype=float).reshape(-1)
    design = np.asarray(exog, dtype=float)
    if design.ndim != 2 or design.shape[0] != errors.size:
        raise WorkflowExecutionError("White test received an invalid completed OLS design")
    if errors.size < 3 or not np.isfinite(errors).all() or not np.isfinite(design).all():
        raise WorkflowExecutionError("White test requires finite residuals and design values")

    left, right = np.triu_indices(design.shape[1])
    auxiliary = design[:, left] * design[:, right]
    scales = np.linalg.norm(auxiliary, axis=0)
    usable = scales > 0
    if not bool(usable.any()):
        raise WorkflowExecutionError("White test auxiliary design has no non-zero columns")
    normalized = auxiliary[:, usable] / scales[usable]
    singular_values = np.linalg.svd(normalized, compute_uv=False)
    if singular_values.size == 0 or not math.isfinite(float(singular_values[0])):
        raise WorkflowExecutionError("White test auxiliary design rank is unavailable")
    rcond = max(normalized.shape) * np.finfo(float).eps
    rank = int((singular_values > singular_values[0] * rcond).sum())
    auxiliary_df = rank - 1
    residual_df = errors.size - rank
    if auxiliary_df < 1 or residual_df < 1:
        raise WorkflowExecutionError(
            "White test auxiliary design does not leave enough independent degrees of freedom"
        )

    squared_errors = errors**2
    centered = squared_errors - squared_errors.mean()
    total_sum_squares = float(centered @ centered)
    scale = max(float(squared_errors @ squared_errors), 1.0)
    if total_sum_squares <= np.finfo(float).eps * scale:
        raise WorkflowExecutionError("White test residual squares have no estimable variation")
    coefficients, *_ = np.linalg.lstsq(normalized, squared_errors, rcond=rcond)
    fitted = normalized @ coefficients
    residual_sum_squares = float(np.square(squared_errors - fitted).sum())
    r_squared = 1.0 - residual_sum_squares / total_sum_squares
    if not math.isfinite(r_squared) or r_squared < -1e-9 or r_squared > 1.0 + 1e-9:
        raise WorkflowExecutionError("White test auxiliary regression produced an invalid R-squared")
    r_squared = min(1.0, max(0.0, r_squared))
    unexplained = 1.0 - r_squared
    if unexplained <= np.finfo(float).eps:
        raise WorkflowExecutionError("White test auxiliary regression is saturated")

    lm_statistic = errors.size * r_squared
    f_statistic = (r_squared / auxiliary_df) / (unexplained / residual_df)
    lm_p_value = float(stats.chi2.sf(lm_statistic, auxiliary_df))
    f_p_value = float(stats.f.sf(f_statistic, auxiliary_df, residual_df))
    values = (lm_statistic, lm_p_value, f_statistic, f_p_value)
    if not all(math.isfinite(value) for value in values):
        raise WorkflowExecutionError("White test produced a non-finite result")
    return (*values, auxiliary_df, residual_df)


def _execute_model_white_test(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    """Persist White's test from the immutable, declared OLS design."""

    _require_active_write_context()

    branch = _dependent_model_branch(step, previous, root=root, draft=draft)
    fitted, _predictor_columns, _analysis_frame = _refit_completed_ols_branch(
        source_frame, branch
    )
    (
        lm_statistic,
        lm_p_value,
        f_statistic,
        f_p_value,
        auxiliary_df,
        residual_df,
    ) = _white_test_statistics(
        fitted.resid,
        fitted.model.exog,
    )
    result = {
        "schema_version": "workbench.model.white-test/v1",
        "test": "white_test",
        "branch_id": str(branch["branch_id"]),
        "lm_statistic": lm_statistic,
        "lm_p_value": lm_p_value,
        "f_statistic": f_statistic,
        "f_p_value": f_p_value,
        "auxiliary_df": auxiliary_df,
        "residual_df": residual_df,
        "nobs": int(fitted.nobs),
        "covariance": _branch_covariance(branch["branch_spec"]),
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="statistical_test",
        result=result,
        model_run_id=str(branch["run_id"]),
        model_artifact_id=_model_artifact_id(branch),
        lineage=lineage,
    )


def _execute_model_quadratic_stationary_point(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    _require_active_write_context()
    branch = _dependent_model_branch(step, previous, root=root, draft=draft)
    column = str(step.spec["column"])
    groups = branch.get("term_groups")
    branch_spec = branch.get("branch_spec")
    if not isinstance(groups, Mapping) or not isinstance(branch_spec, Mapping):
        raise WorkflowExecutionError("completed model branch lacks declared-term provenance")
    linear_terms = groups.get("linear", {}).get(column) if isinstance(groups.get("linear"), Mapping) else None
    polynomial_terms = groups.get("polynomial", {}).get(column) if isinstance(groups.get("polynomial"), Mapping) else None
    degree = next(
        (
            item.get("degree")
            for item in branch_spec.get("polynomials", []) or []
            if isinstance(item, Mapping) and item.get("column") == column
        ),
        None,
    )
    if linear_terms != [column] or polynomial_terms != [polynomial_column_name(column, 2)] or degree != 2:
        raise WorkflowExecutionError(
            "stationary point requires a declared linear-plus-degree-two polynomial term: "
            + column
        )
    fitted, _predictor_columns, analysis_frame = _refit_completed_ols_branch(
        source_frame, branch
    )
    linear_position, quadratic_position = _fitted_term_positions(
        fitted,
        [column, polynomial_column_name(column, 2)],
    )
    parameters = np.asarray(fitted.params, dtype=float)
    linear_coefficient = float(parameters[linear_position])
    quadratic_coefficient = float(parameters[quadratic_position])
    if not all(math.isfinite(value) for value in (linear_coefficient, quadratic_coefficient)):
        raise WorkflowExecutionError("stationary point coefficients are non-finite")
    if quadratic_coefficient == 0.0:
        raise WorkflowExecutionError("stationary point is undefined because the quadratic coefficient is zero")
    stationary_point = -linear_coefficient / (2.0 * quadratic_coefficient)
    if not math.isfinite(stationary_point):
        raise WorkflowExecutionError("stationary point is non-finite")
    observed_values = pd.to_numeric(analysis_frame[column], errors="coerce")
    observed_values = observed_values[np.isfinite(observed_values.to_numpy(dtype=float))]
    if observed_values.empty:
        raise WorkflowExecutionError(
            "stationary point analysis sample has no finite values for the declared column"
        )
    observed_min = float(observed_values.min())
    observed_max = float(observed_values.max())
    result = {
        "schema_version": "workbench.model.quadratic-stationary-point/v1",
        "branch_id": str(branch["branch_id"]),
        "column": column,
        "linear_coefficient": linear_coefficient,
        "quadratic_coefficient": quadratic_coefficient,
        "stationary_point": stationary_point,
        "observed_min": observed_min,
        "observed_max": observed_max,
        "stationary_point_within_observed_range": observed_min <= stationary_point <= observed_max,
        "curvature": "minimum" if quadratic_coefficient > 0 else "maximum",
        "nobs": int(fitted.nobs),
        "covariance": _branch_covariance(branch["branch_spec"]),
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="post_estimation",
        result=result,
        model_run_id=str(branch["run_id"]),
        model_artifact_id=_model_artifact_id(branch),
        lineage=lineage,
    )


def required_branch_figures(predictors: Iterable[str]) -> set[str]:
    """Residual and fitted plots the branch's own predictors imply.

    This gate used to name one exercise's columns and special-case one of
    its branch ids, so a correct single-predictor branch under any other
    name was rejected for "missing diagnostics".
    """

    figures: set[str] = set()
    for predictor in predictors:
        figures.add(f"residuals_vs_{predictor}")
        figures.add(f"fitted_vs_{predictor}")
    return figures


def _wait_for_run(root: Path, run_id: str, *, timeout_seconds: float = 1800.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    path = root / "runs" / run_id / "run_manifest.json"
    while time.monotonic() < deadline:
        if path.is_file():
            manifest = read_json(path)
            if manifest.get("status") in {"completed", "failed", "blocked", "interrupted", "cancelled"}:
                return
        time.sleep(0.1)
    raise WorkflowExecutionError(f"run did not reach a terminal state: {run_id}")


def _execute_workflow_report(
    root: Path,
    draft: WorkflowDraft,
    previous: Mapping[str, WorkflowStepResult],
    step: Any | None = None,
) -> WorkflowStepResult:
    evidence_port, admission_receipt, _active_draft, _active_step = _require_active_write_context()
    report_step = step if step is not None else _active_step
    validated_previous = evidence_port.validate_completed_dependency_results(
        draft, report_step, previous
    )
    run_root = root / "runs" / str(draft.target["run_id"])
    log_path = root / "workbench" / "exploration" / f"{draft.workflow_id}.jsonl"
    events = []
    if log_path.is_file():
        from ..agent.storage import read_jsonl

        events = read_jsonl(log_path)
    steps = {
        step_id: {
            "status": value["status"],
            "artifact_ids": list(value["artifact_ids"]),
        }
        for step_id, value in validated_previous.items()
    }
    collection_id = f"workflow_report_collection_{draft.workflow_id}"
    html_id = f"workflow_report_{draft.workflow_id}_html"
    pdf_id = f"workflow_report_{draft.workflow_id}_pdf"
    xlsx_id = f"workflow_report_{draft.workflow_id}_xlsx"
    report_step_id = getattr(report_step, "step_id", None)
    if not isinstance(report_step_id, str) or not report_step_id:
        report_step_id = next(
            (
                candidate.step_id
                for candidate in draft.steps
                if candidate.operation_id == "report.compose"
            ),
            "report.compose",
        )
    steps[report_step_id] = {
        "status": "completed",
        "artifact_ids": [collection_id, html_id, pdf_id, xlsx_id],
    }
    collection = {
        "schema_version": "workflow-report-collection.v1",
        "workflow_id": draft.workflow_id,
        "workflow_plan_fingerprint": draft.plan_fingerprint,
        "status": "completed",
        "steps": steps,
        "exploration_log": events,
    }
    collection_output = prepare_formal_workflow_output(
        evidence_port,
        admission_receipt,
        run_root=run_root,
        directory_name="artifacts/statistical_exploration",
        filename=f"{draft.workflow_id}.json",
    )
    collection_path = collection_output.path
    try:
        existing_collection = collection_output.read_bytes()
        if existing_collection is not None:
            try:
                existing_payload = json.loads(existing_collection.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkflowExecutionError(
                    "workflow report collection path is occupied"
                ) from exc
            if existing_payload != collection:
                raise WorkflowExecutionError("workflow report collection path is occupied")
        else:
            collection_output.write_bytes(
                json.dumps(
                    collection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
    except Exception:
        collection_output.abort()
        raise
    try:
        record_formal_workflow_artifact(
            evidence_port,
            admission_receipt,
            run_root=run_root,
            artifact_id=collection_id,
            path=collection_path,
            artifact_type="report_collection",
            producer_step="report.compose",
            output_target=collection_output,
        )
    finally:
        collection_output.close()
    view_model = {
        "title": "Statistical workflow report",
        "facts": [
            f"Workflow steps completed: {len(steps)}.",
            f"Workflow id: {draft.workflow_id}",
            f"Source rows: {next(iter(validated_previous.values()))['row_counts'].get('source', 0) if validated_previous else 0}",
        ],
        "claims": [],
        "warnings": [],
        "descriptive_stats": [],
        "exploration": collection,
    }
    render_html_report(
        view_model,
        run_root,
        filename=f"{draft.workflow_id}.html",
        artifact_id=html_id,
        inputs=[collection_id],
        evidence_port=evidence_port,
        admission_receipt=admission_receipt,
    )
    export_pdf(
        view_model,
        run_root,
        filename=f"{draft.workflow_id}.pdf",
        artifact_id=pdf_id,
        inputs=[collection_id],
        evidence_port=evidence_port,
        admission_receipt=admission_receipt,
    )
    export_xlsx(
        {
            "workflow_steps": [
                {
                    "step_id": key,
                    "status": value["status"],
                    "artifact_ids": ", ".join(value["artifact_ids"]),
                }
                for key, value in steps.items()
            ]
        },
        run_root,
        filename=f"{draft.workflow_id}.xlsx",
        artifact_id=xlsx_id,
        inputs=[collection_id],
        evidence_port=evidence_port,
        admission_receipt=admission_receipt,
    )
    return WorkflowStepResult(
        artifact_ids=[collection_id, html_id, pdf_id, xlsx_id],
        row_counts={"steps": len(steps)},
        payload={"collection_id": collection_id},
    )


__all__ = [
    "EvidencePersistencePort",
    "WorkflowHostEndpointV1",
    "WorkflowAdmissionReceipt",
    "build_workflow_step_executor",
    "issue_server_evidence_port",
]
