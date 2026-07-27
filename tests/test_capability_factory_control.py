from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest

from workbench.capability_factory.contracts import SemanticProfile


_NOW = datetime(2026, 7, 27, 4, 30, tzinfo=timezone.utc)


def _subject(control, *, ref="subject.alpha", revision=1, status="valid", expires_at=None):
    return control.ControlSubjectCursor(
        subject_kind="synthetic",
        subject_ref=ref,
        validity_revision=revision,
        status=status,
        effective_at=_NOW - timedelta(seconds=1),
        expires_at=expires_at,
        authority="server.control",
        reason="fixture",
        source_record_ref=f"source-{ref}",
    )


def _expectation(control, *, ref="subject.alpha", revision=1, status="valid"):
    return control.ControlCursorExpectation(
        subject_kind="synthetic",
        subject_ref=ref,
        validity_revision=revision,
        expected_status=status,
        require_unexpired=True,
    )


def _request(control, *, record_id="record.alpha", idempotency_key="idem.alpha", value=None):
    return control.ControlAppendRequest(
        record_id=record_id,
        record_type="synthetic_reservation",
        value=value or {"purpose": "test"},
        idempotency_key=idempotency_key,
    )


def _control():
    try:
        return importlib.import_module("workbench.capability_factory.control")
    except ModuleNotFoundError as error:
        pytest.fail(f"CF1 control module is not implemented: {error}")


def test_append_only_control_requires_expected_sequence_and_keeps_history():
    control = _control()
    store = control.AppendOnlyControlStore()

    first = store.append(
        namespace="profile.alpha",
        value={"status": "active"},
        expected_sequence=0,
    )
    second = store.append(
        namespace="profile.alpha",
        value={"status": "revoked"},
        expected_sequence=1,
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [item.sequence for item in store.history("profile.alpha")] == [1, 2]
    with pytest.raises(control.OptimisticConcurrencyError):
        store.append(
            namespace="profile.alpha",
            value={"status": "stale-write"},
            expected_sequence=1,
        )


def test_control_values_are_snapshotted_and_not_mutable_after_append():
    control = _control()
    value = {"status": "active", "labels": {"scope": "project"}}
    store = control.AppendOnlyControlStore()
    record = store.append(namespace="profile.alpha", value=value, expected_sequence=0)
    value["status"] = "changed-outside-store"

    assert record.value["status"] == "active"
    with pytest.raises(TypeError):
        record.value["status"] = "changed-inside-store"


def test_content_addressed_store_reuses_exact_immutable_content():
    store_module = importlib.import_module("workbench.capability_factory.store")
    store = store_module.ContentAddressedStore()
    profile = SemanticProfile(
        profile_id="profile.alpha",
        revision=1,
        input_kinds=("scalar",),
        operations=("fit",),
        output_facets=("estimate",),
        assumptions=(),
        consumers={
            "report_projection": None,
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )

    assert store.put(profile) == profile.content_digest
    assert store.put(profile) == profile.content_digest
    assert store.get(profile.content_digest) is profile
    assert len(store) == 1


def test_execution_control_compares_cursors_and_is_idempotent():
    control = _control()
    store = control.ExecutionControlStore(clock=lambda: _NOW)
    published = store.publish_subject(_subject(control, expires_at=_NOW + timedelta(minutes=1)))

    result = store.compare_cursors_and_append(
        expectations=(_expectation(control),),
        record=_request(control),
        now=_NOW,
    )
    retry = store.compare_cursors_and_append(
        expectations=(_expectation(control),),
        record=_request(control),
        now=_NOW + timedelta(seconds=1),
    )

    assert published.control_sequence == 1
    assert result is retry
    assert result.control_sequence == 2
    assert result.subject_snapshot[0].validity_revision == 1
    assert result.record_digest == result.request.content_digest
    assert store.latest_record() is result


def test_execution_control_rejects_revocation_without_partial_record():
    control = _control()
    store = control.ExecutionControlStore(clock=lambda: _NOW)
    store.publish_subject(_subject(control, ref="subject.alpha"))
    store.publish_subject(_subject(control, ref="subject.beta"))
    store.publish_subject(_subject(control, ref="subject.beta", revision=2, status="revoked"))

    with pytest.raises(control.ControlCursorConflict):
        store.compare_cursors_and_append(
            expectations=(
                _expectation(control, ref="subject.alpha"),
                _expectation(control, ref="subject.beta"),
            ),
            record=_request(control, record_id="record.rejected", idempotency_key="idem.rejected"),
            now=_NOW,
        )

    assert store.latest_record() is None
    assert store.control_sequence == 3


def test_execution_control_reservation_before_revocation_remains_historical():
    control = _control()
    store = control.ExecutionControlStore(clock=lambda: _NOW)
    store.publish_subject(_subject(control, expires_at=_NOW + timedelta(minutes=1)))
    reservation = store.compare_cursors_and_append(
        expectations=(_expectation(control),),
        record=_request(control),
        now=_NOW,
    )
    store.publish_subject(_subject(control, revision=2, status="revoked"))

    assert store.compare_cursors_and_append(
        expectations=(_expectation(control),),
        record=_request(control),
        now=_NOW + timedelta(seconds=1),
    ) is reservation

    with pytest.raises(control.ControlSubjectRejected):
        store.compare_cursors_and_append(
            expectations=(_expectation(control, revision=2, status="valid"),),
            record=_request(control, record_id="record.new", idempotency_key="idem.new"),
            now=_NOW + timedelta(seconds=1),
        )


def test_execution_control_rejects_stale_revision_and_expired_subject():
    control = _control()
    store = control.ExecutionControlStore(clock=lambda: _NOW)
    store.publish_subject(_subject(control, expires_at=_NOW - timedelta(milliseconds=500)))

    with pytest.raises(control.ControlSubjectExpired):
        store.compare_cursors_and_append(
            expectations=(_expectation(control),),
            record=_request(control),
            now=_NOW,
        )

    store.publish_subject(_subject(control, ref="subject.beta", revision=3))
    with pytest.raises(control.ControlCursorConflict):
        store.compare_cursors_and_append(
            expectations=(_expectation(control, ref="subject.beta", revision=2),),
            record=_request(control, record_id="record.stale", idempotency_key="idem.stale"),
            now=_NOW,
        )

    assert store.latest_record() is None


def test_execution_control_rejects_idempotency_payload_mismatch_and_freezes_input():
    control = _control()
    store = control.ExecutionControlStore(clock=lambda: _NOW)
    store.publish_subject(_subject(control))
    value = {"purpose": "test", "nested": {"scope": "project"}}
    request = _request(control, value=value)
    stored = store.compare_cursors_and_append(
        expectations=(_expectation(control),),
        record=request,
        now=_NOW,
    )
    value["purpose"] = "changed"

    with pytest.raises(control.ControlReplayMismatch):
        store.compare_cursors_and_append(
            expectations=(_expectation(control),),
            record=_request(control, value={"purpose": "other"}),
            now=_NOW,
        )

    assert stored.request.value["purpose"] == "test"
    with pytest.raises(TypeError):
        stored.request.value["purpose"] = "changed-inside-store"
