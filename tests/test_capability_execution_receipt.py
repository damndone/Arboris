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
    validate_artifact_contract_v11,
)
from workbench.contracts.agent.notebook_option import ArtifactContract, ExpectedArtifact
from workbench.capability_factory.supervisor import DurableSupervisorStore

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

    consumed = coordinator.reconcile(
        running,
        owner_id="supervisor.coordinator",
        artifact_validation=validation,
        object_graph_ref="f" * 64,
    )

    assert isinstance(validation, ArtifactContractValidationV11)
    assert validation.validation_status == "passed"
    assert consumed.status == "consumed"
    assert auth_store.read(authorization.authorization_id).status == "consumed"
    assert supervisor.read(running.attempt_id).status == "consumed"


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
