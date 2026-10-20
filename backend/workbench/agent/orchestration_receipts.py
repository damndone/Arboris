"""orchestration receipts: methods over the existing shared state."""
from __future__ import annotations
from typing import Any
from .operation_outcome import result_view
from .operations import OperationRecord

class OrchestrationReceipts:
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

