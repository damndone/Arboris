"""Notebook execution evidence projection, without lifecycle mutation authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence



_TYPED_WORKFLOW_ERROR_CODE = re.compile(
    r"(?:^|[\s(])([A-Z][A-Z0-9_]{2,63}):"
)


def _bounded_workflow_error_code(*, status: str, error: object) -> str:
    """Return a stable error code without projecting arbitrary exception prose."""

    if status == "blocked":
        return "WORKFLOW_STEP_BLOCKED"
    if isinstance(error, str):
        match = _TYPED_WORKFLOW_ERROR_CODE.search(error)
        if match is not None:
            return match.group(1)
    return "WORKFLOW_STEP_FAILED"


@dataclass(frozen=True)
class ExecutionOutcome:
    """What a finished run did and did not earn.

    `execution_status` and `validation_status` are separate fields because
    spec §5.3 says they are separate questions: a model can fit and still fail
    to produce the table a report would cite.
    """

    option_id: str
    option_revision: int
    run_id: str | None
    execution_status: str
    artifact_validation: dict[str, Any]
    artifact_validation_scope: dict[str, Any]
    active_head_advanced: bool
    lifecycle_status: str

    @property
    def validation_status(self) -> str:
        return str(self.artifact_validation["validation_status"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "run_id": self.run_id,
            "execution_status": self.execution_status,
            "artifact_validation": dict(self.artifact_validation),
            "artifact_validation_scope": dict(self.artifact_validation_scope),
            "active_head_advanced": self.active_head_advanced,
            "lifecycle_status": self.lifecycle_status,
        }


def workflow_execution_receipt(project_root: Path, workflow: Any, state: Any, *, read_run_artifacts: Callable[[str], list[dict[str, Any]]]) -> dict[str, Any]:
    """Project durable workflow outputs without exposing model payloads."""

    from ...lineage.pipeline_drafts import PipelineDraftStore
    from ..p7_pack_registry import p7_pack_registry

    branches: list[dict[str, Any]] = []
    store = PipelineDraftStore(project_root)
    for summary in store.list():
        draft_id = summary.get("draft_id")
        if not isinstance(draft_id, str):
            continue
        try:
            stored = store.get(draft_id)
        except Exception:
            continue
        exploration = stored.draft.get("exploration_context")
        if not isinstance(exploration, Mapping) or exploration.get("workflow_id") != workflow.workflow_id:
            continue
        branch_id = exploration.get("branch_id")
        run_id = stored.draft.get("executed_run_id")
        if not isinstance(branch_id, str) or not isinstance(run_id, str) or not run_id:
            continue
        artifact_ids = sorted(
            {
                str(item.get("artifact_id"))
                for item in read_run_artifacts(run_id)
                if isinstance(item.get("artifact_id"), str) and item.get("artifact_id")
            }
        )
        branches.append(
            {
                "branch_id": branch_id,
                "run_id": run_id,
                "artifact_ids": artifact_ids,
            }
        )
    branches.sort(key=lambda item: (item["branch_id"], item["run_id"]))

    post_estimation_ids: list[str] = []
    p7_operation_ids = set(p7_pack_registry.operation_ids())
    steps_by_id = {step.step_id: step for step in workflow.steps}
    for step_id, step_state in state.steps.items():
        step = steps_by_id.get(step_id)
        if step is None:
            continue
        operation_id = str(step.operation_id)
        projects_analysis_artifact = (
            operation_id in p7_operation_ids
            or (
                operation_id.startswith("model.")
                and operation_id != "model.genesis"
            )
        )
        if not projects_analysis_artifact or step_state.status != "completed":
            continue
        post_estimation_ids.extend(str(value) for value in step_state.artifact_ids)

    failed_steps: list[dict[str, str]] = []
    for step_id, step_state in sorted(state.steps.items()):
        if step_state.status not in {"failed", "blocked"}:
            continue
        step = steps_by_id.get(step_id)
        if step is None:
            raise ValueError(
                f"workflow state references undeclared step {step_id!r}"
            )
        failed_steps.append(
            {
                "step_id": str(step_id),
                "operation_id": str(step.operation_id),
                "status": str(step_state.status),
                "error_code": _bounded_workflow_error_code(
                    status=str(step_state.status),
                    error=step_state.error,
                ),
            }
        )
    return {
        "workflow_id": workflow.workflow_id,
        "plan_fingerprint": workflow.plan_fingerprint,
        "status": str(state.status),
        "branch_runs": branches,
        "post_estimation_artifact_ids": sorted(set(post_estimation_ids)),
        "failed_steps": failed_steps,
    }


def workflow_produced_artifacts(workflow: Any, state: Any, *, read_run_artifacts: Callable[[str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Read only registered artifacts referenced by completed workflow state."""

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    source_run_id = str(workflow.target["run_id"])
    for step_state in state.steps.values():
        if step_state.status != "completed":
            continue
        for raw_id in step_state.artifact_ids:
            token = str(raw_id)
            if ":" in token:
                run_id, artifact_id = token.split(":", 1)
            else:
                run_id, artifact_id = source_run_id, token
            if not run_id or not artifact_id or (run_id, artifact_id) in seen:
                continue
            seen.add((run_id, artifact_id))
            records.extend(
                item
                for item in read_run_artifacts(run_id)
                if item.get("artifact_id") == artifact_id
            )
    return records


def contract_artifact_projection(
    contract: Any, ambient_records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Project ambient records by the current declaration-owned identities.

    Matching is intentionally by artifact identity only.  A record with a
    declared identity but the wrong type must remain in the validation view
    so the existing type guard can block the commit instead of being
    silently reclassified as missing.
    """

    expected_types = {
        str(expectation.artifact_id): str(expectation.artifact_type)
        for expectation in contract.expected
    }
    return [
        dict(record)
        for record in ambient_records
        if str(record.get("artifact_id")) in expected_types
    ]


def artifact_validation_scope(
    mode: str, ambient_records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Describe the validation input without reducing the ambient index."""

    ambient_artifact_ids = sorted(str(record.get("artifact_id")) for record in ambient_records)
    return {
        "mode": mode,
        "ambient_artifact_ids": ambient_artifact_ids,
        "ambient_artifact_count": len(ambient_artifact_ids),
    }
