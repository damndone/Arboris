from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from workbench.capability_factory.control import (
    ControlCursorExpectation,
    ControlSubjectCursor,
    ExecutionControlStore,
)
from workbench.capability_factory.custom_dispatcher import CustomCapabilityDispatcher
from workbench.capability_factory.dispatch import PreparedRunIntent
from workbench.capability_factory.execution_authorization import (
    OptionExecutionAuthorization,
    OptionExecutionAuthorizationStore,
)
from workbench.capability_factory.execution_receipt import (
    ArtifactContractValidationV11,
    CapabilityDispatchCoordinator,
    ExecutionReceiptError,
    TerminalSideEffectReconciliation,
    validate_artifact_contract_v11,
)
from workbench.contracts.agent.notebook_option import ArtifactContract, ExpectedArtifact
from workbench.capability_factory.supervisor import AttemptQuiescenceProof, DurableSupervisorStore

from test_capability_custom_dispatcher import _intent_and_records


def _authorization(intent: PreparedRunIntent, binding, implementation, *, now: datetime) -> OptionExecutionAuthorization:
    return OptionExecutionAuthorization(
        authorization_id="authorization.coordinator",
        notebook_id="notebook.coordinator",
        option_id="option.coordinator",
        option_revision=1,
        binding_revision=intent.binding_revision,
        capability_resolution_binding_ref=intent.binding_ref,
        materialization_id="materialization.coordinator",
        draft_id=intent.draft_id,
        draft_hash=intent.draft_hash,
        run_intent_id=intent.intent_id,
        capability_ref=implementation.content_digest,
        bundle_ref=intent.bundle_ref,
        evidence_ref=intent.evidence_ref,
        admission_ref=intent.admission_ref,
        runtime_policy_ref=intent.runtime_policy_ref,
        freshness_cursor_ref="9" * 64,
        input_graph_fingerprint=intent.input_graph_fingerprint,
        freshness_dependency_fingerprint=intent.input_graph_fingerprint,
        operation_id=intent.operation_id,
        execution_mode="confirm_and_execute",
        risk_level="low",
        artifact_contract_ref="a" * 64,
        consumer_projection_ref="b" * 64,
        idempotency_key="authorization-coordinator-idem",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
    )


def _expectations(intent: PreparedRunIntent, authorization_id: str) -> tuple[ControlCursorExpectation, ...]:
    return (
        ControlCursorExpectation("authorization", authorization_id, 1, "claimed"),
        ControlCursorExpectation("binding", intent.binding_ref, intent.binding_revision, "valid"),
        ControlCursorExpectation("host_containment", intent.host_containment_ref, intent.host_validity_revision, "valid"),
        ControlCursorExpectation("bundle", intent.bundle_ref, intent.bundle_validity_revision, "valid"),
        ControlCursorExpectation("evidence", intent.evidence_ref, intent.evidence_validity_revision, "valid"),
        ControlCursorExpectation("admission", intent.admission_ref, intent.admission_validity_revision, "valid"),
    )


def _store_subjects(store: ExecutionControlStore, intent: PreparedRunIntent, authorization_id: str, now: datetime) -> None:
    subjects = (
        ("authorization", authorization_id, 1, "claimed"),
        ("binding", intent.binding_ref, intent.binding_revision, "valid"),
        ("host_containment", intent.host_containment_ref, intent.host_validity_revision, "valid"),
        ("bundle", intent.bundle_ref, intent.bundle_validity_revision, "valid"),
        ("evidence", intent.evidence_ref, intent.evidence_validity_revision, "valid"),
        ("admission", intent.admission_ref, intent.admission_validity_revision, "valid"),
    )
    for kind, ref, revision, status in subjects:
        store.publish_subject(
            ControlSubjectCursor(
                subject_kind=kind,
                subject_ref=ref,
                validity_revision=revision,
                status=status,
                effective_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(minutes=5),
                authority="server.control",
                reason="fixture",
                source_record_ref=f"source.{kind}",
            )
        )


def _termination_proof(attempt, authorization_id: str) -> AttemptQuiescenceProof:
    return AttemptQuiescenceProof(
        proof_id=f"proof.{attempt.attempt_id}",
        attempt_id=attempt.attempt_id,
        reservation_id=attempt.reservation_id,
        authorization_id=authorization_id,
        lease_epoch=attempt.lease_epoch,
        proof_kind="terminated_clean",
        process_handle_ref=attempt.process_handle_ref,
        process_tree_digest="1" * 64,
        resource_cleanup_digest="2" * 64,
        output_cleanup_digest="3" * 64,
        issued_by="trusted.supervisor",
        issuer_role="trusted_supervisor",
        issued_at=datetime(2026, 7, 27, 9, 1, tzinfo=timezone.utc),
        authority_attestation_digest="4" * 64,
    )


