"""The session log index: same answers as a full read, fresh objects, any writer noticed."""

from __future__ import annotations

import json
import os
from pathlib import Path

from workbench.agent import session as session_module
from workbench.agent.session import EntryRef, JsonlSessionRepository


def _repo(tmp_path: Path) -> tuple[JsonlSessionRepository, str]:
    repo = JsonlSessionRepository(tmp_path / "workbench")
    session_id = "s1"
    repo.create_session(session_id, role="chain", chain_id="chain-a")
    return repo, session_id


def _full_read(repo: JsonlSessionRepository, session_id: str) -> list[dict]:
    path = repo.sessions_dir / f"{session_id}.jsonl"
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def test_lookups_match_a_full_read_after_every_append(tmp_path):
    repo, sid = _repo(tmp_path)
    for i in range(30):
        repo.append(sid, "message", {"role": "user", "content": f"m{i}", "nested": {"i": [i]}})
        if i % 7 == 0:
            repo.append_once(sid, "turn_state", {"command_id": "c1", "n": i}, key="c1", stage=f"checkpoint:{i}")
        raw = _full_read(repo, sid)
        assert [e.entry_id for e in repo._read_entries(sid)] == [r["entry_id"] for r in raw]
        assert [e.to_dict() for e in repo.get_branch(sid)] == [r for r in raw]
        last = raw[-1]
        assert repo.get_entry(EntryRef(sid, last["entry_id"])).to_dict() == last
    assert repo.count_on_branch(sid, entry_type="turn_state", key="c1") == len(
        [r for r in _full_read(repo, sid) if r["entry_type"] == "turn_state"])


def test_callers_get_their_own_objects(tmp_path):
    repo, sid = _repo(tmp_path)
    entry = repo.append(sid, "message", {"role": "user", "content": "x", "nested": {"list": [1]}})
    first = repo.get_entry(EntryRef(sid, entry.entry_id))
    first.payload["nested"]["list"].append(2)
    first.payload["content"] = "changed"
    again = repo.get_entry(EntryRef(sid, entry.entry_id))
    assert again.payload == {"role": "user", "content": "x", "nested": {"list": [1]}}
    assert repo.get_branch(sid)[-1].payload["nested"]["list"] == [1]


def test_a_write_by_another_writer_is_seen(tmp_path):
    repo, sid = _repo(tmp_path)
    repo.append(sid, "message", {"role": "user", "content": "a"})
    assert len(repo._read_entries(sid)) == 1
    # Another process rewrites the log (new inode, different content).
    path = repo.sessions_dir / f"{sid}.jsonl"
    other = JsonlSessionRepository(tmp_path / "workbench")
    other.append(sid, "message", {"role": "assistant", "content": "b"})
    assert [e.payload["content"] for e in repo._read_entries(sid)] == ["a", "b"]
    # A replacement that is not an append (same length, different bytes) is re-read in full.
    text = path.read_text().replace('"a"', '"z"')
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    assert [e.payload["content"] for e in repo._read_entries(sid)] == ["z", "b"]


def test_branch_after_rewind_and_last_duplicate_wins(tmp_path):
    repo, sid = _repo(tmp_path)
    first = repo.append(sid, "message", {"role": "user", "content": "1"})
    repo.append(sid, "message", {"role": "assistant", "content": "2"})
    repo.rewind(sid, EntryRef(sid, first.entry_id))
    repo.append(sid, "message", {"role": "user", "content": "3"})
    assert [e.payload["content"] for e in repo.get_branch(sid)] == ["1", "3"]
    assert len(repo._read_entries(sid)) == 3


def test_cache_is_bounded():
    assert session_module._LOG_INDEX_LIMIT >= 1
    assert len(session_module._LOG_INDEXES) <= session_module._LOG_INDEX_LIMIT


def _replaced_log(values) -> bytes:
    """What the former read-and-replace append wrote for the same entries."""
    return b"".join((json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                    for value in values)


def test_in_place_appends_write_the_bytes_replacement_wrote(tmp_path):
    repo, sid = _repo(tmp_path)
    path = repo.sessions_dir / f"{sid}.jsonl"
    repo.append(sid, "message", {"role": "user", "content": "首条   é"})
    first_inode = path.stat().st_ino
    for i in range(5):
        repo.append(sid, "message", {"role": "assistant", "content": f"回答 {i}", "n": [i, 1.5, None]})
        repo.append_once(sid, "turn_state", {"command_id": "c1", "i": i}, key="c1", stage=f"checkpoint:{i}")
    assert path.stat().st_ino == first_inode
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_bytes() == _replaced_log(_full_read(repo, sid))
    assert [e.to_dict() for e in repo.get_branch(sid)] == _full_read(repo, sid)


def test_an_unfinished_last_line_is_unseen_and_the_next_append_removes_it(tmp_path):
    repo, sid = _repo(tmp_path)
    repo.append(sid, "message", {"role": "user", "content": "a"})
    path = repo.sessions_dir / f"{sid}.jsonl"
    committed = path.read_bytes()
    with path.open("ab") as handle:
        handle.write(b'{"entry_id": "torn", "payload": {"con')
    assert [e.payload["content"] for e in repo.get_branch(sid)] == ["a"]
    repo.append(sid, "message", {"role": "assistant", "content": "b"})
    assert path.read_bytes().startswith(committed) and b"torn" not in path.read_bytes()
    assert [e.payload["content"] for e in repo.get_branch(sid)] == ["a", "b"]


def test_a_complete_last_line_without_newline_is_kept(tmp_path):
    repo, sid = _repo(tmp_path)
    repo.append(sid, "message", {"role": "user", "content": "a"})
    path = repo.sessions_dir / f"{sid}.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    assert [e.payload["content"] for e in repo._read_entries(sid)] == ["a"]
    repo.append(sid, "message", {"role": "assistant", "content": "b"})
    assert [e.payload["content"] for e in repo.get_branch(sid)] == ["a", "b"]
    assert path.read_bytes().count(b"\n") == 2
