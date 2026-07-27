from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from workbench.capability_factory.control import (
    ControlAppendRequest,
    ControlCursorConflict,
    ControlCursorExpectation,
    ControlSubjectRejected,
    ControlSubjectCursor,
    ExecutionControlRecord,
    ExecutionControlStore,
)
from workbench.capability_factory.dispatch import (
    DispatchReservation,
    DispatchReservationError,
    PREPARED_RUN_INTENT_CONTRACT_VERSION,
    PreparedRunIntent,
    PreparedRunIntentError,
)


def _intent() -> PreparedRunIntent:
    return PreparedRunIntent(
        intent_id="intent.alpha",
        draft_id="draft.alpha",
        draft_hash="sha256:" + "1" * 64,
        binding_ref="a" * 64,
        binding_revision=2,
        capability_ref="b" * 64,
        bundle_ref="c" * 64,
        evidence_ref="d" * 64,
        admission_ref="e" * 64,
        runtime_policy_ref="f" * 64,
        host_containment_ref="0" * 64,
        operation_id="fit",
        run_id="run.alpha",
        input_graph_fingerprint="graph.alpha",
        input_contract_ref="1" * 64,
        output_contract_ref="2" * 64,
        consumer_projection_ref="3" * 64,
        host_validity_revision=1,
        bundle_validity_revision=1,
        evidence_validity_revision=1,
        admission_validity_revision=1,
        artifact_namespace="artifact.alpha",
        graph_edge_namespace="graph-edge.alpha",
        trace_event_namespace="trace.alpha",
        namespace_derivation_revision=1,
        artifact_producer_revision=1,
        graph_producer_revision=1,
        trace_producer_revision=1,
        slot_mapping_revision=1,
        harness_abi_revision=1,
        protocol_revision=1,
    )


def _control_record(intent: PreparedRunIntent) -> ExecutionControlRecord:
    store = ExecutionControlStore(clock=lambda: datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc))
    now = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    cursor = ControlSubjectCursor(
        subject_kind="binding",
        subject_ref="binding.alpha",
        validity_revision=2,
        status="valid",
        effective_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=1),
        authority="server.control",
        reason="fixture",
        source_record_ref="source-binding.alpha",
    )
    store.publish_subject(cursor)
    return store.compare_cursors_and_append(
        expectations=(
            ControlCursorExpectation(
                subject_kind="binding",
                subject_ref="binding.alpha",
                validity_revision=2,
                expected_status="valid",
            ),
        ),
        record=ControlAppendRequest(
            record_id="reservation.alpha",
            record_type="dispatch_reservation",
            value={
                "authorization_id": "authorization.alpha",
                "authorization_payload_digest": "4" * 64,
                "intent_id": intent.intent_id,
                "intent_digest": intent.content_digest,
                "run_id": intent.run_id,
                "attempt_id": "attempt.alpha",
                "lease_epoch": 1,
                "executor_idempotency_key": "executor.alpha",
            },
            idempotency_key="reservation-idem.alpha",
        ),
        now=now,
    )


def _fenced_store(
    intent: PreparedRunIntent,
    *,
    authorization_id: str = "authorization.alpha",
    authorization_status: str = "claimed",
) -> tuple[ExecutionControlStore, datetime]:
    now = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    store = ExecutionControlStore(clock=lambda: now)
    subjects = (
        ("authorization", authorization_id, 1, authorization_status),
        ("binding", intent.binding_ref, intent.binding_revision, "valid"),
        ("host_containment", intent.host_containment_ref, intent.host_validity_revision, "valid"),
        ("bundle", intent.bundle_ref, intent.bundle_validity_revision, "valid"),
        ("evidence", intent.evidence_ref, intent.evidence_validity_revision, "valid"),
        ("admission", intent.admission_ref, intent.admission_validity_revision, "valid"),
    )
    for kind, reference, revision, status in subjects:
        store.publish_subject(
            ControlSubjectCursor(
                subject_kind=kind,
                subject_ref=reference,
                validity_revision=revision,
                status=status,
                effective_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(minutes=1),
                authority="server.control",
                reason="current",
                source_record_ref=f"source_{kind}",
            )
        )
    return store, now


