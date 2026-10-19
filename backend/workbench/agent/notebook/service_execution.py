"""service execution: methods over the existing shared state."""
from __future__ import annotations
from ...contracts.agent.notebook_option import NotebookOptionRevisionV12, OptionExecution
from ...capability_factory.notebook_bridge import NotebookExecutionDispatch
from ..context_compiler import NotebookPlanningContextV1
from ..trace import TraceWriter
from .errors import OptionExecutionGatewayUnavailable, OptionLifecycleTransitionInvalid, OptionRevisionStale
from .freshness import assert_executable
from .store import RECORD_EXECUTION, RECORD_EXECUTION_RESULT
from .service_contracts import (_execution_modes_for)

class ServiceExecution:
    def confirm_and_execute(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
    ) -> NotebookExecutionDispatch:
        """Run one explicit user confirmation through the trusted CF4 seam.

        The gateway is deliberately optional.  A missing gateway is a normal
        deployment state on hosts that cannot prove native containment; it is
        not permission to use the legacy ``/execute`` callback path.
        """

        if self.execution_gateway is None:
            raise OptionExecutionGatewayUnavailable(
                "explicit capability execution is unavailable on this host",
                option_id=option_id,
                reason="trusted_execution_gateway_unavailable",
            )

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        if not isinstance(current, NotebookOptionRevisionV12):
            raise OptionRevisionStale(
                "confirm_and_execute requires NotebookOptionRevision@1.2",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="execution_contract_version",
            )
        proposal = view.current_stored_revision.proposal
        offered_modes = _execution_modes_for(current.risk_level, proposal.operation_id)
        if len(offered_modes) < 2 or offered_modes[1] not in current.execution_modes:
            raise OptionRevisionStale(
                "the current option does not offer its server-approved execution mode",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="execution_mode_not_offered",
            )
        execution_mode = offered_modes[1]
        if current.risk_level not in {"low", "high"}:
            raise OptionRevisionStale(
                "only low-risk standard or high-risk experimental custom options may execute",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="execution_risk",
            )
        if view.lifecycle_status not in {"selected", "materialized"}:
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; explicit execution "
                "requires a selected or materialized option",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )

        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(current)
        assert_executable(current, context)

        # Materialization is the first product-side write, and is performed
        # only after the trusted gateway has been confirmed to exist.
        materialized = self.materialize_option(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )
        authorization = self._build_server_execution_authorization(
            notebook_id,
            option_id,
            context=context,
            materialized=materialized,
        )
        try:
            dispatch = self.execution_gateway.dispatch(
                notebook_id=notebook_id,
                option_id=option_id,
                authorization=authorization,
                materialization=materialized.materialization,
                draft=materialized.draft.draft,
                context=context,
            )
        except Exception as error:
            raise OptionExecutionGatewayUnavailable(
                "the trusted capability execution gateway failed before returning a typed dispatch receipt",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="trusted_execution_gateway_error",
            ) from error
        if not isinstance(dispatch, NotebookExecutionDispatch):
            raise OptionExecutionGatewayUnavailable(
                "the trusted capability execution gateway returned an invalid dispatch receipt",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="trusted_execution_gateway_result_invalid",
            )
        if (
            dispatch.authorization_id != authorization.authorization_id
            or dispatch.run_intent_id != authorization.run_intent_id
        ):
            raise OptionRevisionStale(
                "the capability dispatch receipt is not bound to the server authorization",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="dispatch_receipt_binding",
            )

        if dispatch.status == "running":
            latest = self.store.read_option(notebook_id, option_id)
            self._transition(
                notebook_id,
                latest,
                to_status="executing",
                actor="system",
                reason="capability_dispatch_running",
                trace=trace,
            )
            execution = OptionExecution(
                option_id=option_id,
                option_revision=current.option_revision,
                proposal_id=current.typed_proposal_id,
                proposal_revision=current.typed_proposal_revision,
                freshness_dependency_fingerprint=current.freshness_dependency_fingerprint,
                generation_context_id=current.generation_context_id,
                run_id=dispatch.run_id,
            )
            self.store.append_option_record(
                notebook_id,
                option_id,
                {
                    "record_type": RECORD_EXECUTION,
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "execution": execution.to_dict(),
                    "authorization_id": authorization.authorization_id,
                    "dispatch_receipt_ref": dispatch.receipt_ref,
                },
            )
        elif dispatch.status in {"completed", "failed"}:
            self._record_capability_dispatch_completion(
                notebook_id,
                option_id,
                current=current,
                dispatch=dispatch,
                trace=trace,
            )
        return dispatch


    def _record_capability_dispatch_completion(
        self,
        notebook_id: str,
        option_id: str,
        *,
        current: NotebookOptionRevisionV12,
        dispatch: NotebookExecutionDispatch,
        trace: TraceWriter | None,
    ) -> None:
        """Project a trusted CF4 terminal receipt into the Notebook log.

        This method accepts only refs already produced by the trusted gateway;
        it has no parameter for client artifacts, raw adapter output, or an
        execution status supplied by Agent.  CF4 has already consumed/failed
        the exact attempt before this projection is written.
        """

        if dispatch.status not in {"completed", "failed"}:
            raise OptionRevisionStale(
                "capability completion requires a terminal dispatch receipt",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="capability_dispatch_not_terminal",
            )
        required = (
            dispatch.run_id,
            dispatch.attempt_id,
            dispatch.receipt_ref,
            dispatch.completion_ref,
            dispatch.artifact_validation_ref,
            dispatch.object_graph_ref,
        )
        if any(value is None for value in required):
            raise OptionRevisionStale(
                "capability completion receipt is missing server-owned refs",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="capability_dispatch_completion_refs",
            )

        view = self.store.read_option(notebook_id, option_id)
        if view.lifecycle_status == "materialized":
            self._transition(
                notebook_id,
                view,
                to_status="executing",
                actor="system",
                reason="capability_dispatch_terminal",
                trace=trace,
            )
            view = self.store.read_option(notebook_id, option_id)
        if view.lifecycle_status != "executing":
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; terminal capability "
                "projection requires an executing option",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )

        succeeded = dispatch.status == "completed"
        self._transition(
            notebook_id,
            view,
            to_status="executed" if succeeded else "materialized",
            actor="system",
            reason="capability_cf4_reconciled",
            trace=trace,
        )
        if not succeeded:
            self._transition(
                notebook_id,
                self.store.read_option(notebook_id, option_id),
                to_status="selected",
                actor="system",
                reason="capability_cf4_retry",
                trace=trace,
            )
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_EXECUTION_RESULT,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "run_id": dispatch.run_id,
                "execution_status": "succeeded" if succeeded else "failed",
                "committed": succeeded,
                "capability_execution": {
                    "dispatch_status": dispatch.status,
                    "attempt_id": dispatch.attempt_id,
                    "receipt_ref": dispatch.receipt_ref,
                    "completion_ref": dispatch.completion_ref,
                    "artifact_validation_ref": dispatch.artifact_validation_ref,
                    "object_graph_ref": dispatch.object_graph_ref,
                    "assessment_ref": dispatch.assessment_ref,
                    "output_bundle_ref": dispatch.output_bundle_ref,
                    "attestation_ref": dispatch.attestation_ref,
                },
            },
        )
        if succeeded:
            self.set_active_head(
                notebook_id,
                dispatch.run_id,
                reason="capability_cf4_reconciled",
                trace=trace,
            )

