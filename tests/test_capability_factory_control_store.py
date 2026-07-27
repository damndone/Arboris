from __future__ import annotations

from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
from pathlib import Path

import pytest

from workbench.capability_factory.control import (
    ControlAppendRequest,
    ControlCursorExpectation,
    ControlCursorConflict,
    ControlSubjectCursor,
)
from workbench.capability_factory.control_store import DurableControlStoreError, DurableExecutionControlStore


_NOW = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)


def _subject(reference: str, *, revision: int = 1, status: str = "valid") -> ControlSubjectCursor:
    return ControlSubjectCursor(
        subject_kind="synthetic",
        subject_ref=reference,
        validity_revision=revision,
        status=status,
        effective_at=_NOW - timedelta(seconds=1),
        expires_at=_NOW + timedelta(minutes=1),
        authority="server.control",
        reason="fixture",
        source_record_ref=f"source-{reference}",
    )


def _expectation(reference: str, *, revision: int = 1, status: str = "valid") -> ControlCursorExpectation:
    return ControlCursorExpectation(
        subject_kind="synthetic",
        subject_ref=reference,
        validity_revision=revision,
        expected_status=status,
    )


def _request(record_id: str = "record.alpha", idempotency_key: str = "idem.alpha") -> ControlAppendRequest:
    return ControlAppendRequest(
        record_id=record_id,
        record_type="synthetic_reservation",
        value={"purpose": "durable-test"},
        idempotency_key=idempotency_key,
    )


def _publish_worker(root: str, reference: str) -> None:
    store = DurableExecutionControlStore(root, clock=lambda: _NOW)
    store.publish_subject(_subject(reference))


def test_durable_store_rehydrates_subjects_records_and_idempotency(tmp_path: Path):
    store = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)
    store.publish_subject(_subject("subject.alpha"))
    record = store.compare_cursors_and_append(
        expectations=(_expectation("subject.alpha"),),
        record=_request(),
        now=_NOW,
    )

    reloaded = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)
    retry = reloaded.compare_cursors_and_append(
        expectations=(_expectation("subject.alpha"),),
        record=_request(),
        now=_NOW + timedelta(seconds=1),
    )

    assert reloaded.latest_subject("synthetic", "subject.alpha").control_sequence == 1
    assert retry.to_dict() == record.to_dict()
    assert retry.control_sequence == 2
    assert len(reloaded.records()) == 1
    assert len(reloaded.journal.read_text(encoding="utf-8").splitlines()) == 2


def test_durable_store_second_instance_reuses_record_without_duplicate(tmp_path: Path):
    first = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)
    second = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)
    first.publish_subject(_subject("subject.alpha"))
    first_record = first.compare_cursors_and_append(
        expectations=(_expectation("subject.alpha"),),
        record=_request(),
        now=_NOW,
    )

    second_record = second.compare_cursors_and_append(
        expectations=(_expectation("subject.alpha"),),
        record=_request(),
        now=_NOW,
    )

    assert second_record.to_dict() == first_record.to_dict()
    assert len(second.records()) == 1
    assert second.control_sequence == 2


def test_durable_store_rejects_stale_multi_subject_compare_without_append(tmp_path: Path):
    store = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)
    store.publish_subject(_subject("subject.alpha"))
    store.publish_subject(_subject("subject.beta"))
    store.publish_subject(_subject("subject.beta", revision=2, status="revoked"))

    with pytest.raises(ControlCursorConflict):
        store.compare_cursors_and_append(
            expectations=(_expectation("subject.alpha"), _expectation("subject.beta")),
            record=_request(record_id="record.rejected", idempotency_key="idem.rejected"),
            now=_NOW,
        )

    assert store.latest_record() is None
    assert len(store.records()) == 0
    assert len(store.journal.read_text(encoding="utf-8").splitlines()) == 3


def test_durable_store_rejects_malformed_journal_fail_closed(tmp_path: Path):
    journal = tmp_path / "execution-control" / "control-stream.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text('{"record_type":"unexpected"}\n', encoding="utf-8")

    with pytest.raises(DurableControlStoreError):
        DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)


def test_durable_store_read_without_create_is_side_effect_free(tmp_path: Path):
    store = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW, create=False)

    assert store.control_sequence == 0
    assert store.latest_record() is None
    assert not (tmp_path / "execution-control").exists()


def test_durable_store_file_lock_keeps_concurrent_publications_replayable(tmp_path: Path):
    context = get_context("spawn")
    processes = [
        context.Process(target=_publish_worker, args=(str(tmp_path), f"subject.{index}"))
        for index in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    store = DurableExecutionControlStore(tmp_path, clock=lambda: _NOW)
    assert store.control_sequence == 2
    assert len(store.subject_history("synthetic", "subject.0")) == 1
    assert len(store.subject_history("synthetic", "subject.1")) == 1
