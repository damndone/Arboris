from __future__ import annotations

import gzip
import json
import os
import threading
import uuid
from pathlib import Path

import pytest

from workbench.development_control import events
from workbench.development_control.events import (
    EventValidationError,
    append_event,
    canonical_event_bytes,
    validate_event,
    verify_log,
)


def _event(*, event_type: str = "FAILURE", event_id: str | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": event_id or str(uuid.uuid4()),
        "timestamp": "2026-07-19T12:34:56.789Z",
        "type": event_type,
        "subtype": "contract_check",
        "stage": "review",
        "cause_status": "known",
        "cause": "contract needs an explicit test",
        "evidence": {
            "kind": "test",
            "ref": "tests/test_devline_control_events.py::test_valid_events",
            "sha256": "a" * 64,
            "observed_at": "2026-07-19T12:34:56.789Z",
        },
        "impact": "prevents an unsafe gate acceptance",
        "preventability": "preventable",
        "resolution": "resolved",
        "lesson": "test the public contract before changing it",
        "incident_id": str(uuid.uuid4()),
        "lesson_key": "event-contract",
        "links": [],
    }


def _line(tmp_path: Path, name: str = "wo-a") -> tuple[Path, str]:
    root = tmp_path / ".agent" / "devlines"
    (root / name).mkdir(parents=True)
    return root, name


def test_validates_every_supported_event_type_and_canonicalizes_stably() -> None:
    for event_type in ("FAILURE", "ERROR", "GAP", "WASTE", "REVIEW", "GATE", "STATE_CHANGE"):
        event = _event(event_type=event_type)
        validated = validate_event(event, previous_sha256="0" * 64)
        assert validated["prev_event_sha256"] == "0" * 64
        assert len(validated["event_sha256"]) == 64
        assert canonical_event_bytes(validated) == canonical_event_bytes(dict(reversed(list(validated.items()))))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda event: event.pop("lesson"),
        lambda event: event.__setitem__("type", "NOT_A_TYPE"),
        lambda event: event.__setitem__("timestamp", "2026-07-19 12:34:56Z"),
        lambda event: event.__setitem__("event_id", "not-a-uuid"),
        lambda event: event.__setitem__("preventability", "maybe"),
        lambda event: event.__setitem__("cause", "token=secret-value"),
    ],
)
def test_rejects_invalid_event_contracts(mutate: object) -> None:
    event = _event()
    mutate(event)  # type: ignore[operator]
    with pytest.raises(EventValidationError):
        validate_event(event, previous_sha256="0" * 64)


def test_rejects_events_larger_than_sixteen_kib() -> None:
    event = _event()
    event["lesson"] = "x" * (16 * 1024)
    with pytest.raises(EventValidationError, match="16 KiB"):
        validate_event(event, previous_sha256="0" * 64)