def _terminal_reconciliation(
    attempt,
    authorization_id: str,
    validation: ArtifactContractValidationV11,
    object_graph_ref: str,
) -> TerminalSideEffectReconciliation:
    return TerminalSideEffectReconciliation(
        attempt_ref=attempt.content_digest,
        authorization_id=authorization_id,
        lease_epoch=attempt.lease_epoch,
        artifact_aggregate_ref=validation.aggregate_ref,
        object_graph_ref=object_graph_ref,
        trace_event_ref="5" * 64,
        artifact_reconciled=True,
        graph_reconciled=True,
        trace_reconciled=True,
    )


def _fixture(tmp_path, *, trace_sink=None):
    intent, implementation, adapter, binding = _intent_and_records()
    now = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    authorization = _authorization(intent, binding, implementation, now=now)
    auth_store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda: now)
    auth_store.issue(authorization)
    control_store = ExecutionControlStore(clock=lambda: now)
    _store_subjects(control_store, intent, authorization.authorization_id, now)
    supervisor = DurableSupervisorStore(tmp_path)
    plan = CustomCapabilityDispatcher.prepare(
        intent=intent,
        binding=binding,
        adapter=adapter,
        implementation=implementation,
        operation_id="fit",
        requested_consumers=("notebook_option_planner", "report_projection"),
    )
    coordinator = CapabilityDispatchCoordinator(
        authorization_store=auth_store,
        control_store=control_store,
        supervisor_store=supervisor,
        trace_sink=trace_sink,
    )
    return intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now


def test_coordinator_claims_reserves_and_replays_one_attempt(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now = _fixture(tmp_path)
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.coordinator",
        lease_seconds=60,
        attempt_id="attempt.coordinator",
        lease_epoch=1,
        executor_idempotency_key="executor.coordinator",
        reservation_id="reservation.coordinator",
        reservation_idempotency_key="reservation-coordinator-idem",
        now=now,
    )

    assert receipt.status == "dispatch_reserved"
    assert len(control_store.records()) == 1
    assert auth_store.read(authorization.authorization_id).status == "dispatch_reserved"
    assert supervisor.read(receipt.attempt_id).status == "reserved"

    replay = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.coordinator",
        lease_seconds=60,
        attempt_id="attempt.other",
        lease_epoch=1,
        executor_idempotency_key="executor.other",
        reservation_id="reservation.other",
        reservation_idempotency_key="reservation-other-idem",
        now=now,
    )
    assert replay == receipt
    assert len(control_store.records()) == 1


def test_coordinator_rejects_stale_fence_without_leaving_a_reservation(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now = _fixture(tmp_path)
    control_store.publish_subject(
        ControlSubjectCursor(
            subject_kind="binding",
            subject_ref=intent.binding_ref,
            validity_revision=intent.binding_revision + 1,
            status="revoked",
            effective_at=now,
            expires_at=None,
            authority="server.control",
            reason="revoked",
            source_record_ref="source.binding.revoked",
        ),
        expected_validity_revision=intent.binding_revision,
    )
    with pytest.raises(ExecutionReceiptError, match="reservation rejected"):
        coordinator.reserve(
            authorization=authorization,
            intent=intent,
            plan=plan,
            expectations=_expectations(intent, authorization.authorization_id),
            owner_id="supervisor.coordinator",
            lease_seconds=60,
            attempt_id="attempt.revoked",
            lease_epoch=1,
            executor_idempotency_key="executor.revoked",
            reservation_id="reservation.revoked",
            reservation_idempotency_key="reservation-revoked-idem",
            now=now,
        )
    assert control_store.records() == ()
    assert auth_store.read(authorization.authorization_id).status == "invalidated"


def test_executor_acknowledgement_requires_a_trusted_handle_and_fences_attempt(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now = _fixture(tmp_path)
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.coordinator",
        lease_seconds=60,
        attempt_id="attempt.running",
        lease_epoch=1,
        executor_idempotency_key="executor.running",
        reservation_id="reservation.running",
        reservation_idempotency_key="reservation-running-idem",
        now=now,
    )
    running = coordinator.acknowledge_executor(
        receipt,
        owner_id="supervisor.coordinator",
        process_handle_ref="trusted-handle.running",
    )
    assert running.status == "running"
    assert supervisor.read(running.attempt_id).process_handle_ref == "trusted-handle.running"
    assert auth_store.read(authorization.authorization_id).status == "running"


def test_executor_acknowledgement_rejects_a_receipt_with_mismatched_intent_digest(tmp_path) -> None:
    intent, authorization, plan, coordinator, _control_store, _auth_store, _supervisor, now = _fixture(tmp_path)
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.coordinator",
        lease_seconds=60,
        attempt_id="attempt.mismatched-receipt",
        lease_epoch=1,
        executor_idempotency_key="executor.mismatched-receipt",
        reservation_id="reservation.mismatched-receipt",
        reservation_idempotency_key="reservation-mismatched-receipt-idem",
        now=now,
    )

    with pytest.raises(ExecutionReceiptError, match="intent"):
        coordinator.acknowledge_executor(
            replace(receipt, intent_digest="0" * 64),
            owner_id="supervisor.coordinator",
            process_handle_ref="trusted-handle.mismatched-receipt",
        )

    assert coordinator.supervisor_store.read(receipt.attempt_id).status == "reserved"


