"""Prepared proposal identity survives the admission commit windows only."""
from __future__ import annotations

import asyncio
import copy
import json
import multiprocessing
from pathlib import Path

import pytest

from workbench.agent import proposals
from workbench.agent.operation_requests import OperationRequest
from workbench.agent.session import EntryRef, JsonlSessionRepository, SessionAppendConflict
from tests.test_agent_proposal_operations import make_orchestrator, proposal_kwargs


def invocation():
    return proposals.ProposalInvocation("invocation-a", 2, "call-a")


def store_kwargs():
    return {**proposal_kwargs(), "session_id": "chain-session"}


def admit(orchestrator, **overrides):
    arguments = {**proposal_kwargs(), **overrides}
    scope = {name: arguments.pop(name) for name in ("chain_id", "command_id")}
    session_id = arguments.pop("session_id", "chain-session")
    proposal_id = arguments.pop("proposal_id", None)
    return orchestrator.admit_operation_request(
        OperationRequest.from_arguments(arguments), session_id=session_id,
        proposal_id=proposal_id, invocation=invocation(), **scope,
    ).proposal


def _race_prepared(root, queue, start, ordinary=False, attempted=None, finished=None):
    store = proposals.ProposalStore(root)
    start.wait(10)
    if attempted is not None:
        attempted.set()
    try:
        if ordinary:
            result = store.create(**store_kwargs(), proposal_id="proposal_fixed")
        else:
            result = store.create_prepared(invocation=invocation(), **store_kwargs(),
                                           proposal_id="proposal_fixed")
        queue.put(("ok", result.to_dict()))
    except Exception as exc:
        queue.put((type(exc).__name__, str(exc)))
    finally:
        if finished is not None:
            finished.set()


def _paused_prepared(root, queue, ready, release):
    store = proposals.ProposalStore(root)
    original = proposals.append_jsonl_atomic

    def pause_before_commit(path, value):
        if path.parent == store.proposals_dir:
            ready.set()
            if not release.wait(15):
                raise TimeoutError("prepared test commit was not released")
        return original(path, value)

    proposals.append_jsonl_atomic = pause_before_commit
    try:
        result = store.create_prepared(invocation=invocation(), **store_kwargs(),
                                       proposal_id="proposal_fixed")
        queue.put(("ok", result.to_dict()))
    except Exception as exc:
        queue.put((type(exc).__name__, str(exc)))


@pytest.mark.parametrize("call_id", ["call-a", ""])
def test_generic_tool_passes_trusted_invocation_and_notifies_once(tmp_path, call_id):
    orchestrator = make_orchestrator(tmp_path)
    arguments = {k: v for k, v in proposal_kwargs().items() if k not in {"chain_id", "command_id"}}
    registry = orchestrator.tool_registry("chain-a")
    results = [asyncio.run(registry.execute(
        {"tool_call_id": call_id, "tool_id": "run_operation", "arguments": arguments},
        session_id="chain-session", metadata={"command_id": "cmd-1", "provider_step": 2,
        "tool_call_id": call_id, "invocation_id": "invocation-a"},
    )) for _ in range(2)]
    assert all(result.ok for result in results), results
    assert results[0].output == results[1].output
    assert len(orchestrator.repository.get_branch("chain-session")) == 1
    assert [e.event_type for e in orchestrator.events.replay("chain-session")] == [
        "proposal_ready", "needs_confirmation"]
    assert len(list(orchestrator.proposal_store.proposals_dir.glob("*.jsonl"))) == 1
    assert orchestrator.operation_store.list_records() == []


