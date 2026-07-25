"""Server-owned compilation and execution contracts for step workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..exploration_log import ExplorationLog
from .operations import OperationValidationError
from .storage import append_jsonl_atomic, read_jsonl
from .workflow_contracts import WORKFLOW_TEMPLATE, validate_workflow_steps


# Written into every plan and state record. Nothing compares it on read, so
# older records keep their previous value; it is metadata, not a gate.
WORKFLOW_SCHEMA_VERSION = "workflow.v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    operation_id: str
    operation_version: str
    depends_on: tuple[str, ...]
    spec: dict[str, Any]
    expected_artifacts: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "depends_on": list(self.depends_on),
            "spec": self.spec,
            "expected_artifacts": list(self.expected_artifacts),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class WorkflowDraft:
    workflow_id: str
    workflow_template: str
    target: dict[str, Any]
    preconditions: dict[str, Any]
    bindings: dict[str, Any]
    steps: tuple[WorkflowStep, ...]
    plan_fingerprint: str
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "workflow_id": self.workflow_id,
            "workflow_template": self.workflow_template,
            "target": self.target,
            "preconditions": self.preconditions,
            "bindings": self.bindings,
            "steps": [step.to_dict() for step in self.steps],
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status,
        }


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow cannot safely continue or resume."""


@dataclass(frozen=True)
class WorkflowStepResult:
    """Bounded result returned by one workflow step executor."""

    artifact_ids: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    empty_group_values: list[Any] = field(default_factory=list)
    result_fingerprint: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowStepState:
    step_id: str
    fingerprint: str
    status: str = "pending"
    artifact_ids: tuple[str, ...] = ()
    row_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    result_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "fingerprint": self.fingerprint,
            "status": self.status,
            "artifact_ids": list(self.artifact_ids),
            "row_counts": dict(self.row_counts),
            "error": self.error,
            "result_fingerprint": self.result_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowStepState":
        return cls(
            step_id=str(value["step_id"]),
            fingerprint=str(value["fingerprint"]),
            status=str(value.get("status", "pending")),
            artifact_ids=tuple(str(item) for item in value.get("artifact_ids", [])),
            row_counts={str(key): int(item) for key, item in (value.get("row_counts") or {}).items()},
            error=value.get("error"),
            result_fingerprint=value.get("result_fingerprint"),
        )