def _fenced_expectations(
    intent: PreparedRunIntent,
    *,
    authorization_id: str = "authorization.alpha",
) -> tuple[ControlCursorExpectation, ...]:
    return (
        ControlCursorExpectation(
            subject_kind="authorization",
            subject_ref=authorization_id,
            validity_revision=1,
            expected_status="claimed",
        ),
        ControlCursorExpectation(
            subject_kind="binding",
            subject_ref=intent.binding_ref,
            validity_revision=intent.binding_revision,
            expected_status="valid",
        ),
        ControlCursorExpectation(
            subject_kind="host_containment",
            subject_ref=intent.host_containment_ref,
            validity_revision=intent.host_validity_revision,
            expected_status="valid",
        ),
        ControlCursorExpectation(
            subject_kind="bundle",
            subject_ref=intent.bundle_ref,
            validity_revision=intent.bundle_validity_revision,
            expected_status="valid",
        ),
        ControlCursorExpectation(
            subject_kind="evidence",
            subject_ref=intent.evidence_ref,
            validity_revision=intent.evidence_validity_revision,
            expected_status="valid",
        ),
        ControlCursorExpectation(
            subject_kind="admission",
            subject_ref=intent.admission_ref,
            validity_revision=intent.admission_validity_revision,
            expected_status="valid",
        ),
    )
def test_prepared_run_intent_is_content_addressed_and_round_trips():
    intent = _intent()
    payload = intent.to_dict()
    restored = PreparedRunIntent.from_dict(payload)

    assert payload["contract_version"] == PREPARED_RUN_INTENT_CONTRACT_VERSION
    assert payload["content_digest"] == intent.content_digest
    assert restored == intent
    assert restored.to_dict() == payload


def test_prepared_run_intent_digest_binds_every_execution_identity_field():
    intent = _intent()

    assert replace(intent, run_id="run.beta").content_digest != intent.content_digest
    assert replace(intent, draft_hash="sha256:" + "2" * 64).content_digest != intent.content_digest
    assert replace(intent, admission_validity_revision=2).content_digest != intent.content_digest
    assert replace(intent, graph_edge_namespace="graph-edge.beta").content_digest != intent.content_digest
    assert replace(intent, harness_abi_revision=2).content_digest != intent.content_digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_id", "../intent"),
        ("run_id", "runs/run.alpha"),
        ("artifact_namespace", "artifact/escape"),
        ("binding_ref", "not-a-digest"),
        ("draft_hash", "sha256:not-a-digest"),
        ("binding_revision", 0),
        ("protocol_revision", 0),
    ],
)
def test_prepared_run_intent_rejects_untrusted_identity_values(field, value):
    with pytest.raises(PreparedRunIntentError):
        replace(_intent(), **{field: value})


def test_prepared_run_intent_rejects_unknown_fields_and_tampered_digest():
    payload = _intent().to_dict()
    payload["unexpected"] = "not-accepted"
    with pytest.raises(PreparedRunIntentError):
        PreparedRunIntent.from_dict(payload)

    payload = _intent().to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(PreparedRunIntentError):
        PreparedRunIntent.from_dict(payload)


def test_prepared_run_intent_has_no_persistence_or_run_side_effects(tmp_path):
    intent = _intent()
    assert intent.run_id == "run.alpha"
    assert list(tmp_path.iterdir()) == []


def test_dispatch_reservation_derives_from_exact_intent_and_control_snapshot():
    intent = _intent()
    control_record = _control_record(intent)
    reservation = DispatchReservation.from_control_record(
        intent=intent,
        control_record=control_record,
    )

    assert reservation.reservation_id == "reservation.alpha"
    assert reservation.intent_digest == intent.content_digest
    assert reservation.run_id == intent.run_id
    assert reservation.control_sequence == control_record.control_sequence
    assert reservation.subject_snapshot == control_record.subject_snapshot


def test_dispatch_reservation_round_trips_and_binds_all_identity_fields():
    reservation = DispatchReservation.from_control_record(
        intent=_intent(),
        control_record=_control_record(_intent()),
    )
    restored = DispatchReservation.from_dict(reservation.to_dict())

    assert restored == reservation
    assert replace(reservation, attempt_id="attempt.beta").content_digest != reservation.content_digest
    assert replace(reservation, lease_epoch=2).content_digest != reservation.content_digest


def test_dispatch_reservation_rejects_wrong_intent_or_record_payload():
    intent = _intent()
    with pytest.raises(DispatchReservationError):
        DispatchReservation.from_control_record(
            intent=replace(intent, run_id="run.other"),
            control_record=_control_record(intent),
        )

    control_record = _control_record(intent)
    bad_request = ControlAppendRequest(
        record_id=control_record.request.record_id,
        record_type="other_record",
        value=control_record.request.value,
        idempotency_key=control_record.request.idempotency_key,
    )
    with pytest.raises(DispatchReservationError):
        DispatchReservation.from_control_record(
            intent=intent,
            control_record=ExecutionControlRecord(
                control_sequence=control_record.control_sequence,
                request=bad_request,
                subject_snapshot=control_record.subject_snapshot,
                request_digest=control_record.request_digest,
            ),
        )


def test_dispatch_reservation_rejects_tampered_serialized_digest():
    reservation = DispatchReservation.from_control_record(
        intent=_intent(),
        control_record=_control_record(_intent()),
    )
    payload = reservation.to_dict()
    payload["content_digest"] = "0" * 64

    with pytest.raises(DispatchReservationError):
        DispatchReservation.from_dict(payload)