def test_reconciliation_consumes_only_after_the_v11_artifact_gate(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now = _fixture(tmp_path)
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.coordinator",
        lease_seconds=60,
        attempt_id="attempt.reconcile",
        lease_epoch=1,
        executor_idempotency_key="executor.reconcile",
        reservation_id="reservation.reconcile",
        reservation_idempotency_key="reservation-reconcile-idem",
        now=now,
    )
    running = coordinator.acknowledge_executor(
        receipt,
        owner_id="supervisor.coordinator",
        process_handle_ref="trusted-handle.reconcile",
    )
    attempt_ref = supervisor.read(running.attempt_id).content_digest
    artifact = {
        "artifact_id": "custom.parameters",
        "artifact_type": "custom_json",
        "step": "fit",
        "lineage_ref": "c" * 64,
        "consumer_projection_ref": authorization.consumer_projection_ref,
        "run_attempt_ref": attempt_ref,
        "option_revision_ref": "a" * 64,
        "artifact_ref": "e" * 64,
        "facet": "parameters",
    }
    validation = validate_artifact_contract_v11(
        ArtifactContract(
            expected=(ExpectedArtifact("custom.parameters", "custom_json", step="fit"),)
        ),
        [artifact],
        option_revision_ref="a" * 64,
        run_attempt_ref=attempt_ref,
        consumer_projection_ref=authorization.consumer_projection_ref,
        lineage_ref="c" * 64,
        allowed_facets=("parameters",),
    )

    termination_proof = _termination_proof(
        supervisor.read(running.attempt_id), authorization.authorization_id
    )
    terminal_reconciliation = _terminal_reconciliation(
        supervisor.read(running.attempt_id),
        authorization.authorization_id,
        validation,
        "f" * 64,
    )
    consumed = coordinator.reconcile(
        running,
        owner_id="supervisor.coordinator",
        artifact_validation=validation,
        object_graph_ref="f" * 64,
        termination_proof=termination_proof,
        terminal_reconciliation=terminal_reconciliation,
    )

    assert isinstance(validation, ArtifactContractValidationV11)
    assert validation.validation_status == "passed"
    assert consumed.status == "consumed"
    assert auth_store.read(authorization.authorization_id).status == "consumed"
    assert supervisor.read(running.attempt_id).status == "consumed"
    assert supervisor.read_termination_proof(termination_proof.proof_id) == termination_proof
    assert TerminalSideEffectReconciliation.from_dict(
        terminal_reconciliation.to_dict()
    ) == terminal_reconciliation