@dataclass(frozen=True)
class WorkflowExecutionState:
    workflow_id: str
    plan_fingerprint: str
    status: str
    steps: dict[str, WorkflowStepState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "workflow_state",
            "workflow_id": self.workflow_id,
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status,
            "steps": {key: value.to_dict() for key, value in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowExecutionState":
        return cls(
            workflow_id=str(value["workflow_id"]),
            plan_fingerprint=str(value["plan_fingerprint"]),
            status=str(value.get("status", "planned")),
            steps={
                str(key): WorkflowStepState.from_dict(item)
                for key, item in (value.get("steps") or {}).items()
            },
        )


class WorkflowStateStore:
    """Append-only workflow execution state used for resumable runs."""

    def __init__(self, project_root: Path | str, workflow_id: str) -> None:
        if not workflow_id or Path(workflow_id).name != workflow_id:
            raise ValueError("workflow_id must be path-safe")
        self.path = Path(project_root) / "workbench" / "workflows" / f"{workflow_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, state: WorkflowExecutionState) -> None:
        append_jsonl_atomic(self.path, state.to_dict())

    def current(self) -> WorkflowExecutionState | None:
        records = [item for item in read_jsonl(self.path) if item.get("record_type") == "workflow_state"]
        return WorkflowExecutionState.from_dict(records[-1]) if records else None


class WorkflowExecutor:
    """Execute a compiled workflow with fail-closed dependencies and resume."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    def execute(self, draft: WorkflowDraft, step_executor) -> WorkflowExecutionState:
        store = WorkflowStateStore(self.project_root, draft.workflow_id)
        existing = store.current()
        if existing is not None and existing.plan_fingerprint != draft.plan_fingerprint:
            raise WorkflowExecutionError("source fingerprint changed; workflow plan cannot resume")

        states: dict[str, WorkflowStepState] = {}
        if existing is not None:
            for step in draft.steps:
                previous = existing.steps.get(step.step_id)
                if previous is not None and previous.status == "completed":
                    if previous.fingerprint != step.fingerprint:
                        raise WorkflowExecutionError(
                            "source fingerprint changed; completed step cannot be reused"
                        )
                    states[step.step_id] = previous
                    continue
                states[step.step_id] = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                )
        else:
            states = {
                step.step_id: WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                )
                for step in draft.steps
            }

        state = WorkflowExecutionState(
            workflow_id=draft.workflow_id,
            plan_fingerprint=draft.plan_fingerprint,
            status="running",
            steps=states,
        )
        store.append(state)
        log = ExplorationLog(self.project_root, workflow_id=draft.workflow_id)
        completed_results: dict[str, WorkflowStepResult] = {
            step_id: WorkflowStepResult(
                artifact_ids=list(step_state.artifact_ids),
                row_counts=dict(step_state.row_counts),
                result_fingerprint=(
                    step_state.result_fingerprint or step_state.fingerprint
                ),
            )
            for step_id, step_state in states.items()
            if step_state.status == "completed"
        }

        for step in draft.steps:
            current = states[step.step_id]
            if current.status == "completed":
                continue
            dependency_states = [states[dependency] for dependency in step.depends_on]
            if any(item.status in {"failed", "blocked"} for item in dependency_states):
                states[step.step_id] = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                    status="blocked",
                    error="dependency failed or was blocked",
                )
                state = self._persist_state(store, draft, states, "failed")
                self._log_transition(log, draft, step, states[step.step_id], states)
                continue
            if any(item.status != "completed" for item in dependency_states):
                raise WorkflowExecutionError(
                    f"workflow dependency is not complete for {step.step_id}"
                )

            running = WorkflowStepState(
                step_id=step.step_id,
                fingerprint=step.fingerprint,
                status="running",
            )
            states[step.step_id] = running
            state = self._persist_state(store, draft, states, "running")
            self._log_transition(log, draft, step, running, states)
            try:
                result = step_executor(step, completed_results)
                if not isinstance(result, WorkflowStepResult):
                    raise WorkflowExecutionError(
                        f"workflow step {step.step_id} returned an invalid result"
                    )
                if result.empty_group_values:
                    raise WorkflowExecutionError(
                        f"workflow step {step.step_id} produced empty group values: "
                        + ", ".join(str(value) for value in result.empty_group_values)
                    )
                completed = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                    status="completed",
                    artifact_ids=tuple(result.artifact_ids),
                    row_counts=dict(result.row_counts),
                    result_fingerprint=(result.result_fingerprint or step.fingerprint),
                )
                states[step.step_id] = completed
                completed_results[step.step_id] = result
                state = self._persist_state(store, draft, states, "running")
                self._log_transition(log, draft, step, completed, states)
            except Exception as exc:
                failed = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                    status="failed",
                    error=str(exc),
                )
                states[step.step_id] = failed
                self._persist_state(store, draft, states, "failed")
                self._log_transition(log, draft, step, failed, states)
                changed = True
                while changed:
                    changed = False
                    for dependent in draft.steps:
                        if states[dependent.step_id].status != "pending":
                            continue
                        if any(
                            states[dependency].status in {"failed", "blocked"}
                            for dependency in dependent.depends_on
                        ):
                            states[dependent.step_id] = WorkflowStepState(
                                step_id=dependent.step_id,
                                fingerprint=dependent.fingerprint,
                                status="blocked",
                                error="dependency failed or was blocked",
                            )
                            self._log_transition(
                                log,
                                draft,
                                dependent,
                                states[dependent.step_id],
                                states,
                            )
                            changed = True
                break

        status = "failed" if any(item.status in {"failed", "blocked"} for item in states.values()) else "completed"
        return self._persist_state(store, draft, states, status)

    @staticmethod
    def _persist_state(store, draft, states, status):
        state = WorkflowExecutionState(
            workflow_id=draft.workflow_id,
            plan_fingerprint=draft.plan_fingerprint,
            status=status,
            steps=dict(states),
        )
        store.append(state)
        return state

    @staticmethod
    def _log_transition(log, draft, step, state, states) -> None:
        dependency_artifacts = [
            artifact_id
            for dependency in step.depends_on
            for artifact_id in states[dependency].artifact_ids
        ]
        log.append_event(
            {
                "event_id": f"{step.step_id}:{state.status}:{state.fingerprint[:16]}",
                "workflow_id": draft.workflow_id,
                "workflow_step_id": step.step_id,
                "operation_id": f"{step.operation_id}@{step.operation_version}",
                "spec_fingerprint": step.fingerprint,
                "source_artifact_ids": [str(draft.target["artifact_id"])],
                "dependency_artifact_ids": dependency_artifacts,
                "row_counts": state.row_counts,
                "status": state.status,
                "error": state.error,
                "artifact_ids": list(state.artifact_ids),
                "dependency_fingerprints": [
                    states[dependency].result_fingerprint
                    or states[dependency].fingerprint
                    for dependency in step.depends_on
                ],
            }
        )


def _make_step(
    *,
    step_id: str,
    operation_id: str,
    depends_on: tuple[WorkflowStep, ...],
    spec: dict[str, Any],
    expected_artifacts: tuple[str, ...],
) -> WorkflowStep:
    dependency_ids = tuple(step.step_id for step in depends_on)
    identity = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "step_id": step_id,
        "operation_id": operation_id,
        "operation_version": "v1",
        "depends_on": list(dependency_ids),
        "dependency_fingerprints": [step.fingerprint for step in depends_on],
        "spec": spec,
        "expected_artifacts": list(expected_artifacts),
    }
    return WorkflowStep(
        step_id=step_id,
        operation_id=operation_id,
        operation_version="v1",
        depends_on=dependency_ids,
        spec=spec,
        expected_artifacts=expected_artifacts,
        fingerprint=_fingerprint(identity),
    )


def compile_workflow(
    *,
    workflow_id: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    steps: Any,
    available_columns: list[str] | tuple[str, ...] | None = None,
    workflow_template: str = "agent-composed-v1",
) -> WorkflowDraft:
    """Compile an Agent-composed plan of arbitrary shape.

    The server owns the step KINDS and validates every spec with the same
    validators the manual UI uses; the plan's length, ordering and column
    choices belong to the request being answered, not to any one assignment.
    """

    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise OperationValidationError("workflow_id must be a non-empty string")
    missing_target = {
        key for key in ("run_id", "node_ref", "artifact_id") if not target.get(key)
    }
    if missing_target:
        raise OperationValidationError(
            "workflow target missing: " + ", ".join(sorted(missing_target))
        )
    if not preconditions.get("context_fingerprint"):
        raise OperationValidationError("workflow source context_fingerprint is required")

    ordered = validate_workflow_steps(steps, available_columns=available_columns)
    source_artifact_fingerprint = str(
        preconditions.get("source_artifact_fingerprint")
        or preconditions["context_fingerprint"]
    )

    compiled: dict[str, WorkflowStep] = {}
    for entry in ordered:
        compiled[entry["step_id"]] = _make_step(
            step_id=entry["step_id"],
            operation_id=entry["operation_id"],
            depends_on=tuple(compiled[dep] for dep in entry["depends_on"]),
            spec={
                **entry["spec"],
                "source_artifact_fingerprint": source_artifact_fingerprint,
            },
            expected_artifacts=tuple(entry["expected_artifacts"]),
        )
    compiled_steps = tuple(compiled[entry["step_id"]] for entry in ordered)
    return WorkflowDraft(
        workflow_id=workflow_id,
        workflow_template=workflow_template,
        target=dict(target),
        preconditions=dict(preconditions),
        bindings={},
        steps=compiled_steps,
        plan_fingerprint=_fingerprint(
            {
                "schema_version": WORKFLOW_SCHEMA_VERSION,
                "workflow_template": workflow_template,
                "target": dict(target),
                "steps": [step.to_dict() for step in compiled_steps],
            }
        ),
    )


def execute_workflow(
    project_root: Path | str,
    draft: WorkflowDraft,
) -> WorkflowExecutionState:
    """Execute a compiled workflow plan using native Workbench services."""

    from .workflow_runtime import build_workflow_step_executor

    return WorkflowExecutor(project_root).execute(
        draft,
        build_workflow_step_executor(project_root, draft),
    )


__all__ = [
    "WORKFLOW_SCHEMA_VERSION",
    "WorkflowDraft",
    "WorkflowExecutionError",
    "WorkflowExecutionState",
    "WorkflowExecutor",
    "WorkflowStateStore",
    "WorkflowStepResult",
    "WorkflowStep",
    "compile_workflow",
    "execute_workflow",
]
