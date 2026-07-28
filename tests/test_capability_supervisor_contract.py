from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from workbench.capability_factory.dispatch import DispatchReservation
from workbench.capability_factory.control import ControlSubjectCursor
from workbench.capability_factory.supervisor import (
    AttemptQuiescenceProof,
    DurableSupervisorError,
    DurableSupervisorStore,
    ExecutionAttemptRecord,
    SupervisorStateError,
)


def _reservation() -> DispatchReservation:
    cursor = ControlSubjectCursor(
        subject_kind="authorization",
        subject_ref="authorization.alpha",
        validity_revision=1,
        status="claimed",
        effective_at=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
        expires_at=None,
        authority="server.control",
        reason="claimed",
        source_record_ref="source.authorization.alpha",
        control_sequence=11,
    )
    return DispatchReservation(
        reservation_id="reservation.alpha",
        authorization_id="authorization.alpha",
        authorization_payload_digest="a" * 64,
        intent_id="intent.alpha",
        intent_digest="b" * 64,
        run_id="run.alpha",
        attempt_id="attempt.alpha",
        lease_epoch=3,
        executor_idempotency_key="executor.alpha",
        control_sequence=12,
        subject_snapshot=(cursor,),
    )


def _reserved() -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord.from_reservation(_reservation())


def _unknown() -> ExecutionAttemptRecord:
    reserved = _reserved()
    requested = reserved.transition(
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    )
    return requested.transition(
        target_status="dispatch_unknown",
        transition_id="transition.unknown",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="supervisor_lost_before_ack",
    )


def _proof(*, proof_kind: str = "terminated_clean", epoch: int = 3) -> AttemptQuiescenceProof:
    return AttemptQuiescenceProof(
        proof_id="proof.alpha",
        attempt_id="attempt.alpha",
        reservation_id="reservation.alpha",
        authorization_id="authorization.alpha",
        lease_epoch=epoch,
        proof_kind=proof_kind,
        process_handle_ref=(None if proof_kind == "not_spawned" else "handle.alpha"),
        process_tree_digest="c" * 64,
        resource_cleanup_digest="d" * 64,
        output_cleanup_digest="e" * 64,
        issued_by="trusted.supervisor",
        issuer_role="trusted_supervisor",
        issued_at=datetime(2026, 7, 27, 8, 1, tzinfo=timezone.utc),
        authority_attestation_digest="f" * 64,
    )


def test_reserved_attempt_is_content_addressed_and_round_trips() -> None:
    record = _reserved()
    restored = ExecutionAttemptRecord.from_dict(record.to_dict())

    assert restored == record
    assert record.status == "reserved"
    assert record.reservation_id == "reservation.alpha"
    assert record.executor_idempotency_key == "executor.alpha"
    assert record.lease_epoch == 3
    assert record.content_digest == record.to_dict()["content_digest"]


def test_attempt_digest_binds_every_execution_identity() -> None:
    record = _reserved()

    assert replace(record, attempt_id="attempt.beta").content_digest != record.content_digest
    assert replace(record, lease_epoch=4).content_digest != record.content_digest
    assert replace(record, executor_idempotency_key="executor.beta").content_digest != record.content_digest
    assert replace(record, reservation_id="reservation.beta").content_digest != record.content_digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "runs/attempt.alpha"),
        ("reservation_id", "../reservation"),
        ("lease_epoch", 0),
        ("status", "not-a-status"),
    ],
)
def test_attempt_rejects_untrusted_identity_values(field: str, value: object) -> None:
    with pytest.raises(SupervisorStateError):
        replace(_reserved(), **{field: value})


def test_attempt_schema_is_exact_and_digest_is_verified() -> None:
    payload = _reserved().to_dict()
    payload["unexpected"] = "rejected"
    with pytest.raises(SupervisorStateError):
        ExecutionAttemptRecord.from_dict(payload)

    payload = _reserved().to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(SupervisorStateError):
        ExecutionAttemptRecord.from_dict(payload)


def test_attempt_transitions_bind_owner_epoch_and_handle() -> None:
    requested = _reserved().transition(
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    )
    acknowledged = requested.transition(
        target_status="spawn_acknowledged",
        transition_id="transition.ack",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        process_handle_ref="handle.alpha",
        reason="acknowledged",
    )
    running = acknowledged.transition(
        target_status="running",
        transition_id="transition.running",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        process_handle_ref="handle.alpha",
        reason="running",
    )

    assert running.status == "running"
    assert running.process_handle_ref == "handle.alpha"
    assert running.prior_state_digest == acknowledged.content_digest


def test_stale_epoch_and_handle_replacement_are_rejected() -> None:
    requested = _reserved().transition(
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    )
    acknowledged = requested.transition(
        target_status="spawn_acknowledged",
        transition_id="transition.ack",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        process_handle_ref="handle.alpha",
        reason="acknowledged",
    )

    with pytest.raises(SupervisorStateError, match="epoch"):
        acknowledged.transition(
            target_status="running",
            transition_id="transition.stale",
            owner_id="supervisor.alpha",
            lease_epoch=2,
            process_handle_ref="handle.alpha",
            reason="stale",
        )

    with pytest.raises(SupervisorStateError, match="handle"):
        acknowledged.transition(
            target_status="running",
            transition_id="transition.other-handle",
            owner_id="supervisor.alpha",
            lease_epoch=3,
            process_handle_ref="handle.beta",
            reason="replacement",
        )