def test_reconciliation_requires_termination_proof_before_marking_failure(tmp_path) -> None:
    intent, authorization, plan, coordinator, _control_store, _auth_store, supervisor, now = _fixture(tmp_path)
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.coordinator",
        lease_seconds=60,
        attempt_id="attempt.failed-proof",
        lease_epoch=1,
        executor_idempotency_key="executor.failed-proof",
        reservation_id="reservation.failed-proof",
        reservation_idempotency_key="reservation-failed-proof-idem",
        now=now,
    )
    running = coordinator.acknowledge_executor(
        receipt,
        owner_id="supervisor.coordinator",
        process_handle_ref="trusted-handle.failed-proof",
    )
    attempt_ref = supervisor.read(running.attempt_id).content_digest
    failed_validation = validate_artifact_contract_v11(
        ArtifactContract(
            expected=(ExpectedArtifact("custom.parameters", "custom_json", step="fit"),)
        ),
        [
            {
                "artifact_id": "custom.parameters",
                "artifact_type": "custom_json",
                "step": "fit",
                "lineage_ref": "0" * 64,
                "consumer_projection_ref": authorization.consumer_projection_ref,
                "run_attempt_ref": attempt_ref,
                "option_revision_ref": "a" * 64,
                "artifact_ref": "e" * 64,
                "facet": "parameters",
            }
        ],
        option_revision_ref="a" * 64,
        run_attempt_ref=attempt_ref,
        consumer_projection_ref=authorization.consumer_projection_ref,
        lineage_ref="c" * 64,
        allowed_facets=("parameters",),
    )
    assert failed_validation.validation_status == "failed"

    with pytest.raises(ExecutionReceiptError, match="termination proof"):
        coordinator.reconcile(
            running,
            owner_id="supervisor.coordinator",
            artifact_validation=failed_validation,
            object_graph_ref="f" * 64,
        )

    termination_proof = _termination_proof(
        supervisor.read(running.attempt_id), authorization.authorization_id
    )
    terminal_reconciliation = _terminal_reconciliation(
        supervisor.read(running.attempt_id),
        authorization.authorization_id,
        failed_validation,
        "f" * 64,
    )
    failed = coordinator.reconcile(
        running,
        owner_id="supervisor.coordinator",
        artifact_validation=failed_validation,
        object_graph_ref="f" * 64,
        termination_proof=termination_proof,
        terminal_reconciliation=terminal_reconciliation,
    )
    assert failed.status == "failed"
    assert supervisor.read(running.attempt_id).status == "failed"


def test_reservation_emits_only_bounded_capability_trace_events(tmp_path) -> None:
    events = []
    intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now = _fixture(
        tmp_path,
        trace_sink=events.append,
    )

    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.trace",
        lease_seconds=60,
        attempt_id="attempt.trace",
        lease_epoch=1,
        executor_idempotency_key="executor.trace",
        reservation_id="reservation.trace",
        reservation_idempotency_key="reservation-trace-idem",
        now=now,
    )

    assert receipt.status == "dispatch_reserved"
    assert [event.event_type for event in events] == [
        "option.authorization.changed",
        "option.authorization.changed",
        "option.dispatch.reserved",
    ]
    assert events[-1].payload["control_sequence"] == 7


def test_expired_authorization_lease_can_take_over_only_as_a_new_epoch(tmp_path) -> None:
    intent, authorization, _plan, _coordinator, _control_store, _auth_store, _supervisor, now = _fixture(
        tmp_path
    )
    from workbench.capability_factory.execution_authorization import OptionExecutionAuthorizationStore

    first = OptionExecutionAuthorizationStore(tmp_path, clock=lambda: now)
    first.issue(authorization)
    claimed = first.claim(
        authorization.authorization_id,
        idempotency_key=authorization.idempotency_key,
        current_binding_ref=authorization.capability_resolution_binding_ref,
        current_freshness_cursor_ref=authorization.freshness_cursor_ref,
        owner_id="owner.first",
        lease_seconds=1,
    )
    recovered = OptionExecutionAuthorizationStore(
        tmp_path,
        clock=lambda: now + timedelta(seconds=2),
    )
    taken = recovered.take_over_lease(
        claimed.authorization_id,
        owner_id="owner.recovered",
        transition_id="transition.takeover",
        lease_seconds=30,
        reason="supervisor recovery",
    )

    assert taken.status == "claimed"
    assert taken.lease_epoch == 2
    assert taken.claim_owner_id == "owner.recovered"
    assert taken.prior_receipt_digest == claimed.receipt_digest


def test_coordinator_recovers_authorization_and_supervisor_as_one_fenced_epoch(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, auth_store, supervisor, now = _fixture(
        tmp_path
    )
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.first",
        lease_seconds=1,
        attempt_id="attempt.recovery",
        lease_epoch=1,
        executor_idempotency_key="executor.recovery",
        reservation_id="reservation.recovery",
        reservation_idempotency_key="reservation-recovery-idem",
        now=now,
    )
    running = coordinator.acknowledge_executor(
        receipt,
        owner_id="supervisor.first",
        process_handle_ref="trusted-handle.recovery",
    )
    recovered_auth = OptionExecutionAuthorizationStore(
        tmp_path,
        clock=lambda: now + timedelta(seconds=2),
    )
    recovered_supervisor = DurableSupervisorStore(tmp_path)
    recovered = CapabilityDispatchCoordinator(
        authorization_store=recovered_auth,
        control_store=control_store,
        supervisor_store=recovered_supervisor,
    )

    taken = recovered.take_over_lease(
        running,
        owner_id="supervisor.recovered",
        transition_id="takeover.recovery",
        lease_seconds=30,
        reason="recover crashed supervisor",
    )

    assert taken.status == "running"
    assert taken.lease_epoch == 2
    assert recovered_auth.read(authorization.authorization_id).claim_owner_id == "supervisor.recovered"
    assert recovered_supervisor.read(running.attempt_id).lease_epoch == taken.lease_epoch
    assert recovered_supervisor.read(running.attempt_id).lease_owner_id == "supervisor.recovered"


