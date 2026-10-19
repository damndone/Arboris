"""orchestration reruns: methods over the existing shared state."""
from __future__ import annotations
import inspect
from pathlib import Path
from ..lineage.rerun_provenance import run_rerun_from_from_context
from ..services.rerun_service import RerunReconciliationRequest, RerunService, RerunSubmissionRequest
from ..lineage.run_inputs import read_run_inputs
from .chains import RerunExecutionRequest, RerunExecutionResult, RerunExecutor
from .execution import OperationEffect, execution_key
from .operations import OperationRecord
from .operation_handlers.proposal_arguments import _overrides_from_proposal_changes

class OrchestrationReruns:
    def _find_rerun_child_run_id(
        self,
        record: OperationRecord,
        execution_key_value: str,
    ) -> str | None:
        """Find an already materialized child before retrying submission.

        The run input is the durable effect witness. If a process dies after
        the rerun service creates the child but before the operation record
        binds it, retry must bind this witness instead of submitting another
        child run.
        """

        runs_root = self.repository.root.parent / "runs"
        matches: list[str] = []
        if not runs_root.exists():
            return None
        for run_root in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            try:
                inputs = read_run_inputs(run_root)
            except (FileNotFoundError, OSError, ValueError):
                continue
            context = inputs.get("workbench_context")
            if not isinstance(context, dict):
                continue
            if context.get("operation_record_id") != record.record_id:
                continue
            witness_key = context.get("execution_key")
            if witness_key is not None and witness_key != execution_key_value:
                continue
            matches.append(run_root.name)
        if len(matches) > 1:
            raise ValueError("multiple_child_runs_for_operation")
        return matches[0] if matches else None


    def _has_fork_context(self, session_id: str, fork_id: str) -> bool:
        try:
            branch = self.repository.get_branch(session_id)
        except (KeyError, ValueError):
            return False
        return any(
            entry.entry_type == "custom_message"
            and entry.payload.get("message_type") == "fork_context"
            and (entry.payload.get("metadata") or {}).get("fork_id") == fork_id
            for entry in branch
        )


    def model_rerun_executor(self, project_root: Path | str) -> RerunExecutor:
        """Build the Agent adapter over the request-independent rerun service."""

        service = RerunService(project_root)

        async def execute(request: RerunExecutionRequest) -> RerunExecutionResult:
            workbench_context = {
                "operation_id": request.operation_id,
                "operation_version": request.operation_version,
                "operation_record_id": request.operation_record_id,
                "proposal_id": request.proposal_id,
                "source_chain_id": request.source_chain_id,
                "source_session_id": request.source_session_id,
                "source_run_id": request.source_run_id,
                "source_node_ref": request.source_node_ref,
                "context_version": request.context_version,
                "context_fingerprint": request.context_fingerprint,
                "owner_run_id": request.owner_run_id,
                "op_node_id": request.op_node_id,
                "node_hash": request.node_hash,
                "forest_node_key": request.forest_node_key,
                "owner_resolution": request.owner_resolution,
                "active_head_run_id": request.active_head_run_id,
                "fork_id": request.fork_id,
                "child_chain_id": request.child_chain_id,
                "child_session_id": request.child_session_id,
            }
            if request.execution_key:
                workbench_context["execution_key"] = request.execution_key
            for field_name in (
                "confirmed_payload_hash",
                "executed_proposal_payload_hash",
                "plan_hash",
                "canonical_patch_hash",
            ):
                value = getattr(request, field_name, "")
                if value:
                    workbench_context[field_name] = value
            submission = service.submit(
                RerunSubmissionRequest(
                    source_run_id=request.source_run_id,
                    from_node=request.source_node_ref,
                    op_overrides=_overrides_from_proposal_changes(request.changes),
                    rerun_reason="agent_confirmed",
                    # metadata.edit may declare columns outside the model.
                    metadata_edit=request.operation_id == "metadata.edit",
                    # Node provenance (RunRerunFrom): this operation record is
                    # the rerun request, validated against the node-operation
                    # context it carries. Without such a context there is no
                    # fingerprint to revalidate the source by, so none is claimed.
                    rerun_from=(
                        run_rerun_from_from_context(
                            request_id=request.operation_record_id,
                            owner_run_id=request.source_run_id,
                            op_node_id=request.source_node_ref,
                            node_hash=request.node_hash,
                            context_fingerprint=request.context_fingerprint,
                        )
                        if request.context_version == "node-operation-context/v1"
                        else None
                    ),
                    workbench_context=workbench_context,
                )
            )
            return RerunExecutionResult(
                target_run_id=submission.run_id,
                outputs={"status": submission.status},
            )

        return execute


    async def _prepare_rerun_effect(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        executor: RerunExecutor | None,
    ) -> OperationEffect:
        """Create or discover the rerun effect without lifecycle bookkeeping."""

        source_session_id = record.agent_session_id
        source_metadata = self.repository.get_metadata(source_session_id)
        source_leaf_id = source_metadata.get("leaf_entry_id")
        if not isinstance(source_leaf_id, str) or not source_leaf_id:
            raise ValueError("source session has no stable leaf")

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
        proposal = self.proposal_store.latest_revision(record.proposal_id)
        executed_proposal_payload_hash = ""
        analysis_loop_binding = self._analysis_loop_binding(record)
        if analysis_loop_binding is not None:
            from ..analysis_loop.plan import confirmed_payload_hash_for_plan
            from ..analysis_loop.storage import PlanDiffStore

            plan_logical_key = analysis_loop_binding.get("plan_logical_key")
            if type(plan_logical_key) is not str or not plan_logical_key:
                raise ValueError("analysis-loop proposal has no PlanDiff logical key")
            plan_packet = PlanDiffStore(
                self.repository.root,
                create=False,
            ).get_terminal_packet(plan_logical_key)
            if plan_packet is None:
                raise ValueError("analysis-loop PlanDiff terminal packet is unavailable")
            executed_proposal_payload_hash = confirmed_payload_hash_for_plan(
                plan_packet.plan_diff,
                proposal_id=proposal.proposal_id,
                revision=proposal.revision,
                operation_version=record.operation_version,
                target=proposal.target,
                preconditions=proposal.preconditions,
                changes=proposal.changes,
            )
            confirmed_payload_hash = str(
                record.preconditions.get("confirmed_payload_hash") or ""
            )
            if executed_proposal_payload_hash != confirmed_payload_hash:
                raise ValueError("confirmed_executed_proposal_hash_mismatch")
            persisted_payload_hash = record.execution.get(
                "executed_proposal_payload_hash"
            )
            if (
                persisted_payload_hash
                and persisted_payload_hash != executed_proposal_payload_hash
            ):
                raise ValueError("executed_proposal_hash_witness_mismatch")
        execution = {
            **record.execution,
            "source_run_id": source_run_id,
            "source_node_ref": source_node_ref,
            "source_session_id": source_session_id,
            "source_session_entry_id": source_leaf_id,
            "active_head_run_id": str(record.preconditions["active_head_run_id"]),
            "run_family_id": run_family_id,
            "fork_id": fork_id,
            "child_chain_id": child_chain_id,
            "child_session_id": child_session_id,
        }
        if executed_proposal_payload_hash:
            execution[
                "executed_proposal_payload_hash"
            ] = executed_proposal_payload_hash
        self._ensure_child_context(
            record=record,
            source_session_entry_id=source_leaf_id,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            run_family_id=run_family_id,
            fork_id=fork_id,
            child_chain_id=child_chain_id,
            child_session_id=child_session_id,
            context_fingerprint=str(record.preconditions["context_fingerprint"]),
            append_fork_context=False,
        )
        request = RerunExecutionRequest(
            operation_id=record.operation_id,
            operation_version=record.operation_version,
            operation_record_id=record.record_id,
            proposal_id=record.proposal_id,
            source_chain_id=record.chain_id,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            context_version=str(record.preconditions["context_version"]),
            context_fingerprint=str(record.preconditions["context_fingerprint"]),
            owner_run_id=str(record.target["run_id"]),
            op_node_id=str(record.target["node_ref"]),
            node_hash=str(record.target["node_hash"]),
            forest_node_key=str(record.target["forest_node_key"]),
            owner_resolution=str(record.preconditions["owner_resolution"]),
            active_head_run_id=str(record.preconditions["active_head_run_id"]),
            changes=dict(proposal.changes),
            fork_id=fork_id,
            child_chain_id=child_chain_id,
            child_session_id=child_session_id,
            execution_key=execution_key,
            confirmed_payload_hash=str(
                record.preconditions.get("confirmed_payload_hash") or ""
            ),
            executed_proposal_payload_hash=executed_proposal_payload_hash,
            plan_hash=str(record.preconditions.get("plan_hash") or ""),
            canonical_patch_hash=str(
                record.preconditions.get("canonical_patch_hash") or ""
            ),
        )
        if executor is None:
            return OperationEffect(execution=execution, status="submitted")
        bound_child_run_id = (record.execution.get("bindings") or {}).get(
            "child_run_id"
        )
        witnessed_child_run_id = self._find_rerun_child_run_id(record, execution_key)
        if bound_child_run_id:
            if witnessed_child_run_id != bound_child_run_id:
                raise ValueError("bound_child_run_witness_missing")
            result = RerunExecutionResult(
                target_run_id=str(bound_child_run_id),
                outputs={"status": "submitted"},
            )
        elif witnessed_child_run_id:
            result = RerunExecutionResult(
                target_run_id=witnessed_child_run_id,
                outputs={"status": "submitted"},
            )
        else:
            result = executor(request)
            if inspect.isawaitable(result):
                result = await result
        if not isinstance(result, RerunExecutionResult):
            raise TypeError("rerun executor returned an invalid result")

        result_status = str(result.outputs.get("status", "completed"))
        if result_status in {"running", "submitted"}:
            operation_status = "running"
        elif result_status == "completed":
            operation_status = "completed"
        else:
            raise RuntimeError(
                f"rerun executor returned unexpected status: {result_status}"
            )
        return OperationEffect(
            outputs={**result.outputs, "target_run_id": result.target_run_id},
            diff_ref=result.diff_ref,
            verification=result.verification,
            bindings={
                "fork_id": fork_id,
                "child_chain_id": child_chain_id,
                "child_session_id": child_session_id,
                "child_run_id": result.target_run_id,
            },
            execution=execution,
            status=operation_status,
        )


    async def _reconcile_rerun_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
    ) -> OperationEffect:
        """Rebuild rerun outputs from the immutable child-run witness."""

        target_run_id = (record.execution.get("bindings") or {}).get(
            "child_run_id"
        ) or record.outputs.get("target_run_id")
        if not isinstance(target_run_id, str) or not target_run_id:
            raise ValueError("operation record has no target run")
        source_run_id = str(record.target["run_id"])
        source_node_ref = str(record.target["node_ref"])
        execution = record.execution
        workbench_context = {
            "operation_id": record.operation_id,
            "operation_version": record.operation_version,
            "operation_record_id": record.record_id,
            "proposal_id": record.proposal_id,
            "source_chain_id": record.chain_id,
            "source_session_id": record.agent_session_id,
            "source_run_id": source_run_id,
            "source_node_ref": source_node_ref,
            "context_version": str(record.preconditions["context_version"]),
            "context_fingerprint": str(record.preconditions["context_fingerprint"]),
            "owner_run_id": str(record.target["run_id"]),
            "op_node_id": str(record.target["node_ref"]),
            "node_hash": str(record.target["node_hash"]),
            "forest_node_key": str(record.target["forest_node_key"]),
            "owner_resolution": str(record.preconditions["owner_resolution"]),
            "active_head_run_id": execution["active_head_run_id"],
            "fork_id": execution["fork_id"],
            "child_chain_id": execution["child_chain_id"],
            "child_session_id": execution["child_session_id"],
            "execution_key": execution.get("execution_key"),
        }
        for field_name in (
            "confirmed_payload_hash",
            "plan_hash",
            "canonical_patch_hash",
        ):
            value = record.preconditions.get(field_name)
            if value:
                workbench_context[field_name] = value
        executed_proposal_payload_hash = execution.get(
            "executed_proposal_payload_hash"
        )
        if executed_proposal_payload_hash:
            workbench_context[
                "executed_proposal_payload_hash"
            ] = executed_proposal_payload_hash
        request = RerunReconciliationRequest(
            source_run_id=source_run_id,
            target_run_id=target_run_id,
            from_node=source_node_ref,
            op_overrides=_overrides_from_proposal_changes(
                self.proposal_store.latest_revision(record.proposal_id).changes
            ),
            workbench_context=workbench_context,
        )
        try:
            reconciliation = RerunService(project_root).reconcile_submission(request)
        except Exception as exc:
            return OperationEffect(
                outputs=dict(record.outputs),
                bindings={
                    str(key): str(value)
                    for key, value in (record.execution.get("bindings") or {}).items()
                },
                execution=execution,
                status="failed",
                error={"type": type(exc).__name__, "message": str(exc)},
            )

        outputs = {
            **record.outputs,
            **reconciliation.outputs,
            "target_run_id": target_run_id,
        }
        if reconciliation.status in {"running", "submitted"}:
            status = "running"
        elif (
            reconciliation.status == "completed"
            and reconciliation.verification.get("passed") is True
        ):
            status = "completed"
        else:
            status = "failed"
        return OperationEffect(
            outputs=outputs,
            diff_ref=reconciliation.diff_ref,
            verification=reconciliation.verification,
            bindings={
                str(key): str(value)
                for key, value in (record.execution.get("bindings") or {}).items()
            },
            execution=execution,
            status=status,
            error=reconciliation.error,
        )