def test_transition_replay_is_idempotent_only_for_the_same_payload() -> None:
    requested = _reserved().transition(
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    )
    assert requested.transition(
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    ) == requested

    with pytest.raises(SupervisorStateError, match="replay"):
        requested.transition(
            target_status="spawn_requested",
            transition_id="transition.request",
            owner_id="supervisor.alpha",
            lease_epoch=3,
            reason="changed",
        )


def test_unknown_dispatch_is_terminal_without_quiescence_reconciliation() -> None:
    unknown = _unknown()

    with pytest.raises(SupervisorStateError, match="terminal"):
        unknown.transition(
            target_status="running",
            transition_id="transition.retry",
            owner_id="supervisor.alpha",
            lease_epoch=3,
            process_handle_ref="handle.beta",
            reason="retry",
        )


def test_quiescence_proof_releases_isolation_but_never_resumes_execution() -> None:
    assessment = _unknown().assess_quiescence(_proof())

    assert assessment.outcome == "quiescent"
    assert assessment.release_isolation is True
    assert assessment.requires_new_user_authorization is True
    assert assessment.execution_allowed is False
    assert assessment.source_attempt_status == "dispatch_unknown"


def test_not_spawned_proof_is_valid_and_unknown_proof_is_not_a_proof() -> None:
    assessment = _unknown().assess_quiescence(_proof(proof_kind="not_spawned"))
    assert assessment.outcome == "quiescent"

    with pytest.raises(SupervisorStateError, match="proof"):
        _unknown().assess_quiescence(replace(_proof(), proof_kind="unknown"))


def test_quiescence_proof_must_match_attempt_and_epoch() -> None:
    unknown = _unknown()

    with pytest.raises(SupervisorStateError, match="attempt"):
        unknown.assess_quiescence(replace(_proof(), attempt_id="attempt.other"))
    with pytest.raises(SupervisorStateError, match="epoch"):
        unknown.assess_quiescence(_proof(epoch=4))


def test_quiescence_assessment_is_content_addressed_and_exact() -> None:
    assessment = _unknown().assess_quiescence(_proof())
    restored = type(assessment).from_dict(assessment.to_dict())

    assert restored == assessment
    payload = assessment.to_dict()
    payload["execution_allowed"] = True
    with pytest.raises(SupervisorStateError):
        type(assessment).from_dict(payload)


def test_contract_has_no_execution_surface() -> None:
    import workbench.capability_factory.supervisor as module

    assert not hasattr(module, "subprocess")
    assert not hasattr(module, "socket")
    assert not hasattr(module, "Popen")


def test_durable_supervisor_reopens_the_same_attempt_and_fences_old_epoch(tmp_path) -> None:
    store = DurableSupervisorStore(tmp_path)
    reserved = store.create(_reservation())
    requested = store.transition(
        reserved.attempt_id,
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    )
    reopened = DurableSupervisorStore(tmp_path)
    assert reopened.read(reserved.attempt_id) == requested

    recovered = reopened.take_over_lease(
        reserved.attempt_id,
        owner_id="supervisor.beta",
        transition_id="transition.takeover",
    )
    assert recovered.attempt_id == reserved.attempt_id
    assert recovered.lease_epoch == 4
    assert recovered.status == "spawn_requested"

    with pytest.raises(SupervisorStateError, match="epoch"):
        reopened.transition(
            reserved.attempt_id,
            target_status="spawn_acknowledged",
            transition_id="transition.old-ack",
            owner_id="supervisor.alpha",
            lease_epoch=3,
            process_handle_ref="handle.alpha",
            reason="old worker",
        )


def test_durable_supervisor_is_idempotent_for_same_reservation_and_transition(tmp_path) -> None:
    store = DurableSupervisorStore(tmp_path)
    first = store.create(_reservation())
    replay = store.create(_reservation())
    assert replay == first
    requested = store.transition(
        first.attempt_id,
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    )
    assert store.transition(
        first.attempt_id,
        target_status="spawn_requested",
        transition_id="transition.request",
        owner_id="supervisor.alpha",
        lease_epoch=3,
        reason="recorded",
    ) == requested
    assert len(store.history(first.attempt_id)) == 2

    with pytest.raises(DurableSupervisorError, match="another reservation"):
        store.create(replace(_reservation(), reservation_id="reservation.other"))


def test_durable_supervisor_rejects_reusing_an_executor_idempotency_key_for_another_attempt(tmp_path) -> None:
    store = DurableSupervisorStore(tmp_path)
    store.create(_reservation())

    with pytest.raises(DurableSupervisorError, match="executor idempotency key"):
        store.create(
            replace(
                _reservation(),
                attempt_id="attempt.other",
                reservation_id="reservation.other",
            )
        )