def test_append_is_anchored_and_detects_duplicate_ids_and_hash_integrity(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    first = _event()
    appended = append_event(root, line_id, first)
    assert appended["prev_event_sha256"] == "0" * 64
    assert verify_log(root, line_id)["event_count"] == 1

    with pytest.raises(EventValidationError, match="duplicate event_id"):
        append_event(root, line_id, _event(event_id=str(first["event_id"])))

    events_path = root / line_id / "events.jsonl"
    row = json.loads(events_path.read_text(encoding="utf-8"))
    row["lesson"] = "rewritten after append"
    events_path.write_bytes(canonical_event_bytes(row) + b"\n")
    with pytest.raises(EventValidationError, match="event_sha256"):
        verify_log(root, line_id)


def test_rejects_malicious_line_ids_and_symbolic_link_line_directories(tmp_path: Path) -> None:
    root, _ = _line(tmp_path)
    with pytest.raises(EventValidationError):
        append_event(root, "../escape", _event())

    target = tmp_path / "target"
    target.mkdir()
    (root / "wo-link").symlink_to(target, target_is_directory=True)
    with pytest.raises(EventValidationError, match="symlink"):
        append_event(root, "wo-link", _event())


def test_verifier_rejects_truncated_and_reordered_chains(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    append_event(root, line_id, _event())
    append_event(root, line_id, _event())
    path = root / line_id / "events.jsonl"
    rows = path.read_bytes().splitlines()

    path.write_bytes(rows[0])
    with pytest.raises(EventValidationError, match="trailing newline"):
        verify_log(root, line_id)

    path.write_bytes(rows[0] + b"\n")
    with pytest.raises(EventValidationError, match="tail anchor"):
        verify_log(root, line_id)

    path.write_bytes(rows[1] + b"\n" + rows[0] + b"\n")
    with pytest.raises(EventValidationError, match="prev_event_sha256"):
        verify_log(root, line_id)


def test_append_serializes_two_writers_without_interleaving(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    errors: list[BaseException] = []

    def append() -> None:
        try:
            append_event(root, line_id, _event())
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    writers = [threading.Thread(target=append), threading.Thread(target=append)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    assert not errors
    result = verify_log(root, line_id)
    assert result["event_count"] == 2
    rows = (root / line_id / "events.jsonl").read_bytes().splitlines()
    assert len(rows) == 2
    assert all(json.loads(row) for row in rows)


def test_append_recovers_archive_published_before_interrupted_truncate(tmp_path: Path, monkeypatch) -> None:
    root, line_id = _line(tmp_path)
    append_event(root, line_id, _event())
    events.archive_event_log(root, line_id)
    previous = append_event(root, line_id, _event())
    anchor = verify_log(root, line_id)
    archive = root / line_id / "events.jsonl.gz"
    live = root / line_id / "events.jsonl"
    original = gzip.decompress(archive.read_bytes()) + live.read_bytes()

    def interrupt_truncate(*_args):
        raise OSError("interrupted after archive publication")

    with monkeypatch.context() as patch:
        patch.setattr(events.os, "ftruncate", interrupt_truncate)
        with pytest.raises(OSError, match="interrupted"):
            events.archive_event_log(root, line_id)
    assert gzip.decompress(archive.read_bytes()) == original
    assert live.read_bytes()
    assert verify_log(root, line_id) == anchor

    appended = append_event(root, line_id, _event())
    assert appended["prev_event_sha256"] == previous["event_sha256"]
    assert live.read_bytes() == canonical_event_bytes(appended) + b"\n"
    assert verify_log(root, line_id)["event_count"] == 3


@pytest.mark.parametrize("damage", ["corrupt", "missing", "valid_gzip_with_truncated_history"])
def test_verification_and_append_reject_a_damaged_archive(tmp_path: Path, damage: str) -> None:
    root, line_id = _line(tmp_path)
    append_event(root, line_id, _event())
    append_event(root, line_id, _event())
    events.archive_event_log(root, line_id)
    archive = root / line_id / "events.jsonl.gz"
    if damage == "corrupt":
        archive.write_bytes(b"not gzip")
    elif damage == "missing":
        archive.unlink()
    else:
        archive.write_bytes(gzip.compress(gzip.decompress(archive.read_bytes()).splitlines()[0] + b"\n"))
    with pytest.raises(EventValidationError):
        verify_log(root, line_id)
    with pytest.raises(EventValidationError):
        append_event(root, line_id, _event())
    assert (root / line_id / "events.jsonl").read_bytes() == b""


def test_archive_serializes_with_append_and_verified_read(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    append_event(root, line_id, _event())
    errors: list[Exception] = []
    ready = threading.Barrier(3)

    def worker(action) -> None:
        try:
            ready.wait(timeout=5)
            for _ in range(5):
                action()
        except Exception as error:
            errors.append(error)

    threads = [
        threading.Thread(target=worker, args=(action,))
        for action in (
            lambda: events.archive_event_log(root, line_id),
            lambda: append_event(root, line_id, _event()),
            lambda: verify_log(root, line_id),
        )
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert verify_log(root, line_id)["event_count"] == 6


def test_schema_is_versioned_and_matches_required_contract() -> None:
    schema_path = Path(__file__).parents[1] / ".agent/development-control/schemas/event-v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"].endswith("event-v1.json")
    assert set(_event()) | {"prev_event_sha256", "event_sha256"} <= set(schema["required"])
    assert schema["additionalProperties"] is False
