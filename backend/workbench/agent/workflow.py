"""Server-owned compilation and execution contracts for Class 3 workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..exploration_log import ExplorationLog
from .operations import OperationValidationError
from .storage import append_jsonl_atomic, read_jsonl
from .workflow_contracts import (
    validate_workflow_steps,
    CLASS3_GROUP_VALUES,
    CLASS3_WORKFLOW_TEMPLATE,
    compile_step_bindings,
)


WORKFLOW_SCHEMA_VERSION = "class3-workflow.v1"
_THRESHOLD_REF = {"step_id": "step-4", "artifact_role": "result"}


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


def compile_class3_workflow(
    *,
    workflow_id: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    bindings: Mapping[str, Any],
    available_columns: list[str] | tuple[str, ...] | None = None,
    group_value_witness: list[Any] | tuple[Any, ...] | None = None,
) -> WorkflowDraft:
    """Compile the Stata-semantics template from typed source bindings.

    The grouping values come from the proposal and are checked against the real
    column contents, so the same template serves any panel rather than only the
    reference exercise's years.
    """

    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise OperationValidationError("workflow_id must be a non-empty string")
    required_target = {"run_id", "node_ref", "artifact_id"}
    missing_target = {key for key in required_target if not target.get(key)}
    if missing_target:
        raise OperationValidationError(
            "workflow target missing: " + ", ".join(sorted(missing_target))
        )
    if not preconditions.get("context_fingerprint"):
        raise OperationValidationError("workflow source context_fingerprint is required")
    bound = compile_step_bindings(
        bindings,
        available_columns=available_columns,
        group_value_witness=group_value_witness,
    )
    source_artifact_fingerprint = str(
        preconditions.get("source_artifact_fingerprint")
        or preconditions["context_fingerprint"]
    )

    def make_step(**kwargs):
        step_kwargs = dict(kwargs)
        raw_spec = dict(step_kwargs.pop("spec"))
        return _make_step(
            **step_kwargs,
            spec={
                **raw_spec,
                "source_artifact_fingerprint": source_artifact_fingerprint,
            },
        )

    year = bound["year_column"]
    spending = bound["spending_column"]
    black = bound["black_column"]
    poverty = bound["poverty_column"]
    enrollment = bound["enrollment_column"]
    numeric = list(bound["all_numeric_columns"])
    groups = list(bound["group_values"])

    step1 = make_step(
        step_id="step-1",
        operation_id="statistical.explore",
        depends_on=(),
        spec={
            "operation": "summarize",
            "selected_columns": numeric,
            "filters": [],
            "options": {"group_by": year, "group_values": groups},
            "missing_policy": "variablewise",
        },
        expected_artifacts=("table.grouped_descriptive_statistics",),
    )
    step2 = make_step(
        step_id="step-2",
        operation_id="statistical.explore",
        depends_on=(),
        spec={
            "operation": "misstable",
            "selected_columns": numeric,
            "filters": [],
            "options": {},
            "missing_policy": "variablewise",
        },
        expected_artifacts=("table.missingness",),
    )
    step3 = make_step(
        step_id="step-3",
        operation_id="statistical.explore",
        depends_on=(),
        spec={
            "operation": "corr",
            "selected_columns": numeric,
            "filters": [],
            "options": {"missing_policy": "listwise"},
            "missing_policy": "listwise",
        },
        expected_artifacts=("table.correlation_matrix",),
    )
    step4 = make_step(
        step_id="step-4",
        operation_id="statistical.explore",
        depends_on=(),
        spec={
            "operation": "summarize_detail",
            "selected_columns": [enrollment, poverty],
            "filters": [],
            "options": {
                "quantile_method": "stata_summarize_detail_v1",
                "percentiles": [1, 5, 10, 25, 50, 75, 90, 95, 99],
            },
            "missing_policy": "variablewise",
        },
        expected_artifacts=("table.detailed_descriptive_statistics",),
    )
    recipes = (
        {
            "source_column": enrollment,
            "percentile": 25,
            "comparison": "lte",
            "output_name": "small_school",
            "threshold_ref": dict(_THRESHOLD_REF),
        },
        {
            "source_column": enrollment,
            "percentile": 75,
            "comparison": "gte",
            "output_name": "large_school",
            "threshold_ref": dict(_THRESHOLD_REF),
        },
        {
            "source_column": poverty,
            "percentile": 75,
            "comparison": "gte",
            "output_name": "poor_school",
            "threshold_ref": dict(_THRESHOLD_REF),
        },
        {
            "source_column": poverty,
            "percentile": 25,
            "comparison": "lte",
            "output_name": "least_poor_school",
            "threshold_ref": dict(_THRESHOLD_REF),
        },
    )
    step5 = make_step(
        step_id="step-5",
        operation_id="statistical.derive_boolean",
        depends_on=(step4,),
        spec={
            "operation": "derive_boolean",
            "quantile_method": "stata_summarize_detail_v1",
            "recipes": list(recipes),
            "threshold_source": dict(_THRESHOLD_REF),
        },
        expected_artifacts=("derived_data.grouping_booleans", "recipe.boolean_groups"),
    )
    step6 = make_step(
        step_id="step-6",
        operation_id="statistical.derived_group_summarize",
        # The derived columns come from step5; the thresholds that define them
        # come from step4. Both are real dependencies, so both are declared —
        # the runtime resolves percentile evidence through depends_on.
        depends_on=(step5, step4),
        spec={
            # Self-describing: the runtime summarises exactly these groups over
            # exactly these columns. Nothing about which groups exist, or what
            # they are called, lives in the executor any more.
            "groups": [
                {
                    "source_column": recipe["source_column"],
                    "percentile": recipe["percentile"],
                    "comparison": recipe["comparison"],
                    "output_name": recipe["output_name"],
                }
                for recipe in recipes
            ],
            "summarize_columns": [spending],
            "missing_policy": "variablewise",
        },
        expected_artifacts=("table.grouped_spending_statistics",),
    )
    scatter_specs = [
        {"x_column": poverty, "y_column": spending},
        {"x_column": enrollment, "y_column": spending},
    ]
    step7 = make_step(
        step_id="step-7",
        operation_id="statistical.explore",
        depends_on=(),
        spec={
            "operation": "scatter",
            "plots": scatter_specs,
            "missing_policy": "complete_case_for_plot",
        },
        expected_artifacts=("figure.spending_vs_poverty", "figure.spending_vs_enrollment"),
    )
    step8 = make_step(
        step_id="step-8",
        operation_id="model.genesis",
        depends_on=(step1, step2, step3, step4, step5, step6, step7),
        spec={
            "model_family": "ols",
            "covariance": "unadjusted",
            "branches": [
                {
                    "branch_id": "ols_pblack",
                    "outcome": spending,
                    "predictors": [black],
                    "covariance": "unadjusted",
                },
                {
                    "branch_id": "ols_pblack_pfl",
                    "outcome": spending,
                    "predictors": [black, poverty],
                    "covariance": "unadjusted",
                },
            ],
            "expected_artifacts": [
                "coefficient_ci",
                "sample_size",
                "residual_diagnostics",
                "fitted_diagnostics",
            ],
        },
        expected_artifacts=(
            "model.ols_pblack",
            "model.ols_pblack_pfl",
            "model.coefficient_ci",
            "coefficient_ci",
            "sample_size",
            "residual_diagnostics",
            "fitted_diagnostics",
            "model.sample_size",
            "figure.residuals_vs_poverty",
            "figure.residuals_vs_black",
            "figure.fitted_vs_poverty",
        ),
    )
    step9 = make_step(
        step_id="step-9",
        operation_id="report.class3",
        depends_on=(step1, step2, step3, step4, step5, step6, step7, step8),
        spec={
            "report_contract": "class3-complete-v1",
            "required_steps": [f"step-{index}" for index in range(1, 9)],
            "formats": ["html", "pdf", "xlsx"],
            "complete_only": True,
        },
        expected_artifacts=("report.class3.html", "report.class3.pdf", "report.class3.xlsx"),
    )
    steps = (step1, step2, step3, step4, step5, step6, step7, step8, step9)
    plan_identity = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "workflow_template": CLASS3_WORKFLOW_TEMPLATE,
        "target": dict(target),
        "preconditions": dict(preconditions),
        "bindings": bound,
        "steps": [step.to_dict() for step in steps],
    }
    return WorkflowDraft(
        workflow_id=workflow_id,
        workflow_template=CLASS3_WORKFLOW_TEMPLATE,
        target=dict(target),
        preconditions=dict(preconditions),
        bindings=bound,
        steps=steps,
        plan_fingerprint=_fingerprint(plan_identity),
    )


def execute_class3_workflow(
    project_root: Path | str,
    draft: WorkflowDraft,
) -> WorkflowExecutionState:
    """Execute the compiled Class 3 template using native Workbench services."""

    from .workflow_runtime import build_class3_step_executor

    return WorkflowExecutor(project_root).execute(
        draft,
        build_class3_step_executor(project_root, draft),
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
    "compile_class3_workflow",
    "execute_class3_workflow",
]
