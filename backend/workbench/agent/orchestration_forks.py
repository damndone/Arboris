"""orchestration forks: methods over the existing shared state."""
from __future__ import annotations
from .execution import OperationEffect, execution_key
from .operations import OperationRecord

class OrchestrationForks:
    async def _prepare_fork_effect(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> OperationEffect:
        """Create or discover a graph fork without lifecycle bookkeeping."""

        source_session_id = record.agent_session_id
        source_session_entry_id = str(record.target["source_session_entry_id"])
        source_run_id = str(record.target["run_id"])
        source_node_ref = str(record.target["node_ref"])
        fork_id, child_chain_id, child_session_id = self._deterministic_effect_ids(
            record,
            execution_key,
        )
        run_family_id = str(
            record.preconditions.get("run_family_id")
            or f"legacy-family:{source_run_id}"
        )
        execution = {
            **record.execution,
            "source_run_id": source_run_id,
            "source_node_ref": source_node_ref,
            "source_session_id": source_session_id,
            "source_session_entry_id": source_session_entry_id,
            "active_head_run_id": str(record.preconditions["active_head_run_id"]),
            "run_family_id": run_family_id,
            "fork_id": fork_id,
            "child_chain_id": child_chain_id,
            "child_session_id": child_session_id,
            "graph_fork_node_id": f"fork:{fork_id}",
        }
        self._ensure_child_context(
            record=record,
            source_session_entry_id=source_session_entry_id,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            run_family_id=run_family_id,
            fork_id=fork_id,
            child_chain_id=child_chain_id,
            child_session_id=child_session_id,
            context_fingerprint=str(record.preconditions["context_fingerprint"]),
            append_fork_context=True,
        )
        return OperationEffect(
            outputs={
                "fork_id": fork_id,
                "child_chain_id": child_chain_id,
                "child_session_id": child_session_id,
                "graph_fork_node_id": f"fork:{fork_id}",
                "status": "active",
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "fork_record": True,
                    "child_chain": True,
                    "child_session": True,
                },
            },
            bindings={
                "fork_id": fork_id,
                "child_chain_id": child_chain_id,
                "child_session_id": child_session_id,
            },
            execution=execution,
            status="completed",
        )


    async def _reconcile_fork_effect(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> OperationEffect:
        return await self._prepare_fork_effect(record, execution_key=execution_key)