@pytest.mark.parametrize("after_commit", [False, True])
def test_prepared_write_before_proposal_commit_reuses_id_and_time(tmp_path, monkeypatch, after_commit):
    store = proposals.ProposalStore(tmp_path)
    original = proposals.append_jsonl_atomic

    def interrupt(path, value):
        if path.parent == store.proposals_dir:
            if after_commit:
                original(path, value)
            raise OSError("proposal commit interrupted")
        return original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(proposals, "append_jsonl_atomic", interrupt)
        with pytest.raises(OSError, match="proposal commit interrupted"):
            store.create_prepared(invocation=invocation(), **store_kwargs())
    prepared = list((store.proposals_dir / "prepared").glob("*.jsonl"))
    assert len(prepared) == 1
    original_revision = json.loads(prepared[0].read_text())["revision"]

    def forbidden():
        raise AssertionError("retry must reuse the prepared identity and business time")

    monkeypatch.setattr(proposals, "uuid4", forbidden)
    monkeypatch.setattr(proposals, "_now", forbidden)
    result = proposals.ProposalStore(tmp_path).create_prepared(invocation=invocation(), **store_kwargs())
    assert result.to_dict() == original_revision
    assert store.latest_revision(result.proposal_id).to_dict() == original_revision


@pytest.mark.parametrize("other", [(3, "call-a"), (2, "other-call")])
def test_provider_step_and_call_are_part_of_exact_prepared_scope(tmp_path, other):
    store = proposals.ProposalStore(tmp_path)
    store.create_prepared(invocation=invocation(), **store_kwargs())
    with pytest.raises(proposals.ProposalAdmissionConflict):
        store.create_prepared(invocation=proposals.ProposalInvocation("invocation-a", *other), **store_kwargs())


@pytest.mark.parametrize("after_append", [False, True])
def test_committed_proposal_before_notification_retries_once_across_instances(tmp_path, monkeypatch, after_append):
    orchestrator = make_orchestrator(tmp_path)
    original = orchestrator.repository.append_once

    def interrupt(*args, **kwargs):
        if after_append:
            original(*args, **kwargs)
        raise OSError("notify failed")

    with monkeypatch.context() as patch:
        patch.setattr(orchestrator.repository, "append_once", interrupt)
        with pytest.raises(OSError, match="notify failed"):
            admit(orchestrator)
    before = next(orchestrator.proposal_store.proposals_dir.glob("*.jsonl")).read_bytes()
    orchestrator.repository = JsonlSessionRepository(tmp_path / "workbench")
    orchestrator.proposal_store = proposals.ProposalStore(tmp_path / "workbench")
    first = admit(orchestrator)
    second = admit(orchestrator)
    assert first.to_dict() == second.to_dict()
    assert orchestrator.proposal_store._path(first.proposal_id).read_bytes() == before
    assert len(orchestrator.repository.get_branch("chain-session")) == 1
    entry = orchestrator.repository.get_branch("chain-session")[0]
    assert set(entry.payload) == {"message_type", "audience", "content", "proposal"}
    assert json.loads(entry.payload["content"]) == first.to_dict()


@pytest.mark.parametrize("change", ["changes", "risks", "chain_id", "session_id", "command_id"])
def test_prepared_identity_conflicts_with_any_changed_request_or_scope(tmp_path, change):
    store = proposals.ProposalStore(tmp_path)
    store.create_prepared(invocation=invocation(), **store_kwargs())
    kwargs = copy.deepcopy(store_kwargs())
    kwargs[change] = {"covariance": {"old": "nonrobust", "new": "HC1"}} if change == "changes" else (
        ["different risk"] if change == "risks" else "different-scope")
    with pytest.raises(proposals.ProposalAdmissionConflict):
        proposals.ProposalStore(tmp_path).create_prepared(invocation=invocation(), **kwargs)
    assert len(list(store.proposals_dir.glob("*.jsonl"))) == 1