def test_recovery_repairs_a_crash_after_authorization_takeover_without_spawning_again(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, _auth_store, supervisor, now = _fixture(
        tmp_path
    )
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.first",
        lease_seconds=1,
        attempt_id="attempt.partial-takeover",
        lease_epoch=1,
        executor_idempotency_key="executor.partial-takeover",
        reservation_id="reservation.partial-takeover",
        reservation_idempotency_key="reservation-partial-takeover-idem",
        now=now,
    )
    running = coordinator.acknowledge_executor(
        receipt,
        owner_id="supervisor.first",
        process_handle_ref="trusted-handle.partial-takeover",
    )
    recovered_auth = OptionExecutionAuthorizationStore(
        tmp_path,
        clock=lambda: now + timedelta(seconds=2),
    )
    already_taken = recovered_auth.take_over_lease(
        authorization.authorization_id,
        owner_id="supervisor.recovered",
        transition_id="takeover.authorization-only",
        lease_seconds=30,
        reason="authorization journal committed before supervisor journal",
    )
    assert already_taken.lease_epoch == 2

    recovered = CapabilityDispatchCoordinator(
        authorization_store=recovered_auth,
        control_store=control_store,
        supervisor_store=supervisor,
    )
    repaired = recovered.take_over_lease(
        running,
        owner_id="supervisor.recovered",
        transition_id="takeover.repair",
        lease_seconds=30,
        reason="repair supervisor journal after crash",
    )

    assert repaired.status == "running"
    assert repaired.lease_epoch == 2
    assert supervisor.read(running.attempt_id).lease_epoch == 2
    assert supervisor.read(running.attempt_id).lease_owner_id == "supervisor.recovered"

    replayed = recovered.take_over_lease(
        running,
        owner_id="supervisor.recovered",
        transition_id="takeover.repair",
        lease_seconds=30,
        reason="repair supervisor journal after crash",
    )
    assert replayed == repaired


def test_irreconcilable_journal_epochs_are_fenced_as_dispatch_unknown(tmp_path) -> None:
    intent, authorization, plan, coordinator, control_store, _auth_store, supervisor, now = _fixture(
        tmp_path
    )
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=_expectations(intent, authorization.authorization_id),
        owner_id="supervisor.first",
        lease_seconds=1,
        attempt_id="attempt.irreconcilable",
        lease_epoch=1,
        executor_idempotency_key="executor.irreconcilable",
        reservation_id="reservation.irreconcilable",
        reservation_idempotency_key="reservation-irreconcilable-idem",
        now=now,
    )
    running = coordinator.acknowledge_executor(
        receipt,
        owner_id="supervisor.first",
        process_handle_ref="trusted-handle.irreconcilable",
    )
    first_recovery = OptionExecutionAuthorizationStore(
        tmp_path,
        clock=lambda: now + timedelta(seconds=2),
    )
    first_recovery.take_over_lease(
        authorization.authorization_id,
        owner_id="supervisor.recovered.one",
        transition_id="takeover.authorization-only.one",
        lease_seconds=30,
        reason="authorization journal committed before supervisor journal",
    )
    second_recovery = OptionExecutionAuthorizationStore(
        tmp_path,
        clock=lambda: now + timedelta(seconds=40),
    )
    advanced = second_recovery.take_over_lease(
        authorization.authorization_id,
        owner_id="supervisor.recovered.two",
        transition_id="takeover.authorization-only.two",
        lease_seconds=30,
        reason="authorization journal advanced again before supervisor repair",
    )
    assert advanced.lease_epoch == 3

    recovered = CapabilityDispatchCoordinator(
        authorization_store=second_recovery,
        control_store=control_store,
        supervisor_store=supervisor,
    )
    with pytest.raises(ExecutionReceiptError, match="dispatch_unknown recorded"):
        recovered.take_over_lease(
            running,
            owner_id="supervisor.recovered.two",
            transition_id="takeover.irreconcilable",
            lease_seconds=30,
            reason="fence irreconcilable journals",
        )

    assert second_recovery.read(authorization.authorization_id).status == "dispatch_unknown"
    assert supervisor.read(running.attempt_id).status == "dispatch_unknown"