def test_dispatch_reservation_fence_requires_all_pinned_subjects_and_is_idempotent():
    intent = _intent()
    store, now = _fenced_store(intent)
    expectations = _fenced_expectations(intent)

    reservation = DispatchReservation.reserve(
        control_store=store,
        intent=intent,
        authorization_id="authorization.alpha",
        authorization_payload_digest="4" * 64,
        authorization_validity_revision=1,
        attempt_id="attempt.fenced",
        lease_epoch=1,
        executor_idempotency_key="executor.fenced",
        record_id="reservation.fenced",
        idempotency_key="reservation-fenced-idem",
        expectations=expectations,
        now=now,
    )
    assert reservation.control_sequence == store.control_sequence
    assert len(store.records()) == 1

    store.publish_subject(
        ControlSubjectCursor(
            subject_kind="binding",
            subject_ref=intent.binding_ref,
            validity_revision=3,
            status="revoked",
            effective_at=now,
            expires_at=None,
            authority="server.control",
            reason="revoked",
            source_record_ref="source_binding_revoke",
        ),
        expected_validity_revision=intent.binding_revision,
    )
    repeated = DispatchReservation.reserve(
        control_store=store,
        intent=intent,
        authorization_id="authorization.alpha",
        authorization_payload_digest="4" * 64,
        authorization_validity_revision=1,
        attempt_id="attempt.fenced",
        lease_epoch=1,
        executor_idempotency_key="executor.fenced",
        record_id="reservation.fenced",
        idempotency_key="reservation-fenced-idem",
        expectations=expectations,
        now=now,
    )
    assert repeated == reservation
    assert len(store.records()) == 1


def test_dispatch_reservation_fence_rejects_missing_subject_or_wrong_revision():
    intent = _intent()
    store, now = _fenced_store(intent)
    expectations = _fenced_expectations(intent)

    with pytest.raises(DispatchReservationError, match="required"):
        DispatchReservation.reserve(
            control_store=store,
            intent=intent,
            authorization_id="authorization.alpha",
            authorization_payload_digest="4" * 64,
            authorization_validity_revision=1,
            attempt_id="attempt.missing",
            lease_epoch=1,
            executor_idempotency_key="executor.missing",
            record_id="reservation.missing",
            idempotency_key="reservation-missing-idem",
            expectations=expectations[:-1],
            now=now,
        )

    wrong_revision = expectations[:-1] + (
        replace(expectations[-1], validity_revision=2),
    )
    with pytest.raises(DispatchReservationError, match="revision"):
        DispatchReservation.reserve(
            control_store=store,
            intent=intent,
            authorization_id="authorization.alpha",
            authorization_payload_digest="4" * 64,
            authorization_validity_revision=1,
            attempt_id="attempt.wrong_revision",
            lease_epoch=1,
            executor_idempotency_key="executor.wrong_revision",
            record_id="reservation.wrong_revision",
            idempotency_key="reservation-wrong-revision-idem",
            expectations=wrong_revision,
            now=now,
        )


def test_dispatch_reservation_fence_serializes_revocation_before_first_reservation():
    intent = _intent()
    store, now = _fenced_store(intent)
    store.publish_subject(
        ControlSubjectCursor(
            subject_kind="binding",
            subject_ref=intent.binding_ref,
            validity_revision=3,
            status="revoked",
            effective_at=now,
            expires_at=None,
            authority="server.control",
            reason="revoked",
            source_record_ref="source_binding_revoke_first",
        ),
        expected_validity_revision=intent.binding_revision,
    )

    with pytest.raises(ControlCursorConflict):
        DispatchReservation.reserve(
            control_store=store,
            intent=intent,
            authorization_id="authorization.alpha",
            authorization_payload_digest="4" * 64,
            authorization_validity_revision=1,
            attempt_id="attempt.revoked",
            lease_epoch=1,
            executor_idempotency_key="executor.revoked",
            record_id="reservation.revoked",
            idempotency_key="reservation-revoked-idem",
            expectations=_fenced_expectations(intent),
            now=now,
        )
    assert not store.records()


def test_dispatch_reservation_fence_requires_claimed_authorization_subject():
    intent = _intent()
    store, now = _fenced_store(intent, authorization_status="revoked")

    with pytest.raises(ControlSubjectRejected):
        DispatchReservation.reserve(
            control_store=store,
            intent=intent,
            authorization_id="authorization.alpha",
            authorization_payload_digest="4" * 64,
            authorization_validity_revision=1,
            attempt_id="attempt.not_claimed",
            lease_epoch=1,
            executor_idempotency_key="executor.not_claimed",
            record_id="reservation.not_claimed",
            idempotency_key="reservation-not-claimed-idem",
            expectations=_fenced_expectations(intent),
            now=now,
        )