@pytest.mark.parametrize("transition", ["revise", "confirm", "decline", "executed"])
def test_changed_lifecycle_requires_reconciliation_without_pending_notification(tmp_path, transition):
    orchestrator = make_orchestrator(tmp_path)
    proposal = admit(orchestrator)
    store = orchestrator.proposal_store
    if transition == "revise":
        store.revise(proposal.proposal_id, base_revision=1, changes=proposal.changes)
    elif transition == "decline":
        store.decline(proposal.proposal_id, actor_type="user")
    else:
        confirmation = store.confirm(proposal.proposal_id, revision=1, fingerprint=proposal.fingerprint,
            actor_type="user", current_context_fingerprint="ctx-1", current_active_head_run_id="run-1")
        if transition == "executed":
            record = orchestrator.operation_store.create_pending(confirmation, command_id="cmd-1")
            orchestrator.operation_store.append_status(record.record_id, "completed")
    events_before = orchestrator.events.replay("chain-session")
    with pytest.raises(proposals.ProposalAdmissionNeedsReconciliation, match="needs_reconciliation"):
        admit(orchestrator)
    assert orchestrator.events.replay("chain-session") == events_before
    assert len(orchestrator.repository.get_branch("chain-session")) == 1


@pytest.mark.parametrize("corruption", ["truncated", "unknown", "digest", "revision"])
def test_corrupt_prepared_record_fails_closed(tmp_path, corruption):
    store = proposals.ProposalStore(tmp_path)
    store.create_prepared(invocation=invocation(), **store_kwargs())
    path = next((store.proposals_dir / "prepared").glob("*.jsonl"))
    row = json.loads(path.read_text())
    if corruption == "truncated":
        path.write_text('{"schema_version":')
    else:
        if corruption == "unknown": row["unexpected"] = True
        if corruption == "digest": row["request_sha256"] = "0" * 64
        if corruption == "revision": row["revision"]["created_at"] = "changed"
        path.write_text(json.dumps(row) + "\n")
    before = path.read_bytes()
    with pytest.raises(proposals.ProposalAdmissionConflict):
        proposals.ProposalStore(tmp_path).create_prepared(invocation=invocation(), **store_kwargs())
    assert path.read_bytes() == before


def test_off_branch_notification_identity_cannot_be_revived(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    anchor = orchestrator.repository.append("chain-session", "message", {"role": "user", "content": "anchor"})
    admit(orchestrator)
    orchestrator.repository.rewind("chain-session", EntryRef("chain-session", anchor.entry_id))
    with pytest.raises(SessionAppendConflict, match="off-branch"):
        admit(orchestrator)
    assert len(orchestrator.repository.get_branch("chain-session")) == 1


@pytest.mark.parametrize("ordinary", [False, True])
def test_independent_processes_share_proposal_creation_lock(tmp_path, ordinary):
    invocation()  # Fail visibly before spawning when the prepared API is absent.
    ctx = multiprocessing.get_context("spawn")
    queue, start = ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_race_prepared, args=(str(tmp_path), queue, start, flag))
                 for flag in ([False, True] if ordinary else [False] * 3)]
    for process in processes: process.start()
    start.set()
    results = [queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    successes = [row[1] for row in results if row[0] == "ok"]
    assert len(successes) == (1 if ordinary else 3), results
    assert all(value == successes[0] for value in successes)
    assert len((tmp_path / "proposals/proposal_fixed.jsonl").read_text().splitlines()) == 1


def test_ordinary_create_waits_for_the_prepared_commit_window(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    ready, release, start, attempted, finished = [ctx.Event() for _ in range(5)]
    prepared = ctx.Process(target=_paused_prepared, args=(str(tmp_path), queue, ready, release))
    ordinary = ctx.Process(target=_race_prepared,
        args=(str(tmp_path), queue, start, True, attempted, finished))
    prepared.start()
    try:
        assert ready.wait(15)
        ordinary.start()
        start.set()
        assert attempted.wait(15)
        assert not finished.wait(0.25), "ordinary create bypassed the held prepared creation lock"
    finally:
        release.set()
        prepared.join(20)
        if ordinary.pid is not None:
            ordinary.join(20)
    assert prepared.exitcode == ordinary.exitcode == 0
    results = [queue.get(timeout=5) for _ in range(2)]
    assert sorted(row[0] for row in results) == ["ProposalConfirmationError", "ok"]
    assert len((tmp_path / "proposals/proposal_fixed.jsonl").read_text().splitlines()) == 1
