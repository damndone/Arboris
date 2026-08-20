from __future__ import annotations

from pathlib import Path

import pytest

from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import (
    LegacyProposalWriteBoundaryError,
    WorkbenchOrchestrator,
)
from workbench.agent.proposals import (
    ProposalConfirmationError,
    ProposalStore,
    ProposalStoreCapabilityV1,
)
from workbench.agent.session import JsonlSessionRepository
from workbench.http import agent_routes


def _world(
    tmp_path: Path,
    *,
    proposal_store: object | None = None,
) -> tuple[JsonlSessionRepository, AgentEventStream, WorkbenchOrchestrator]:
    root = tmp_path / "workbench"
    repository = JsonlSessionRepository(root)
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    events = AgentEventStream(root)
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        proposal_store=proposal_store,
    )
    return repository, events, orchestrator


def _proposal(store: ProposalStore | ProposalStoreCapabilityV1, *, proposal_id: str = "proposal-1"):
    return store.create(
        proposal_id=proposal_id,
        session_id="chain-session",
        chain_id="chain-a",
        operation_id="model.rerun",
        target={
            "run_id": "run-1",
            "node_ref": "model-ols",
            "node_hash": "node-hash-1",
            "forest_node_key": "node-hash-1",
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "ctx-1",
            "active_head_run_id": "run-1",
            "owner_resolution": "active_head_contains_node",
        },
        changes={"covariance": {"old": "nonrobust", "new": "HC3"}},
        evidence_refs=["diagnostic:heteroskedasticity"],
        expected_effect=["standard errors may change"],
        risks=["small samples may overinflate standard errors"],
        command_id="cmd-1",
    )


def _snapshot(
    repository: JsonlSessionRepository,
    events: AgentEventStream,
    store: ProposalStore,
    proposal_id: str,
) -> tuple[bytes, tuple[dict, ...], tuple[dict, ...]]:
    proposal_path = store.proposals_dir / f"{proposal_id}.jsonl"
    return (
        proposal_path.read_bytes(),
        tuple(entry.to_dict() for entry in repository.get_branch("chain-session")),
        tuple(event.to_dict() for event in events.replay("chain-session")),
    )


def test_default_orchestrator_has_no_raw_writable_proposal_store(tmp_path: Path) -> None:
    _repository, _events, orchestrator = _world(tmp_path)

    assert orchestrator.proposal_store is None


def test_direct_create_requires_server_owned_store_before_any_write(tmp_path: Path) -> None:
    repository, events, orchestrator = _world(tmp_path)
    proposal_path = tmp_path / "workbench" / "proposals" / "proposal-direct.jsonl"
    before = tuple(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    with pytest.raises(LegacyProposalWriteBoundaryError):
        orchestrator.create_proposal(
            chain_id="chain-a",
            operation_id="model.rerun",
            target={
                "run_id": "run-1",
                "node_ref": "model-ols",
                "node_hash": "node-hash-1",
                "forest_node_key": "node-hash-1",
            },
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "ctx-1",
                "active_head_run_id": "run-1",
                "owner_resolution": "active_head_contains_node",
            },
            changes={"covariance": {"old": "nonrobust", "new": "HC3"}},
            evidence_refs=[],
            expected_effect=[],
            risks=[],
            proposal_id="proposal-direct",
        )

    assert not proposal_path.exists()
    assert tuple(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before
    assert repository.get_branch("chain-session") == []
    assert events.replay("chain-session") == []


def test_direct_revise_requires_server_owned_store_before_any_write(tmp_path: Path) -> None:
    repository, events, orchestrator = _world(tmp_path)
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(LegacyProposalWriteBoundaryError):
        orchestrator.revise_proposal(
            proposal.proposal_id,
            base_revision=proposal.revision,
            changes={"covariance": {"old": "nonrobust", "new": "HC1"}},
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_direct_decline_requires_server_owned_store_before_any_write(tmp_path: Path) -> None:
    repository, events, orchestrator = _world(tmp_path)
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(LegacyProposalWriteBoundaryError):
        orchestrator.decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="not approved",
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


@pytest.mark.parametrize("operation", ["revise", "decline"])
def test_caller_created_explicit_store_cannot_write_proposal(
    tmp_path: Path, operation: str
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store)
    repository, events, orchestrator = _world(tmp_path, proposal_store=raw_store)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    assert orchestrator.proposal_store is None

    with pytest.raises(LegacyProposalWriteBoundaryError):
        if operation == "revise":
            orchestrator.revise_proposal(
                proposal.proposal_id,
                base_revision=proposal.revision,
                changes={"covariance": {"old": "nonrobust", "new": "HC1"}},
            )
        else:
            orchestrator.decline_proposal(
                proposal.proposal_id,
                actor_type="user",
                reason="not approved",
            )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_reconstructed_store_cannot_write_proposal(tmp_path: Path) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store)
    reconstructed_store = ProposalStore(tmp_path / "workbench", create=False)
    repository, events, orchestrator = _world(tmp_path, proposal_store=reconstructed_store)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(LegacyProposalWriteBoundaryError):
        orchestrator.decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="reconstructed store",
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_cross_scope_server_capability_cannot_write_or_replay_proposal(tmp_path: Path) -> None:
    repository, events, orchestrator = _world(tmp_path)
    local_store = ProposalStore(tmp_path / "workbench")
    local_proposal = _proposal(local_store)
    other_root = tmp_path / "other-workbench"
    other_store = ProposalStore(other_root)
    _proposal(other_store, proposal_id=local_proposal.proposal_id)
    cross_scope = agent_routes._server_proposal_store(other_root)
    before_local = _snapshot(repository, events, local_store, local_proposal.proposal_id)
    before_other = (other_store.proposals_dir / f"{local_proposal.proposal_id}.jsonl").read_bytes()

    cross_scope_orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        proposal_store=cross_scope,
    )
    with pytest.raises(LegacyProposalWriteBoundaryError):
        cross_scope_orchestrator.decline_proposal(
            local_proposal.proposal_id,
            actor_type="user",
            reason="cross scope",
        )

    assert _snapshot(repository, events, local_store, local_proposal.proposal_id) == before_local
    assert (
        other_store.proposals_dir / f"{local_proposal.proposal_id}.jsonl"
    ).read_bytes() == before_other


