"""orchestration analysis loop: methods over the existing shared state."""
from __future__ import annotations
from pathlib import Path
from time import perf_counter
from typing import Any
from .operations import OperationRecord

class OrchestrationAnalysisLoop:
    @staticmethod
    def _analysis_loop_binding(record: OperationRecord) -> dict[str, Any] | None:
        binding = record.preconditions.get("analysis_loop")
        return dict(binding) if isinstance(binding, dict) else None


    def observe_analysis_loop_terminal(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
    ) -> dict[str, Any] | None:
        """Materialize post-rerun packets from terminal persisted evidence.

        Packet construction is deliberately supplementary: a packet build
        failure is reported as an observable analysis-loop status and never
        rewrites an already terminal operation into a second execution.
        """

        if record.operation_id != "model.rerun":
            return None
        binding = self._analysis_loop_binding(record)
        if binding is None:
            return None
        observation_started = perf_counter()
        try:
            # Keep packet storage/observation imports lazy: the analysis-loop
            # storage module depends on the Agent persistence package, whose
            # package initializer also exposes this orchestrator.
            from ..analysis_loop.observation import build_and_store_analysis_loop_packets
            from ..canonical import sha256_canonical
            from ..analysis_loop.resolver import (
                resolve_analysis_loop_inputs,
                resolve_analysis_loop_run,
            )
            from ..analysis_loop.storage import (
                ComparePacketStore,
                PlanDiffStore,
                ValidationPacketStore,
            )

            plan_key = binding.get("plan_logical_key")
            if type(plan_key) is not str or not plan_key:
                raise ValueError("analysis-loop proposal has no PlanDiff logical key")
            plan_packet = PlanDiffStore(
                self.repository.root,
                create=False,
            ).get_terminal_packet(plan_key)
            if plan_packet is None:
                raise ValueError("analysis-loop PlanDiff terminal packet is unavailable")
            plan = plan_packet.plan_diff
            cluster_variable = plan.product_patch.get("cluster_variable")
            if type(cluster_variable) is not str or not cluster_variable:
                raise ValueError("analysis-loop PlanDiff has no exact cluster variable")
            source_run_id = str(record.target["run_id"])
            child_run_id = (
                (record.execution.get("bindings") or {}).get("child_run_id")
                or record.outputs.get("target_run_id")
            )
            if type(child_run_id) is not str or not child_run_id:
                raise ValueError("analysis-loop operation has no child run")

            resolved_source = resolve_analysis_loop_inputs(
                project_root,
                run_id=source_run_id,
                cluster_variable=cluster_variable,
            )
            source_run = resolve_analysis_loop_run(
                project_root,
                run_id=source_run_id,
                require_result=True,
            )
            child_run = resolve_analysis_loop_run(
                project_root,
                run_id=child_run_id,
                require_result=False,
            )
            if resolved_source.source.run_id != source_run.run_id:
                raise ValueError("resolved source identity does not match operation target")

            context = child_run.run_inputs.get("workbench_context")
            context = context if isinstance(context, dict) else {}
            confirmed_payload = child_run.run_inputs.get("confirmed_payload")
            executed_payload = child_run.run_inputs.get("executed_payload")
            confirmed_payload_hash = sha256_canonical(
                confirmed_payload
                if isinstance(confirmed_payload, dict)
                else {"missing": "confirmed_payload"}
            )
            executed_payload_hash = sha256_canonical(
                executed_payload
                if isinstance(executed_payload, dict)
                else {"missing": "executed_payload"}
            )
            plan_hash = str(context.get("plan_hash") or plan.plan_hash)
            canonical_patch_hash = str(
                context.get("canonical_patch_hash") or plan.canonical_patch_hash
            )
            execution_evidence = {
                "operation_id": record.operation_id,
                "execution_key": record.execution.get("execution_key"),
                "confirmed_payload_hash": confirmed_payload_hash,
                "executed_payload_hash": executed_payload_hash,
                "draft_hash": plan_hash,
                "executed_draft_hash": plan_hash,
                "plan_hash": plan.plan_hash,
                "executed_plan_hash": plan_hash,
                "canonical_patch_hash": plan.canonical_patch_hash,
                "executed_canonical_patch_hash": canonical_patch_hash,
                "effect_status": record.effect_status,
                "projection_status": record.projection_status,
                "child_terminal": child_run.manifest.get("status")
                in {"completed", "failed", "cancelled", "interrupted", "partial", "blocked"},
            }
            observation = build_and_store_analysis_loop_packets(
                source=resolved_source.source,
                source_run=source_run,
                child_run=child_run,
                plan=plan,
                execution_evidence=execution_evidence,
                validation_store=ValidationPacketStore(self.repository.root),
                compare_store=ComparePacketStore(self.repository.root),
            )
            payload = observation.to_dict()
            timings_ms = dict(observation.timings_ms or {})
            timings_ms["terminal_observation_ms"] = round(
                (perf_counter() - observation_started) * 1000,
                3,
            )
            self.events.emit(
                record.agent_session_id,
                "analysis_loop_packets_materialized",
                {"record_id": record.record_id, **payload, "timings_ms": timings_ms},
                command_id=record.command_id,
            )
            return {"analysis_loop": payload}
        except Exception as exc:
            error = {
                "code": getattr(exc, "code", type(exc).__name__),
                "type": type(exc).__name__,
                "message": str(exc),
                "message": str(exc),
            }
            self.events.emit(
                record.agent_session_id,
                "analysis_loop_packet_build_failed",
                {"record_id": record.record_id, "error": error},
                command_id=record.command_id,
            )
            return {
                "analysis_loop": {
                    "status": "failed",
                    "error": error,
                }
            }


    def _ensure_terminal_analysis_loop_observation(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
    ) -> OperationRecord:
        if record.status not in {"completed", "failed"}:
            return record
        if record.operation_id != "model.rerun" or self._analysis_loop_binding(record) is None:
            return record
        current = record.outputs.get("analysis_loop")
        if isinstance(current, dict) and current.get("status") not in {None, "failed"}:
            return record
        observation = self.observe_analysis_loop_terminal(
            record,
            project_root=project_root,
        )
        if not observation:
            return record
        return self.operation_store.append_status(
            record.record_id,
            record.status,
            execution=record.execution,
            outputs={**record.outputs, **observation},
            diff_ref=record.diff_ref,
            verification=record.verification,
            error=record.error,
            effect_status=record.effect_status,
            projection_status=record.projection_status,
        )

