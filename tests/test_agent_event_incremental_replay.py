"""Polling an event log reads only what is new, and a reader never edits the log.

2026-11-06 risk review, finding 7: replay read and parsed the whole JSONL log on every poll, so
an idle 50,000-event session cost about 118 ms per poll with nothing new to return.
"""
from __future__ import annotations

import json

from workbench.agent import events as events_module
from workbench.agent.events import AgentEventStream


def _stream(tmp_path, count):
    stream = AgentEventStream(tmp_path)
    for index in range(count):
        stream.emit("s", "token", {"i": index})
    return stream


def test_an_idle_poll_parses_nothing(tmp_path, monkeypatch):
    stream = _stream(tmp_path, 200)
    last = stream.replay("s")[-1].seq
    parsed = []
    original = events_module.json.loads
    monkeypatch.setattr(events_module.json, "loads", lambda raw, *a, **k: parsed.append(1) or original(raw, *a, **k))
    for _ in range(5):
        assert stream.replay("s", after_seq=last) == []
    assert parsed == []


def test_a_poll_returns_exactly_the_new_events(tmp_path):
    stream = _stream(tmp_path, 50)
    assert [event.seq for event in stream.replay("s", after_seq=47)] == [48, 49, 50]
    stream.emit("s", "token", {"i": 50})
    assert [event.payload["i"] for event in stream.replay("s", after_seq=50)] == [50]
    assert [event.seq for event in stream.replay("s")] == list(range(1, 52))


def test_another_process_s_half_written_line_is_left_alone_and_read_once_complete(tmp_path):
    stream = _stream(tmp_path, 3)
    path = tmp_path / "agent-events" / "s.jsonl"
    whole = json.dumps({"schema_version": "agent.event.v1", "event_id": "x", "session_id": "s", "seq": 4,
                        "event_type": "token", "payload": {}, "command_id": None, "created_at": "t"},
                       sort_keys=True) + "\n"
    with path.open("ab") as handle:
        handle.write(whole[:20].encode())
    before = path.read_bytes()
    assert [event.seq for event in stream.replay("s", after_seq=2)] == [3]
    assert path.read_bytes() == before
    with path.open("ab") as handle:
        handle.write(whole[20:].encode())
    assert [event.seq for event in stream.replay("s", after_seq=3)] == [4]


def test_a_rewritten_shorter_log_is_indexed_again(tmp_path):
    stream = _stream(tmp_path, 10)
    stream.replay("s")
    stream.delete("s")
    for index in range(2):
        stream.emit("s", "token", {"i": index})
    assert [event.seq for event in stream.replay("s")] == [1, 2]


def test_a_fresh_reader_sees_the_same_events_as_the_writer(tmp_path):
    writer = _stream(tmp_path, 30)
    reader = AgentEventStream(tmp_path)
    assert [event.event_id for event in reader.replay("s", after_seq=10)] == \
        [event.event_id for event in writer.replay("s", after_seq=10)]


def test_a_log_deleted_and_rewritten_by_another_stream_is_indexed_again(tmp_path):
    reader = _stream(tmp_path, 5)
    assert [event.payload["i"] for event in reader.replay("s")] == [0, 1, 2, 3, 4]
    other = AgentEventStream(tmp_path)  # e.g. run deletion, in another instance or process
    other.delete("s")
    for index in range(10, 16):  # the same line lengths, one line longer
        other.emit("s", "token", {"i": index})
    assert [event.payload["i"] for event in reader.replay("s")] == [10, 11, 12, 13, 14, 15]
    assert [event.payload["i"] for event in reader.replay("s", after_seq=5)] == [15]
