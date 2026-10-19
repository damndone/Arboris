"""service authorization: methods over the existing shared state."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from ...contracts.agent.notebook_option import NotebookOptionRevisionV12, OptionExecution
from ...capability_factory.execution_authorization import ExecutionAuthorizationError, OptionExecutionAuthorization, OptionExecutionAuthorizationStore
from ...custom_capability.canonical import domain_digest
from ...capability_factory.notebook_catalog import CapabilityBindingCatalogError
from ..context_compiler import NotebookPlanningContextV1
from ..trace import TraceWriter
from .errors import OptionLifecycleTransitionInvalid, OptionMaterializationRequired, OptionRevisionStale
from .freshness import assert_executable
from .store import RECORD_EXECUTION, OptionView
from .service_contracts import (_DECISION_TO_LIFECYCLE, _artifact_contract_ref, _consumer_projection_ref, _execution_modes_for)

class ServiceAuthorization:
    def materialize_option(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
    ):
        """Materialize one selected v1.1 Option into a bound Pipeline Draft."""

        from .materialization import NotebookOptionMaterializer

        current = self.store.read_option(notebook_id, option_id).current_revision
        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(
            current
        )
        return NotebookOptionMaterializer(self).materialize(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )


    def authorize_option_execution(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        authorization: OptionExecutionAuthorization,
    ) -> OptionExecutionAuthorization:
        """Bind a user-confirmed option to a durable receipt.

        Standard low-risk options use ``confirm_and_execute``; the explicitly
        experimental ``model.custom`` path uses
        ``experimental_confirm_and_execute`` and remains high-risk.

        This is deliberately a control-plane operation.  It validates the
        current recommendation, binding, risk, and freshness, then persists
        the already-prepared server authorization.  It does not transition
        the Option, materialize a Draft, create a Run intent, or dispatch
        anything.
        """

        if not isinstance(authorization, OptionExecutionAuthorization):
            raise TypeError("authorization must be OptionExecutionAuthorization")

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        if authorization.notebook_id != notebook_id or authorization.option_id != option_id:
            raise OptionRevisionStale(
                "authorization does not identify the current notebook option",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_option_identity",
            )
        if authorization.option_revision != current.option_revision:
            raise OptionRevisionStale(
                "authorization option revision is stale",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_option_revision",
            )
        if not isinstance(current, NotebookOptionRevisionV12):
            raise OptionRevisionStale(
                "confirm_and_execute requires NotebookOptionRevision@1.2",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_contract_version",
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
        expected_mode = offered_modes[1]
        if (
            authorization.execution_mode != expected_mode
            or authorization.risk_level != current.risk_level
        ):
            raise OptionRevisionStale(
                "authorization execution mode or risk does not match the server-approved option",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_risk",
            )
        if view.lifecycle_status not in {"selected", "materialized"}:
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; user confirmation "
                "requires the selected or materialized lifecycle state",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )

        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(current)
        assert_executable(current, context)

        reference = current.capability_resolution_binding_ref
        if self.capability_bindings is None or reference is None:
            raise OptionRevisionStale(
                "authorization requires a current server-owned capability binding",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding_unavailable",
            )
        try:
            capability_id = self.capability_bindings.capability_id_for_reference(
                reference,
                scope_candidates=(
                    ("project", self.get_notebook(notebook_id).project_id),
                    ("run_family", self.get_notebook(notebook_id).run_family_id),
                ),
            )
            if capability_id is None:
                raise CapabilityBindingCatalogError(
                    "authorization binding reference is not registered"
                )
            binding = self.capability_bindings.require(
                capability_id,
                scope_candidates=(
                    ("project", self.get_notebook(notebook_id).project_id),
                    ("run_family", self.get_notebook(notebook_id).run_family_id),
                ),
            )
        except CapabilityBindingCatalogError as error:
            raise OptionRevisionStale(
                "authorization binding is not currently usable",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding_not_current",
            ) from error

        expected = {
            "capability_resolution_binding_ref": binding.content_digest,
            "capability_ref": binding.implementation_ref,
            "bundle_ref": binding.dependency_bundle_ref,
            "evidence_ref": binding.assessment_ref,
            "admission_ref": binding.admission_ref,
            "runtime_policy_ref": binding.runtime_policy_ref,
            "freshness_cursor_ref": binding.validity_cursor_ref,
            "input_graph_fingerprint": current.generation_context_hash,
            "freshness_dependency_fingerprint": current.freshness_dependency_fingerprint,
            "artifact_contract_ref": _artifact_contract_ref(current.artifact_contract),
            "consumer_projection_ref": _consumer_projection_ref(binding),
        }
        mismatches = [
            field
            for field, value in expected.items()
            if getattr(authorization, field) != value
        ]
        if authorization.binding_revision != 1:
            mismatches.append("binding_revision")
        if mismatches:
            raise OptionRevisionStale(
                "authorization binding does not match the current option: "
                + ", ".join(sorted(mismatches)),
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding",
            )
        binding_operation = (
            proposal.changes.get("operation")
            if proposal.operation_id == "model.custom"
            else authorization.operation_id
        )
        if binding_operation not in binding.allowed_operations:
            raise OptionRevisionStale(
                "capability operation is not allowed by the current binding",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_operation",
            )

        try:
            return OptionExecutionAuthorizationStore(self.project_root).issue(
                authorization
            )
        except ExecutionAuthorizationError as error:
            raise OptionRevisionStale(
                "authorization receipt could not be persisted",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_receipt_invalid",
            ) from error


    def _build_server_execution_authorization(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        materialized: Any,
    ) -> OptionExecutionAuthorization:
        """Create the authorization envelope only from persisted server facts."""

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        if not isinstance(current, NotebookOptionRevisionV12):
            raise OptionRevisionStale(
                "server execution authorization requires NotebookOptionRevision@1.2",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_contract_version",
            )
        reference = current.capability_resolution_binding_ref
        if self.capability_bindings is None or reference is None:
            raise OptionRevisionStale(
                "server execution authorization requires a current capability binding",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding_unavailable",
            )
        try:
            notebook = self.get_notebook(notebook_id)
            capability_id = self.capability_bindings.capability_id_for_reference(
                reference,
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
            if capability_id is None:
                raise CapabilityBindingCatalogError(
                    "authorization binding reference is not registered"
                )
            binding = self.capability_bindings.require(
                capability_id,
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
        except CapabilityBindingCatalogError as error:
            raise OptionRevisionStale(
                "server execution authorization binding is not currently usable",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding_not_current",
            ) from error

        persisted_materialization = materialized.materialization
        persisted_draft = materialized.draft
        if (
            persisted_materialization.option_id != option_id
            or persisted_materialization.option_revision != current.option_revision
            or persisted_materialization.capability_resolution_binding_ref != reference
            or persisted_materialization.draft_id != persisted_draft.draft["draft_id"]
            or persisted_materialization.draft_hash != persisted_draft.draft_hash
        ):
            raise OptionRevisionStale(
                "materialization provenance does not match the current capability option",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_materialization_binding",
            )

        proposal = view.current_stored_revision.proposal
        requested_operation = (proposal.changes.get("operation") or "")
        if proposal.operation_id == "model.custom":
            if requested_operation not in binding.allowed_operations:
                raise OptionRevisionStale(
                    "the custom capability operation is no longer admitted",
                    option_id=option_id,
                    option_revision=current.option_revision,
                    reason="authorization_operation_not_admitted",
                )
            # ``model.custom`` is the outer, high-risk Workbench operation.
            # The inner capability operation (for example ``fit``) remains
            # in the canonical Draft and is consumed by the Adapter plan.
            operation_id = proposal.operation_id
        else:
            operation_id = (
                requested_operation
                if requested_operation in binding.allowed_operations
                else binding.allowed_operations[0]
            )
        seed = domain_digest(
            "workbench.notebook.confirm_and_execute/v1",
            {
                "notebook_id": notebook_id,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "materialization_id": persisted_materialization.materialization_id,
                "draft_hash": persisted_materialization.draft_hash,
                "binding_ref": reference,
            },
        ).split(":", 1)[-1]
        authorization_id = f"auth_{seed}"
        idempotency_key = f"confirm-and-execute-{seed}"
        try:
            existing = OptionExecutionAuthorizationStore(self.project_root).read(
                authorization_id
            )
        except KeyError:
            existing = None
        draft_hash = persisted_materialization.draft_hash
        if isinstance(draft_hash, str) and not draft_hash.startswith("sha256:"):
            if len(draft_hash) != 64 or any(
                char not in "0123456789abcdef" for char in draft_hash
            ):
                raise OptionRevisionStale(
                    "the persisted Draft hash is not a lowercase SHA-256 digest",
                    option_id=option_id,
                    option_revision=current.option_revision,
                    reason="authorization_draft_hash_invalid",
                )
            draft_hash = f"sha256:{draft_hash}"
        issued_at = existing.issued_at if existing is not None else datetime.now(timezone.utc)
        expires_at = existing.expires_at if existing is not None else issued_at + timedelta(minutes=5)
        authorization = OptionExecutionAuthorization(
            authorization_id=authorization_id,
            notebook_id=notebook_id,
            option_id=option_id,
            option_revision=current.option_revision,
            binding_revision=1,
            capability_resolution_binding_ref=reference,
            materialization_id=persisted_materialization.materialization_id,
            draft_id=persisted_materialization.draft_id,
            draft_hash=draft_hash,
            run_intent_id=f"intent_{seed}",
            capability_ref=binding.implementation_ref,
            bundle_ref=binding.dependency_bundle_ref,
            evidence_ref=binding.assessment_ref,
            admission_ref=binding.admission_ref,
            runtime_policy_ref=binding.runtime_policy_ref,
            freshness_cursor_ref=binding.validity_cursor_ref,
            input_graph_fingerprint=current.generation_context_hash,
            freshness_dependency_fingerprint=current.freshness_dependency_fingerprint,
            operation_id=operation_id,
            execution_mode=_execution_modes_for(
                current.risk_level, proposal.operation_id
            )[1],
            risk_level=current.risk_level,
            artifact_contract_ref=_artifact_contract_ref(current.artifact_contract),
            consumer_projection_ref=_consumer_projection_ref(binding),
            idempotency_key=idempotency_key,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        if existing is not None:
            if existing.payload_digest != authorization.payload_digest:
                raise OptionRevisionStale(
                    "the deterministic capability authorization is bound to different server facts",
                    option_id=option_id,
                    option_revision=current.option_revision,
                    reason="authorization_payload_mismatch",
                )
            if existing.status == "issued":
                return self.authorize_option_execution(
                    notebook_id,
                    option_id,
                    context=context,
                    authorization=existing,
                )
            if existing.status in {"dispatch_reserved", "running"}:
                return existing
            raise OptionRevisionStale(
                "the deterministic capability authorization has reached a terminal state",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_already_progressed",
            )
        return self.authorize_option_execution(
            notebook_id,
            option_id,
            context=context,
            authorization=authorization,
        )


    def record_decision(
        self,
        notebook_id: str,
        option_id: str,
        *,
        decision: str,
        actor: str,
        edited_fields: Sequence[str] | None = None,
        note_ref: str | None = None,
        trace: TraceWriter | None = None,
    ) -> OptionView:
        """Record what the user did. A decision is an observation, not a label.

        Nothing here carries reward/score/correctness; the Gate 3 schema refuses
        those outright (DEC-TRACE-001), and this method has no parameter that
        could smuggle one in.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        target = _DECISION_TO_LIFECYCLE.get(decision)
        # Browser retries and remounts may replay the same user intent. Keep
        # the lifecycle state machine strict, but make the public observation
        # operation idempotent when the requested state is already current.
        if target is not None and target != view.lifecycle_status:
            self._transition(
                notebook_id,
                view,
                to_status=target,
                actor=actor,
                reason=f"user_{decision}",
                trace=trace,
            )
        if trace is not None:
            payload: dict[str, Any] = {
                "option_id": option_id,
                "option_revision": current.option_revision,
                "decision": decision,
            }
            if edited_fields:
                payload["edited_fields"] = list(edited_fields)
            if note_ref:
                payload["note_ref"] = note_ref
            trace.emit("user.decision.recorded", payload=payload)
        return self.store.read_option(notebook_id, option_id)


    def confirm(
        self,
        notebook_id: str,
        option_id: str,
        *,
        option_revision: int,
        proposal_id: str,
        proposal_revision: int,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
    ) -> OptionExecution:
        """The gate (spec §3.3, §4.2). Fail-closed, and recomputed here.

        `context` must be freshly compiled by the caller at confirm time. A
        read-time verdict is explicitly not accepted as an argument, because
        accepting one would turn the read-time evaluator into a bypassable gate.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision

        if option_revision != current.option_revision:
            raise OptionRevisionStale(
                f"option {option_id} is at revision {current.option_revision}; "
                f"revision {option_revision} can no longer be executed",
                option_id=option_id,
                requested_revision=option_revision,
                current_revision=current.option_revision,
                reason="superseded_revision",
            )
        if (proposal_id, proposal_revision) != (
            current.typed_proposal_id,
            current.typed_proposal_revision,
        ):
            raise OptionRevisionStale(
                f"option {option_id} revision {option_revision} pins proposal "
                f"{current.typed_proposal_id}@{current.typed_proposal_revision}, not "
                f"{proposal_id}@{proposal_revision}",
                option_id=option_id,
                requested_revision=option_revision,
                current_revision=current.option_revision,
                reason="proposal_pin_mismatch",
            )

        if current.materializable:
            raise OptionMaterializationRequired(
                f"option {option_id} revision {option_revision} requires a "
                "persisted OptionMaterialization record before execution",
                option_id=option_id,
                option_revision=option_revision,
                contract_version=current.contract_version,
            )

        # Recompiled upstream facts, compared here and nowhere else.
        assert_executable(current, context)

        if view.lifecycle_status not in {"proposed", "deferred", "selected"}:
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; only a proposed, "
                "deferred or selected option can be confirmed",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )
        if view.lifecycle_status != "selected":
            self._transition(
                notebook_id,
                view,
                to_status="selected",
                actor="user",
                reason="confirm",
                trace=trace,
            )
            view = self.store.read_option(notebook_id, option_id)
        self._transition(
            notebook_id,
            view,
            to_status="executing",
            actor="user",
            reason="confirmed",
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
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_EXECUTION,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "execution": execution.to_dict(),
                "confirmed_context_id": context.context_id,
            },
        )
        if trace is not None:
            trace.emit(
                "option.execution.started",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "proposal_id": execution.proposal_id,
                    "proposal_revision": execution.proposal_revision,
                    "freshness_dependency_fingerprint": (
                        execution.freshness_dependency_fingerprint
                    ),
                },
            )
        return execution

