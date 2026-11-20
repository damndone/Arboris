"""orchestration audit: extracted behavior owner."""
from __future__ import annotations
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from .operations import OperationRecord
from .session import JsonlSessionRepository
from .workflow import WorkflowExecutionState

def _workflow_failure_message(state: WorkflowExecutionState) -> str:
    """Keep the failed step's server-owned error visible to the Agent."""

    failures = [
        f"{step_id}: {step.error or 'no step error was recorded'}"
        for step_id, step in state.steps.items()
        if step.status in {"failed", "blocked"}
    ]
    if not failures:
        return "workflow did not complete"
    return "workflow did not complete; failed steps: " + "; ".join(failures)


def _tests_per_step(outputs: Mapping[str, Any]) -> dict[str, int]:
    """How many tests each executed step reported (a by-group step: one per group)."""
    state = outputs.get("workflow_state") if isinstance(outputs, Mapping) else None
    steps = state.get("steps") if isinstance(state, Mapping) else None
    items = steps.values() if isinstance(steps, Mapping) else steps if isinstance(steps, list) else ()
    counts: dict[str, int] = {}
    for item in items:
        if isinstance(item, Mapping) and isinstance(item.get("row_counts"), Mapping):
            tests = item["row_counts"].get("ledger_count")
            if isinstance(tests, int) and tests > 0:
                counts[str(item.get("step_id"))] = tests
    return counts


def _record_operation_in_ledger(project_root: Any, record: OperationRecord) -> None:
    """Every executed Agent operation enters the analysis ledger."""

    from ..analysis_ledger import LedgerEntry, LedgerStep, record as record_entry

    if record.operation_id == "operation.multi_step":
        tests = _tests_per_step(record.outputs or {})
        steps = tuple(
            LedgerStep.of(str(step.get("operation_id", "")), str(step.get("step_id", "")),
                          tests=tests.get(str(step.get("step_id", "")), 1))
            for step in (record.changes.get("steps") or ())
            if isinstance(step, dict)
        )
    else:
        steps = (LedgerStep.of(record.operation_id),)
    outputs = record.outputs or {}
    source = record.operation_id
    if record.actor_type in {"human_ui", "human_cli"}:
        try:
            metadata = JsonlSessionRepository(Path(project_root) / "workbench", create=False).get_metadata(
                record.agent_session_id
            )
        except KeyError:
            metadata = {}
        manual_sources = {
            "manual_operation": "POST /operations/run",
            "manual_operation_cli": "workbench data (CLI)",
        }
        source = manual_sources.get(metadata.get("role"), source)
    record_entry(
        project_root,
        LedgerEntry(
            # Manual UI and CLI operations use the same lifecycle as Agent
            # proposals; durable adapter provenance identifies the user.
            actor="user" if record.actor_type in {"human_ui", "human_cli"} else "agent",
            authorized_by=(
                record.actor_type
                if record.actor_type in {"read_only_policy", "approved_plan", "session_grant", "project_rule"}
                else "user"
            ),
            source=source,
            status="completed" if record.status == "completed" else "failed",
            steps=steps,
            run_id=str(record.target.get("run_id") or "") or None,
            node_id=str(record.target.get("node_ref") or "") or None,
            produced_run_id=str(outputs.get("child_run_id") or outputs.get("run_id") or "") or None,
            session_id=record.agent_session_id,
            record_id=record.record_id,
            research_specification=record.execution.get("research_specification"),
        ),
    )

