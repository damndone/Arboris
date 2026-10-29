"""orchestration workflows: methods over the existing shared state."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Any
from .operations import OperationRecord
from .proposals import ProposalConfirmation
from .workflow import WorkflowDraft, WorkflowExecutionState

class OrchestrationWorkflows:
    def _compile_workflow_record(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
    ) -> WorkflowDraft:
        """Rebind a confirmed workflow proposal to the live source schema."""

        from ..statistical_exploration import resolve_statistical_source

        changes = record.changes or {}
        composed_steps = changes.get("steps")
        if composed_steps is None:
            raise ValueError(
                "operation.multi_step confirmed changes are missing steps"
            )
        source_context, frame = resolve_statistical_source(
            project_root,
            source_run_id=str(record.target["run_id"]),
            source_node_id=str(record.target["node_ref"]),
            source_artifact_id=str(record.target["artifact_id"]),
        )
        from .workflow import compile_workflow

        workflow_id = (
            record.workflow_id
            or record.execution.get("workflow_id")
            or f"workflow_{record.record_id}"
        )
        workflow = compile_workflow(
            workflow_id=str(workflow_id),
            target=record.target,
            preconditions={
                **record.preconditions,
                "source_artifact_fingerprint": source_context["source_sha256"],
            },
            steps=composed_steps,
            available_columns=[str(column) for column in frame.columns],
        )
        return replace(workflow, bindings=dict(record.execution.get("workflow_bindings", {})))


    def _workflow_post_estimation_results(
        self, project_root: Any, draft: WorkflowDraft
    ) -> list[dict[str, Any]]:
        """Bounded results this workflow produced, for the operation record.

        The Agent transcript renders the operation record, so without this a
        confirmed workflow can only report that it finished -- the number the
        user asked for stays in an artifact nobody opens.

        Scoped to this workflow id: the source run accumulates evidence from
        every workflow ever run against it, and replaying older findings under
        a new confirmation would misattribute them.
        """

        from pathlib import Path

        from .workflow_runtime import collect_post_estimation_results

        return collect_post_estimation_results(
            Path(project_root), str(draft.target["run_id"]), workflow_id=draft.workflow_id
        )


    def _persist_workflow_step_audit(
        self,
        parent: OperationRecord,
        draft: WorkflowDraft,
        state: WorkflowExecutionState,
    ) -> None:
        """Persist one auditable child record per compiled workflow step."""

        from .workflow_contracts import workflow_authorization

        confirmation_id = f"confirmation_{parent.record_id}"
        for step in draft.steps:
            step_state = state.steps[step.step_id]
            authorization = workflow_authorization(
                workflow_id=draft.workflow_id,
                confirmation_id=confirmation_id,
                step_id=step.step_id,
                plan_fingerprint=draft.plan_fingerprint,
            )
            confirmation = ProposalConfirmation(
                proposal_id=f"{draft.workflow_id}_{step.step_id}",
                operation_id=step.operation_id,
                operation_version=step.operation_version,
                revision=1,
                fingerprint=step.fingerprint,
                session_id=parent.agent_session_id,
                chain_id=parent.chain_id,
                command_id=parent.command_id,
                target={**draft.target, "workflow_step_id": step.step_id},
                preconditions={
                    "source_fingerprint": parent.preconditions.get("context_fingerprint", ""),
                    "dependency_fingerprints": [
                        draft_step.fingerprint
                        for draft_step in draft.steps
                        if draft_step.step_id in step.depends_on
                    ],
                },
                actor_type="workflow",
                confirmed_at=parent.confirmation.get("confirmed_at", ""),
                status="confirmed",
                changes={"compiled_spec": step.spec},
            )
            child = self.operation_store.create_pending(
                confirmation,
                command_id=parent.command_id,
                workflow_authorization=authorization,
            )
            if child.status in {"completed", "failed", "stale", "cancelled"}:
                continue
            status = step_state.status
            terminal_status = status if status in {'completed', 'cancelled'} else 'failed'
            not_executed = status == 'cancelled' and step_state.error == 'workflow_cancelled_before_execution'
            self.operation_store.append_status(
                child.record_id,
                terminal_status,
                execution={
                    **child.execution,
                    **authorization,
                    "workflow_step_status": status,
                },
                outputs={
                    "workflow_step_id": step.step_id,
                    "workflow_step_status": status,
                    "artifact_ids": list(step_state.artifact_ids),
                    "row_counts": dict(step_state.row_counts),
                    **({'execution_status': 'not_executed'} if not_executed else {}),
                },
                verification={
                    "passed": status == "completed",
                    "status": status,
                    "workflow_confirmation": confirmation_id,
                },
                error=(
                    {"type": 'WorkflowStepCancelled' if status == 'cancelled' else 'WorkflowStepFailed',
                     "message": step_state.error}
                    if status != "completed"
                    else None
                ),
            )

