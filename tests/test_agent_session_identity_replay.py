"""Provider-visible provenance uses the actual journaled session entry IDs."""
from shutil import copytree

import pytest

from workbench.agent import session
from workbench.agent.business_identity import BusinessIdentityError, business_identity_scope


def _fixture(tmp_path):
    initial = tmp_path / "initial"
    repository = session.JsonlSessionRepository(initial)
    repository.create_session(session_id="session", role="chain", chain_id="chain")
    for name in ("record", "replay"):
        copytree(initial, tmp_path / name)
    return tuple(session.JsonlSessionRepository(tmp_path / name) for name in ("record", "replay"))


def _append(repository):
    first = repository.append("session", "message", {"role": "user", "content": "Estimate ATT"})
    intent = repository.append_once("session", "tool_intent", {"tool_call_id": "plan"},
                                    key="command", stage="tool:plan")
    assert repository.append_once("session", "tool_intent", {"tool_call_id": "plan"},
                                  key="command", stage="tool:plan") == intent
    last = repository.append("session", "message", {"role": "assistant", "content": "Plan saved"})
    return [(entry.entry_id, entry.parent_ref.to_dict() if entry.parent_ref else None, entry.payload)
            for entry in (first, intent, last)]


def test_actual_append_and_append_once_entry_ids_replay_without_allocating(tmp_path, monkeypatch):
    recorded_repository, replay_repository = _fixture(tmp_path)
    with business_identity_scope(mode="record", root=tmp_path, name="business.jsonl"):
        expected = _append(recorded_repository)

    def forbidden():
        pytest.fail("replay must consume recorded entry IDs rather than allocate replacements")

    monkeypatch.setattr(session, "uuid4", forbidden)
    with business_identity_scope(mode="replay", root=tmp_path, name="business.jsonl"):
        assert _append(replay_repository) == expected
    for entry_id, _, _ in expected:
        entry = replay_repository.get_entry(session.EntryRef("session", entry_id))
        assert entry.entry_id == entry_id


def test_entry_identity_replay_refuses_a_different_allocation_owner_state(tmp_path):
    recorded_repository, replay_repository = _fixture(tmp_path)
    with business_identity_scope(mode="record", root=tmp_path, name="business.jsonl"):
        recorded_repository.append("session", "message", {"role": "user", "content": "Estimate ATT"})
    with pytest.raises(BusinessIdentityError, match="mismatch"):
        with business_identity_scope(mode="replay", root=tmp_path, name="business.jsonl"):
            replay_repository.append("session", "tool_intent", {"tool_call_id": "plan"})


def test_journal_without_session_allocations_has_no_replay_fallback(tmp_path):
    _, replay_repository = _fixture(tmp_path)
    with business_identity_scope(mode="record", root=tmp_path, name="business.jsonl"):
        pass
    with pytest.raises(BusinessIdentityError, match="exhausted"):
        with business_identity_scope(mode="replay", root=tmp_path, name="business.jsonl"):
            replay_repository.append("session", "message", {"role": "user", "content": "Estimate ATT"})
