"""service workflow: methods over the existing shared state."""
from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from ...contracts.agent.notebook_option import NotebookOptionRevisionV12, OptionExecution
from ...canonical import sha256_canonical
from ...lineage.run_family import assert_run_in_family
from ...data_operations import resolve_data_column_cast_context
from ..context_compiler import NotebookPlanningContextV1
from ...services.notebook_source_materialization import materialize_notebook_upload_source
from ..trace import TraceWriter
from ..workflow import compile_workflow, execute_workflow
from .execution_results import ExecutionOutcome, artifact_validation_scope
from .artifact_contract import COMMITTABLE_VALIDATION_STATUSES, validate_produced_artifacts
from .errors import OptionExecutionReceiptRequired, OptionLifecycleTransitionInvalid, OptionMaterializationRequired, OptionRevisionStale, OptionValidationFailed
from .freshness import assert_executable
from .store import RECORD_EXECUTION, RECORD_EXECUTION_RESULT
from .workflow_artifacts import p7_capability_ids_from_steps, persist_workflow_result_manifest, workflow_result_artifact_id
from .operation_adapter import execute_workflow_option

class ServiceWorkflow:
    def confirm_and_execute_workflow(
        self,
        notebook_id: str,
        option_id: str,
        *,
        option_revision: int,
        proposal_id: str,
        proposal_revision: int,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
        operation_record=None,
    ) -> dict[str, Any]:
        """Run one confirmed ``operation.multi_step`` with server-owned facts.

        The browser contributes only the immutable Option/Proposal revision
        pins.  Source identity is recomputed from the Notebook projection,
        workflow compilation uses the published server vocabulary, and result
        artifact records are read from the resulting Runs.  In particular, this
        never accepts a client-reported status, run id, or artifact list.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        proposal = view.current_stored_revision.proposal
        if (option_revision, proposal_id, proposal_revision) != (
            current.option_revision,
            current.typed_proposal_id,
            current.typed_proposal_revision,
        ):
            raise OptionRevisionStale(
                "workflow confirmation does not match the current option revision",
                option_id=option_id,
                requested_revision=option_revision,
                current_revision=current.option_revision,
                reason="proposal_pin_mismatch",
            )
        if proposal.operation_id != "operation.multi_step":
            raise OptionValidationFailed(
                "the selected option is not a composed workflow",
                option_id=option_id,
                option_revision=current.option_revision,
            )
        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(current)
        assert_executable(current, context)

        notebook = self.get_notebook(notebook_id)
        expected_pin = self._workflow_source_pin(notebook, context)
        if proposal.target != expected_pin["target"] or proposal.preconditions != expected_pin[
            "preconditions"
        ]:
            raise OptionRevisionStale(
                "workflow source pin no longer matches the current Notebook source",
                option_id=option_id,
                requested_revision=option_revision,
                current_revision=current.option_revision,
                reason="workflow_source_changed",
            )
        if view.lifecycle_status not in {"proposed", "deferred", "selected"}:
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; it cannot start a workflow",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )
        projection_source = notebook.projection_source
        if (
            projection_source is not None
            and projection_source.kind == "dataset"
            and projection_source.workflow_source is not None
            and projection_source.workflow_source.source_kind == "dataset_upload"
        ):
            materialize_notebook_upload_source(
                self.project_root,
                source=projection_source,
                run_family_id=notebook.run_family_id,
            )
        self._assert_dataset_workflow_source_current(notebook)
        if view.lifecycle_status != "selected":
            self._transition(
                notebook_id,
                view,
                to_status="selected",
                actor="user",
                reason="workflow_confirm",
                trace=trace,
            )
            view = self.store.read_option(notebook_id, option_id)
        if current.materializable:
            # V1.1 reserves direct selected -> executing for a persisted
            # Pipeline Draft.  A typed workflow has no single Draft and may
            # produce several sibling Runs, so retain the explicit intermediate
            # state without fabricating a Draft materialization record.
            self._transition(
                notebook_id,
                view,
                to_status="materialized",
                actor="system",
                reason="workflow_execution_prepared",
                trace=trace,
                server_workflow_prepared=True,
            )
            view = self.store.read_option(notebook_id, option_id)
        self._transition(
            notebook_id,
            view,
            to_status="executing",
            actor="user",
            reason="workflow_confirmed",
            trace=trace,
        )
        execution = OptionExecution(
            option_id=option_id,
            option_revision=current.option_revision,
            proposal_id=current.typed_proposal_id,
            proposal_revision=current.typed_proposal_revision,
            freshness_dependency_fingerprint=current.freshness_dependency_fingerprint,
            generation_context_id=current.generation_context_id,
            run_id=None,
        )

        workflow_id = "workflow_" + sha256_canonical(
            {
                "notebook_id": notebook_id,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "proposal_hash": proposal.canonical_hash(),
                "target": proposal.target,
            }
        )[:24]
        if trace is not None:
            trace.emit(
                "option.execution.started",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "proposal_id": current.typed_proposal_id,
                    "proposal_revision": current.typed_proposal_revision,
                },
            )

        receipt: dict[str, Any] | None = None
        operation = None
        try:
            source_context = resolve_data_column_cast_context(
                self.project_root,
                source_run_id=str(proposal.target["run_id"]),
                source_node_id=str(proposal.target["node_ref"]),
            )
            source_columns = [
                str(item["name"])
                for item in source_context.get("columns", [])
                if isinstance(item, Mapping) and isinstance(item.get("name"), str)
            ]
            workflow = compile_workflow(
                workflow_id=workflow_id,
                target=proposal.target,
                preconditions=proposal.preconditions,
                steps=proposal.changes.get("steps"),
                available_columns=source_columns,
            )
            workflow = replace(
                workflow,
                bindings={
                    "notebook_provenance": {
                        "notebook_id": notebook.notebook_id,
                        "run_family_id": notebook.run_family_id,
                        "option_id": option_id,
                        "option_revision": str(current.option_revision),
                    }
                },
            )
            self.store.append_option_record(
                notebook_id,
                option_id,
                {
                    "record_type": RECORD_EXECUTION,
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "execution": execution.to_dict(),
                    "workflow_id": workflow.workflow_id,
                    "workflow_plan_fingerprint": workflow.plan_fingerprint,
                },
            )
            executed = execute_workflow_option(self, notebook=notebook, option_id=option_id,
                revision=current, proposal=proposal, workflow=workflow, operation_record=operation_record)
            operation, state = executed.operation, executed.state
            receipt = self._workflow_execution_receipt(workflow, state)
            produced = self._workflow_produced_artifacts(workflow, state)
            if (
                state.status == "completed"
                and p7_capability_ids_from_steps(workflow.steps)
            ):
                produced.append(
                    persist_workflow_result_manifest(
                        self.project_root,
                        artifact_id=workflow_result_artifact_id(
                            notebook_id=notebook_id,
                            option_id=option_id,
                            proposal_hash=proposal.canonical_hash(),
                        ),
                        workflow=workflow,
                        state=state,
                        produced_artifacts=produced,
                    )
                )
            projected = self._contract_artifact_projection(
                current.artifact_contract,
                produced,
            )
            succeeded = state.status == "completed"
            outcome = self.complete_execution(
                notebook_id,
                option_id,
                execution_status="succeeded" if succeeded else "failed",
                produced_artifacts=projected,
                error_code=None if succeeded else "WORKFLOW_EXECUTION_FAILED",
                trace=trace,
                server_workflow_execution=True,
                workflow_execution=receipt,
                ambient_artifacts=produced,
                artifact_validation_scope_mode="server_owned_workflow_projection",
            )
        except Exception:
            # Compilation and runtime are both server-owned.  Preserve the
            # failure as an execution result, but never leak arbitrary raw
            # exception text into the UI or advance a Notebook head.
            outcome = self.complete_execution(
                notebook_id,
                option_id,
                execution_status="failed",
                produced_artifacts=(),
                error_code="WORKFLOW_EXECUTION_FAILED",
                trace=trace,
                server_workflow_execution=True,
            )
            if trace is not None:
                trace.emit(
                    "operation.error",
                    payload={
                        "code": "WORKFLOW_EXECUTION_FAILED",
                        "fatal": False,
                        "option_id": option_id,
                        "option_revision": current.option_revision,
                    },
                )
        result = {
            "execution": execution.to_dict(),
            "outcome": outcome.to_dict(),
        }
        if receipt is not None:
            result["workflow_execution"] = receipt
        if operation is not None:
            result["operation"] = operation.to_dict()
        return result


    def complete_execution(
        self,
        notebook_id: str,
        option_id: str,
        *,
        execution_status: str,
        run_id: str | None = None,
        produced_artifacts: Iterable[Mapping[str, Any]] | None = None,
        error_code: str | None = None,
        trace: TraceWriter | None = None,
        server_workflow_execution: bool = False,
        workflow_execution: Mapping[str, Any] | None = None,
        artifact_validation_scope_mode: str | None = None,
        ambient_artifacts: Sequence[Mapping[str, Any]] | None = None,
    ) -> ExecutionOutcome:
        """Close the loop: validate the contract, then decide about the head.

        spec §5.3 commit gate — the head advances only when execution succeeded
        *and* the artifact contract passed (possibly with warnings). A failed
        contract keeps its artifacts for debugging and returns the option to
        `selected`; it does not become a result.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(current)
        if (
            isinstance(current, NotebookOptionRevisionV12)
            and current.capability_resolution_binding_ref is not None
        ):
            raise OptionExecutionReceiptRequired(
                "a bound capability execution must be completed from a server-owned CF4 receipt",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="capability_execution_receipt_required",
            )
        if current.materializable and not server_workflow_execution:
            materialization = self.store.read_materialization(
                notebook_id, option_id, current.option_revision
            )
            if materialization is None:
                raise OptionMaterializationRequired(
                    f"option {option_id} revision {current.option_revision} requires "
                    "a persisted OptionMaterialization record before completion",
                    option_id=option_id,
                    option_revision=current.option_revision,
                    contract_version=current.contract_version,
                )
            if view.lifecycle_status == "materialized":
                # A materialized Draft has not gone through the legacy
                # Notebook `confirm` endpoint.  Its real execution begins in
                # Draft Graph, so the first callback from that run is the
                # authoritative start of the materialized option's execution.
                # Record the transition before validating artifacts; a failed
                # run must still leave an append-only execution attempt.
                self._transition(
                    notebook_id,
                    view,
                    to_status="executing",
                    actor="system",
                    reason="draft_execution_started",
                    trace=trace,
                )
                if trace is not None:
                    trace.emit(
                        "option.execution.started",
                        payload={
                            "option_id": option_id,
                            "option_revision": current.option_revision,
                            "proposal_id": current.typed_proposal_id,
                            "proposal_revision": current.typed_proposal_revision,
                            "freshness_dependency_fingerprint": (
                                current.freshness_dependency_fingerprint
                            ),
                        },
                    )
                view = self.store.read_option(notebook_id, option_id)
            if view.lifecycle_status != "executing":
                raise OptionLifecycleTransitionInvalid(
                    f"option {option_id} is {view.lifecycle_status}; only an executing "
                    "materialized option can complete",
                    option_id=option_id,
                    lifecycle_status=view.lifecycle_status,
                )
        ambient_records = (
            [dict(record) for record in ambient_artifacts]
            if ambient_artifacts is not None
            else self._read_run_artifacts(run_id)
        )
        if produced_artifacts is None:
            artifacts = self._contract_artifact_projection(
                current.artifact_contract, ambient_records
            )
            artifact_validation_scope = self._artifact_validation_scope(
                "contract_projection", ambient_records
            )
        else:
            artifacts = [dict(record) for record in produced_artifacts]
            artifact_validation_scope = self._artifact_validation_scope(
                artifact_validation_scope_mode
                or (
                    "server_owned_artifact_manifest"
                    if server_workflow_execution
                    else "explicit_produced_artifacts"
                ),
                ambient_records,
            )
        validation = validate_produced_artifacts(current.artifact_contract, artifacts)

        committable = (
            execution_status == "succeeded"
            and validation["validation_status"] in COMMITTABLE_VALIDATION_STATUSES
        )
        if trace is not None:
            payload: dict[str, Any] = {
                "option_id": option_id,
                "option_revision": current.option_revision,
                "execution_status": execution_status,
            }
            if run_id:
                payload["run_id"] = run_id
            if error_code:
                payload["error_code"] = error_code
            trace.emit("option.execution.completed", payload=payload)
            trace.emit(
                "artifact_contract.validation.completed",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "validation_status": validation["validation_status"],
                    "missing_required": [
                        issue["artifact_id"]
                        for issue in validation["issues"]
                        if issue["code"] == "ARTIFACT_REQUIRED_MISSING"
                    ],
                    "checked_dimensions": list(validation["checked_dimensions"]),
                    "artifact_validation_scope": artifact_validation_scope,
                },
            )
            if not committable:
                trace.emit(
                    "operation.error",
                    payload={
                        "code": error_code or "ARTIFACT_CONTRACT_UNSATISFIED",
                        "fatal": False,
                        "option_id": option_id,
                        "option_revision": current.option_revision,
                        "detail": (
                            "execution_status="
                            f"{execution_status}, validation_status="
                            f"{validation['validation_status']}"
                        ),
                    },
                )

        if current.materializable:
            self._transition(
                notebook_id,
                view,
                to_status="executed" if committable else "materialized",
                actor="system",
                reason="artifact_contract_" + validation["validation_status"],
                trace=trace,
                server_workflow_prepared=server_workflow_execution,
            )
        else:
            self._transition(
                notebook_id,
                view,
                to_status="executed" if committable else "selected",
                actor="system",
                reason="artifact_contract_" + validation["validation_status"],
                trace=trace,
            )
        if not committable and current.materializable:
            self._transition(
                notebook_id,
                self.store.read_option(notebook_id, option_id),
                to_status="selected",
                actor="system",
                reason="artifact_contract_retry",
                trace=trace,
            )
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_EXECUTION_RESULT,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "run_id": run_id,
                "execution_status": execution_status,
                "artifact_validation": validation,
                "artifact_validation_scope": artifact_validation_scope,
                "committed": committable,
                **(
                    {"workflow_execution": dict(workflow_execution)}
                    if server_workflow_execution and workflow_execution is not None
                    else {}
                ),
            },
        )

        advanced = False
        if committable and run_id:
            self.set_active_head(
                notebook_id, run_id, reason="option_executed", trace=trace
            )
            advanced = True
        elif run_id:
            # Failed attempts are recorded on their own field; the head does not
            # move, and neither does "what the user was looking at" silently
            # become a broken run (spec §9.1 criterion 4).
            self.store.append_notebook_state(
                notebook_id,
                {"last_attempt_run_id": run_id, "reason": "execution_not_committable"},
            )

        return ExecutionOutcome(
            option_id=option_id,
            option_revision=current.option_revision,
            run_id=run_id,
            execution_status=execution_status,
            artifact_validation=validation,
            artifact_validation_scope=artifact_validation_scope,
            active_head_advanced=advanced,
            lifecycle_status=self.store.read_option(notebook_id, option_id).lifecycle_status,
        )


    def complete_execution_from_server_run(
        self,
        notebook_id: str,
        option_id: str,
        *,
        run_id: str,
        trace: TraceWriter | None = None,
    ) -> ExecutionOutcome:
        """Complete from a run manifest and index owned by Workbench.

        ``run_id`` is a reference supplied by the client; status and artifact
        records are reconstructed from the bound run. A caller cannot turn a
        plausible artifact id/type/count tuple into a committed Notebook
        result by posting it to the completion endpoint.
        """

        if not isinstance(run_id, str) or not run_id:
            raise OptionExecutionReceiptRequired(
                "server-owned completion requires a non-empty run_id"
            )
        if Path(run_id).name != run_id or run_id in {".", ".."}:
            raise OptionExecutionReceiptRequired(
                "server-owned completion run_id is not path-safe",
                run_id=run_id,
            )
        notebook = self.get_notebook(notebook_id)
        try:
            assert_run_in_family(
                self.project_root,
                run_family_id=notebook.run_family_id,
                run_id=run_id,
            )
        except (OSError, ValueError, KeyError) as exc:
            raise OptionExecutionReceiptRequired(
                "server-owned completion run is not bound to this notebook family",
                run_id=run_id,
            ) from exc
        run_root = (self.project_root / "runs" / run_id).resolve()
        runs_root = (self.project_root / "runs").resolve()
        try:
            run_root.relative_to(runs_root)
        except ValueError as exc:
            raise OptionExecutionReceiptRequired(
                "server-owned completion run is outside the project runs root",
                run_id=run_id,
            ) from exc
        manifest_path = run_root / "run_manifest.json"
        if not manifest_path.is_file():
            raise OptionExecutionReceiptRequired(
                "server-owned completion run has no run manifest",
                run_id=run_id,
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OptionExecutionReceiptRequired(
                "server-owned completion run manifest is unreadable",
                run_id=run_id,
            ) from exc
        if not isinstance(manifest, Mapping):
            raise OptionExecutionReceiptRequired(
                "server-owned completion run manifest must be an object",
                run_id=run_id,
            )
        if manifest.get("run_id") not in (None, run_id):
            raise OptionExecutionReceiptRequired(
                "server-owned completion run manifest identity does not match run_id",
                run_id=run_id,
            )
        terminal_status = manifest.get("status")
        if terminal_status not in {"completed", "failed"}:
            raise OptionExecutionReceiptRequired(
                "server-owned completion requires a terminal run status",
                run_id=run_id,
                status=terminal_status,
            )
        ambient_records = self._read_run_artifacts(run_id, required=True)
        current = self.store.read_option(notebook_id, option_id).current_revision
        projected_records = self._contract_artifact_projection(
            current.artifact_contract,
            ambient_records,
        )
        return self.complete_execution(
            notebook_id,
            option_id,
            execution_status=("succeeded" if terminal_status == "completed" else "failed"),
            run_id=run_id,
            produced_artifacts=projected_records,
            error_code=(None if terminal_status == "completed" else "RUN_EXECUTION_FAILED"),
            trace=trace,
            server_workflow_execution=True,
            artifact_validation_scope_mode="server_owned_contract_projection",
        )

