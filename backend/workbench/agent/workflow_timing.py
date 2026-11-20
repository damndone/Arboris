"""Local observations for exact source-bound workflows."""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS, WORKFLOW_TEMPLATE

if TYPE_CHECKING:
    from .plan_preflight import RegisteredSource
    from .workflow import WorkflowDraft, WorkflowStep

_SHA256 = re.compile(r"[0-9a-f]{64}")
_DIRECT_SOURCE_DISPATCHERS = frozenset({
    "workbench.agent.workflow_runtime.statistical_explore",
    "workbench.agent.workflow_runtime.statistical_named_test",
    "workbench.services.genesis",
})
_DIRECTORY = "workflow-timings"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_RECORD_SUFFIX = ".v1.json"
_MAX_RECORD_BYTES = 512
_MAX_ELAPSED_NS = (1 << 63) - 1


def _direct_source(step: WorkflowStep) -> bool:
    contract = WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id]
    if "source" in step.spec or not contract.consumes_input_frame or contract.model_reference_fields:
        return False
    return (
        contract.dispatcher_key in _DIRECT_SOURCE_DISPATCHERS
        or (contract.capability_kind == "statistical_test"
            and contract.dispatcher_key == "workbench.agent.workflow_runtime.workflow_capability")
    )


def _workload_key(draft: WorkflowDraft) -> str | None:
    # These dispatchers consume the selected table and the compiled parameters.
    # Extension, upstream-artifact and runtime-bound workloads need more input receipts.
    if (draft.workflow_template != WORKFLOW_TEMPLATE or draft.bindings or not draft.steps
            or not all(_direct_source(step) for step in draft.steps)):
        return None
    digest = draft.preconditions.get("source_artifact_fingerprint")
    tag, _, key = draft.plan_fingerprint.partition(":")
    if isinstance(digest, str) and _SHA256.fullmatch(digest) and tag == "sha256" and _SHA256.fullmatch(key):
        return key
    return None


@contextmanager
def _timing_directory(root: Path, *, create: bool = False):
    workbench_fd = os.open(root / "workbench", _DIRECTORY_FLAGS)
    try:
        if create:
            try:
                os.mkdir(_DIRECTORY, mode=0o700, dir_fd=workbench_fd)
            except FileExistsError:
                pass
        directory_fd = os.open(_DIRECTORY, _DIRECTORY_FLAGS, dir_fd=workbench_fd)
        try:
            yield directory_fd
        finally:
            os.close(directory_fd)
    finally:
        os.close(workbench_fd)


@dataclass(frozen=True)
class WorkflowTiming:
    root: Path
    key: str
    source: RegisteredSource
    source_generation: str
    started_ns: int

    def matches_source(self, context: Mapping[str, Any]) -> bool:
        try:
            if (context.get("source_sha256") != self.source.sha256
                    or context.get("source_run_id") != self.source.run_id
                    or context.get("source_node_id") != self.source.node_ref
                    or context.get("source_artifact_id") != self.source.artifact_id):
                return False
            path = (self.root / "runs" / self.source.run_id / context["source_artifact_path"]).resolve()
            return path == self.source.path and self.source.file_generation() == self.source_generation
        except (KeyError, OSError, TypeError, ValueError):
            return False

    def record(self, workflow_id: str) -> None:
        elapsed = perf_counter_ns() - self.started_ns
        if not 0 < elapsed <= _MAX_ELAPSED_NS:
            return
        try:
            if self.source.file_generation() != self.source_generation:
                return
            raw = json.dumps({"key": self.key, "source_generation": self.source_generation,
                              "workflow_id": workflow_id, "elapsed_ns": elapsed}).encode("utf-8")
            if len(raw) > _MAX_RECORD_BYTES:
                return
            with _timing_directory(self.root, create=True) as directory_fd:
                temporary = f".{uuid4().hex}.tmp"
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self.key + _RECORD_SUFFIX, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
        except OSError:
            # Optional history cannot change the outcome of a completed execution.
            return


def begin_workflow_timing(root: Path, draft: WorkflowDraft) -> WorkflowTiming | None:
    from .plan_preflight import registered_workflow_source

    try:
        key = _workload_key(draft)
        if key is not None:
            source = registered_workflow_source(root, draft.target)
            if (source.artifact_id == draft.target["artifact_id"]
                    and source.sha256 == draft.preconditions["source_artifact_fingerprint"]
                    and (generation := source.file_generation()) is not None):
                return WorkflowTiming(root, key, source, generation, perf_counter_ns())
    except (KeyError, OSError, TypeError, ValueError):
        pass
    return None


def estimated_workflow_seconds(root: Path, draft: WorkflowDraft, source: RegisteredSource) -> float | None:
    """Read one successful observation, matched to the input's verified file generation."""
    try:
        key = _workload_key(draft)
        if key is None:
            return None
        with _timing_directory(root) as directory_fd:
            fd = os.open(key + _RECORD_SUFFIX, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            with os.fdopen(fd, "rb") as handle:
                if not S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return None
                raw = handle.read(_MAX_RECORD_BYTES + 1)
        if len(raw) <= _MAX_RECORD_BYTES:
            record = json.loads(raw)
            if (isinstance(record, dict) and record.get("key") == key and
                    isinstance(record.get("workflow_id"), str) and record["workflow_id"] and
                    isinstance(record.get("source_generation"), str) and
                    record["source_generation"] == source.file_generation()):
                elapsed = record.get("elapsed_ns")
                if type(elapsed) is int and 0 < elapsed <= _MAX_ELAPSED_NS:
                    return max(0.001, round(elapsed / 1_000_000_000, 3))
    except (KeyError, OSError, TypeError, ValueError):
        pass
    return None
