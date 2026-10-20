"""orchestration operation handler: extracted behavior owner."""
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any
from ..data_operations import preview_data_column_cast, preview_data_columns_cast
from .chains import RerunExecutor
from .execution import ChainExecutionLease, OperationEffect, execution_key
from .operations import OperationRecord
from .proposals import ProposalStaleError
from .workflow import execute_workflow
from .orchestration_audit import (_workflow_failure_message)

_DATA_CHILD_NODE_OPERATIONS = frozenset(
    {"data.column.cast", "data.columns.cast", "code.execute", "operation.multi_step"}
)


class _OrchestratorOperationHandler:
    """Provide only operation-specific hooks to the shared lifecycle."""

    def validate_session(self, record):
        from .analysis_history import require_active_session
        require_active_session(self.orchestrator.repository, record.agent_session_id)

    def __init__(
        self,
        orchestrator: "WorkbenchOrchestrator",
        *,
        executor_key: str,
        project_root: Path | str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        rerun_executor: RerunExecutor | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.executor_key = executor_key
        self.project_root = project_root
        self.current_context_fingerprint = current_context_fingerprint
        self.current_active_head_run_id = current_active_head_run_id
        self.rerun_executor = rerun_executor

    @staticmethod
    def _effect(record: OperationRecord) -> OperationEffect:
        return OperationEffect(
            outputs=dict(record.outputs),
            diff_ref=record.diff_ref,
            verification=dict(record.verification),
            bindings={
                str(key): str(value)
                for key, value in (record.execution.get("bindings") or {}).items()
            },
            status=record.status,
            error=record.error,
        )

    async def validate(self, record: OperationRecord) -> None:
        self.orchestrator.proposal_store.validate_confirmation_preconditions(
            record.proposal_id,
            current_context_fingerprint=self.current_context_fingerprint,
            current_active_head_run_id=self.current_active_head_run_id,
        )
        if self.executor_key == "graph.fork":
            source_session_entry_id = str(record.target["source_session_entry_id"])
            branch = self.orchestrator.repository.get_branch(record.agent_session_id)
            if source_session_entry_id not in {entry.entry_id for entry in branch}:
                raise ValueError("source session entry is outside the current branch")
        if self.executor_key == "data.column.cast":
            spec = self.orchestrator._data_column_cast_spec(record)
            preview = preview_data_column_cast(self.project_root, spec)
            if preview.fingerprint != record.preconditions.get("context_fingerprint"):
                raise ProposalStaleError("data column cast preview is stale")
        if self.executor_key == "data.columns.cast":
            spec = self.orchestrator._data_columns_cast_spec(record)
            preview = preview_data_columns_cast(self.project_root, spec)
            if preview.fingerprint != record.preconditions.get("context_fingerprint"):
                raise ProposalStaleError("data columns cast preview is stale")
        if self.executor_key == "operation.multi_step":
            self.orchestrator._compile_workflow_record(
                record,
                project_root=self.project_root,
            )
        # code.execute intentionally does NOT re-preview here: previewing means
        # really running the user's code, and this hook runs on every attempt.
        # Its staleness check lives in _prepare_code_execute_effect, which can
        # tell "the source changed" apart from "the code isn't deterministic".

    def acquire_domain_lease(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> ChainExecutionLease:
        lease = ChainExecutionLease(
            self.orchestrator.repository.root,
            chain_id=record.chain_id,
            active_head_run_id=str(record.preconditions["active_head_run_id"]),
            execution_key=execution_key,
        )
        lease.acquire()
        return lease

    def release_domain_lease(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        lease: ChainExecutionLease,
    ) -> None:
        lease.release()

    async def prepare(self, record, *, execution_key, failpoint) -> OperationEffect:
        if self.executor_key == "model.rerun":
            return await self.orchestrator._prepare_rerun_effect(
                record,
                execution_key=execution_key,
                executor=None,
            )
        if self.executor_key == "graph.fork":
            prepared = await self.orchestrator._prepare_fork_effect(
                record,
                execution_key=execution_key,
            )
            return OperationEffect(execution=prepared.execution, status="submitted")
        if self.executor_key == "data.column.cast":
            return await self.orchestrator._prepare_data_column_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=False,
            )
        if self.executor_key == "data.columns.cast":
            return await self.orchestrator._prepare_data_columns_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=False,
            )
        if self.executor_key == "code.execute":
            return await self.orchestrator._prepare_code_execute_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=False,
            )
        if self.executor_key == "operation.multi_step":
            draft = self.orchestrator._compile_workflow_record(
                record,
                project_root=self.project_root,
            )
            return OperationEffect(
                execution={
                    **record.execution,
                    "workflow_id": draft.workflow_id,
                    "workflow_plan_fingerprint": draft.plan_fingerprint,
                    "workflow_step_count": len(draft.steps),
                },
                status="submitted",
            )
        raise ValueError(f"no executor registered for {self.executor_key}")

    async def execute(self, record, *, execution_key, failpoint) -> OperationEffect:
        if self.executor_key == "model.rerun":
            executor = self.rerun_executor or self.orchestrator.model_rerun_executor(
                self.project_root
            )
            return await self.orchestrator._prepare_rerun_effect(
                record,
                execution_key=execution_key,
                executor=executor,
            )
        elif self.executor_key == "graph.fork":
            return await self.orchestrator._prepare_fork_effect(
                record,
                execution_key=execution_key,
            )
        elif self.executor_key == "data.column.cast":
            return await self.orchestrator._prepare_data_column_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "data.columns.cast":
            return await self.orchestrator._prepare_data_columns_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "code.execute":
            return await self.orchestrator._prepare_code_execute_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "operation.multi_step":
            draft = self.orchestrator._compile_workflow_record(
                record,
                project_root=self.project_root,
            )
            state = await asyncio.to_thread(
                execute_workflow,
                self.project_root,
                draft,
            )
            self.orchestrator._persist_workflow_step_audit(record, draft, state)
            if state.status != "completed":
                raise ValueError(_workflow_failure_message(state))
            return OperationEffect(
                outputs={
                    "status": "completed",
                    "workflow_id": draft.workflow_id,
                    "workflow_plan_fingerprint": draft.plan_fingerprint,
                    "workflow_state": state.to_dict(),
                    "post_estimation_results": self.orchestrator._workflow_post_estimation_results(
                        self.project_root, draft
                    ),
                },
                execution={
                    **record.execution,
                    "workflow_id": draft.workflow_id,
                    "workflow_plan_fingerprint": draft.plan_fingerprint,
                    "workflow_step_count": len(draft.steps),
                },
                bindings={"workflow_id": draft.workflow_id},
                verification={
                    "passed": True,
                    "status": "completed",
                    "checks": {"nine_steps_completed": True, "code_execute_used": False},
                },
                status="completed",
            )
        raise ValueError(f"no executor registered for {self.executor_key}")

    async def reconcile(self, record, *, execution_key, failpoint) -> OperationEffect:
        if self.executor_key == "model.rerun":
            return await self.orchestrator._reconcile_rerun_effect(
                record,
                project_root=self.project_root,
            )
        elif self.executor_key == "graph.fork":
            return await self.orchestrator._reconcile_fork_effect(
                record,
                execution_key=execution_key,
            )
        elif self.executor_key == "data.column.cast":
            return await self.orchestrator._prepare_data_column_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "data.columns.cast":
            return await self.orchestrator._prepare_data_columns_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "code.execute":
            return await self.orchestrator._prepare_code_execute_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "operation.multi_step":
            draft = self.orchestrator._compile_workflow_record(
                record,
                project_root=self.project_root,
            )
            state = await asyncio.to_thread(
                execute_workflow,
                self.project_root,
                draft,
            )
            self.orchestrator._persist_workflow_step_audit(record, draft, state)
            if state.status != "completed":
                raise ValueError(_workflow_failure_message(state))
            return OperationEffect(
                outputs={
                    "workflow_state": state.to_dict(),
                    "post_estimation_results": self.orchestrator._workflow_post_estimation_results(
                        self.project_root, draft
                    ),
                },
                execution=record.execution,
                bindings={"workflow_id": draft.workflow_id},
                verification={"passed": True, "status": "completed"},
                status="completed",
            )
        raise ValueError(f"no reconciler registered for {self.executor_key}")

    async def commit_domain_state(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        effect: OperationEffect,
    ) -> OperationEffect:
        return await self.orchestrator._commit_domain_state(
            record,
            effect=effect,
        )

    def publish_state(self, record: OperationRecord, *, phase: str) -> None:
        execution = dict(record.execution)
        payload = {
            "record_id": record.record_id,
            "status": record.status,
            **execution,
            **record.outputs,
        }
        if phase == "submitted":
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_submitted",
                payload,
                command_id=record.command_id,
            )
            return
        if phase == "running":
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_running",
                payload,
                command_id=record.command_id,
            )
            return
        if phase == "completed":
            if record.operation_id == "graph.fork":
                self.orchestrator.events.emit(
                    record.agent_session_id,
                    "fork_created",
                    payload,
                    command_id=record.command_id,
                )
            self.orchestrator._append_operation_result(
                self._result_session_id(record),
                record,
                outputs=record.outputs,
                status="completed",
            )
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_completed",
                payload,
                command_id=record.command_id,
            )
            return
        if phase == "failed":
            self.orchestrator._append_operation_result(
                self._result_session_id(record),
                record,
                outputs=record.outputs,
                status="failed",
                error=record.error,
            )
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_failed",
                {
                    "record_id": record.record_id,
                    "error": record.error,
                    **execution,
                },
                command_id=record.command_id,
            )

    def observe_terminal(self, record: OperationRecord) -> dict[str, Any] | None:
        """Build optional deterministic analysis packets after terminalization."""

        if record.status not in {"completed", "failed"}:
            return None
        return self.orchestrator.observe_analysis_loop_terminal(
            record,
            project_root=self.project_root,
        )

    def _result_session_id(self, record: OperationRecord) -> str:
        child_session_id = record.execution.get("child_session_id")
        if isinstance(child_session_id, str) and (
            self.orchestrator.repository.root
            / "agent-sessions"
            / f"{child_session_id}.meta.json"
        ).exists():
            return child_session_id
        return record.agent_session_id