def test_tampered_server_capability_cannot_write_or_emit_side_effects(tmp_path: Path) -> None:
    repository, events, _orchestrator = _world(tmp_path)
    store = agent_routes._server_proposal_store(tmp_path / "workbench")
    proposal = _proposal(store)
    tampered_root_store = ProposalStore(tmp_path / "tampered-workbench")
    object.__setattr__(store, "_store", tampered_root_store)
    before = _snapshot(repository, events, ProposalStore(tmp_path / "workbench"), proposal.proposal_id)

    tampered_orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        proposal_store=store,
    )
    with pytest.raises(LegacyProposalWriteBoundaryError):
        tampered_orchestrator.decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="tampered",
        )

    assert _snapshot(repository, events, ProposalStore(tmp_path / "workbench"), proposal.proposal_id) == before
    assert not (tampered_root_store.proposals_dir / f"{proposal.proposal_id}.jsonl").exists()


def test_server_capability_replay_is_stale_without_duplicate_write(tmp_path: Path) -> None:
    repository, events, _orchestrator = _world(tmp_path)
    store = agent_routes._server_proposal_store(tmp_path / "workbench")
    proposal = _proposal(store)
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        proposal_store=store,
    )

    revised = orchestrator.revise_proposal(
        proposal.proposal_id,
        base_revision=proposal.revision,
        changes={"covariance": {"old": "nonrobust", "new": "HC1"}},
    )
    before_replay = _snapshot(repository, events, store._require_admitted(), proposal.proposal_id)

    with pytest.raises(ProposalConfirmationError, match="current|revision|editable"):
        orchestrator.revise_proposal(
            proposal.proposal_id,
            base_revision=proposal.revision,
            changes={"covariance": {"old": "nonrobust", "new": "HC2"}},
        )

    assert revised.revision == 2
    assert _snapshot(repository, events, store._require_admitted(), proposal.proposal_id) == before_replay


def test_decline_route_passes_server_owned_store_into_orchestrator(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    repository.create_session("agent_main", chain_id="project", role="main")
    events = AgentEventStream(workbench_root)
    store = agent_routes._server_proposal_store(workbench_root)
    proposal = _proposal(store)
    captured: dict[str, object] = {}
    original = agent_routes.WorkbenchOrchestrator

    class SpyOrchestrator:
        def __init__(self, *args, **kwargs):
            captured["proposal_store"] = kwargs.get("proposal_store")
            self._inner = original(*args, **kwargs)

        def decline_proposal(self, *args, **kwargs):
            return self._inner.decline_proposal(*args, **kwargs)

    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: root)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (repository, events, repository.get_metadata("chain-session")),
    )
    monkeypatch.setattr(agent_routes, "_server_proposal_store", lambda _root: store)
    monkeypatch.setattr(agent_routes, "_proposal_for_session", lambda *args, **kwargs: proposal)
    monkeypatch.setattr(agent_routes, "_ensure_main_session", lambda _repository, _root: "agent_main")
    monkeypatch.setattr(agent_routes, "WorkbenchOrchestrator", SpyOrchestrator)

    response = agent_routes.decline_agent_proposal(
        "chain-session",
        proposal.proposal_id,
        str(root),
        agent_routes.AgentProposalDeclineRequest(reason="not approved"),
    )

    assert captured["proposal_store"] is store
    assert response["status"] == "declined"
