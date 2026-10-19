"""orchestration receipts: methods over the existing shared state."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .chains import RerunExecutor
from .operation_outcome import result_view
from .operations import OperationRecord

class OrchestrationReceipts:
    async def reconcile_confirmed_proposal(
        self,
        record_id: str,
        *,
        project_root: Path | str,
        notebook_service=None,
    ) -> OperationRecord:
        """Compatibility wrapper around the shared lifecycle reconciler."""

        record = self.operation_store.get(record_id)
        if record.status in {"completed", "failed", "stale", "cancelled"}:
            return record
        return await self.execute_confirmed_operation(
            record_id,
            project_root=project_root,
            current_context_fingerprint=record.preconditions.get(
                "context_fingerprint"
            ),
            current_active_head_run_id=record.preconditions.get(
                "active_head_run_id"
            ),
            allow_recovery=True,
            notebook_service=notebook_service,
        )


    async def execute_confirmed_proposal(
        self,
        record_id: str,
        *,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        executor: RerunExecutor,
    ) -> OperationRecord:
        """Compatibility wrapper around the shared rerun lifecycle."""

        return await self.execute_confirmed_operation(
            record_id,
            project_root=self.repository.root.parent,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
            allow_recovery=True,
            rerun_executor=executor,
        )


    async def execute_confirmed_fork(
        self,
        record_id: str,
        *,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> OperationRecord:
        """Compatibility wrapper around the shared graph.fork lifecycle."""

        return await self.execute_confirmed_operation(
            record_id,
            project_root=self.repository.root.parent,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
            allow_recovery=True,
        )


    def _append_operation_result(
        self,
        session_id: str,
        record: OperationRecord,
        *,
        outputs: dict[str, Any],
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "record_id": record.record_id,
            "operation_id": record.operation_id,
            "status": status,
            "outputs": outputs,
            "error": error,
        }
        self.repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "operation_result",
                "audience": "model",
                "content": result_view(payload, read_with={
                    "owner_run_id": (record.target or {}).get("run_id"),
                    "op_node_id": (record.target or {}).get("node_ref"),
                    "operation_record_id": record.record_id,
                }),
                "operation_result": payload,
            },
        )

