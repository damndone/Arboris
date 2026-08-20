from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import (
    LegacyProposalWriteBoundaryError,
    WorkbenchOrchestrator,
)
from workbench.agent.proposals import (
    ProposalStoreCapabilityIssuerV1,
    ProposalConfirmationError,
    ProposalStore,
    ProposalStoreCapabilityError,
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


def _proposal(store: ProposalStore | ProposalStoreCapabilityV1, *, proposal_id: str):
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
    return (
        (store.proposals_dir / f"{proposal_id}.jsonl").read_bytes(),
        tuple(entry.to_dict() for entry in repository.get_branch("chain-session")),
        tuple(event.to_dict() for event in events.replay("chain-session")),
    )


def _caller_capability(root: Path) -> ProposalStoreCapabilityV1:
    return ProposalStore._issue_server_capability(root, owner_token=object())


def test_caller_owner_token_cannot_mint_a_usable_capability(tmp_path: Path) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="caller-token")
    repository, events, orchestrator = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        caller_capability = _caller_capability(tmp_path / "workbench")
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
            proposal_store=caller_capability,
        )
        orchestrator.decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="caller-created authority",
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_direct_capability_issue_seam_cannot_write_before_route_admission(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="direct-issue")
    repository, events, _orchestrator = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        caller_capability = ProposalStoreCapabilityV1._issue(
            raw_store,
            owner_token=object(),
        )
        WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
            proposal_store=caller_capability,
        ).decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="direct issue seam",
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_caller_created_issuer_cannot_mutate_capability_directly(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="caller-issuer")
    repository, events, _orchestrator = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)
    caller_issuer = ProposalStoreCapabilityIssuerV1()

    with pytest.raises((TypeError, ProposalStoreCapabilityError)):
        ProposalStore._issue_server_capability(
            tmp_path / "workbench",
            issuer=caller_issuer,
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_imported_default_route_issuer_cannot_issue_directly(tmp_path: Path) -> None:
    for service_admission in (None, object()):
        with pytest.raises((TypeError, ProposalStoreCapabilityError)):
            ProposalStore._issue_server_capability(
                tmp_path / "workbench",
                issuer=agent_routes.DEFAULT_ROUTE_PROPOSAL_STORE_ISSUER,
                service_admission=service_admission,
            )


def test_direct_orchestrator_without_explicit_issuer_fails_closed(
    tmp_path: Path,
) -> None:
    repository, events, _orchestrator = _world(tmp_path)
    route_store = agent_routes._server_proposal_store(tmp_path / "workbench")
    proposal = _proposal(route_store, proposal_id="missing-orchestrator-issuer")
    before = _snapshot(repository, events, route_store._require_admitted(), proposal.proposal_id)

    with pytest.raises(LegacyProposalWriteBoundaryError):
        WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
            proposal_store=route_store,
        ).decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="missing explicit route issuer",
        )

    assert _snapshot(repository, events, route_store._require_admitted(), proposal.proposal_id) == before


def test_concurrent_caller_capability_misuse_has_zero_side_effects(tmp_path: Path) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="concurrent-caller")
    repository, events, _orchestrator = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    def misuse() -> str:
        try:
            capability = _caller_capability(tmp_path / "workbench")
            WorkbenchOrchestrator(
                repository,
                events,
                main_session_id="main-session",
                proposal_store=capability,
            ).decline_proposal(
                proposal.proposal_id,
                actor_type="user",
                reason="concurrent caller misuse",
            )
        except (
            TypeError,
            ProposalStoreCapabilityError,
            LegacyProposalWriteBoundaryError,
            ProposalConfirmationError,
        ):
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _item: misuse(), (1, 2)))

    assert outcomes == ("rejected", "rejected")
    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_route_owned_capability_remains_valid(tmp_path: Path) -> None:
    repository, events, _orchestrator = _world(tmp_path)
    route_store = agent_routes._server_proposal_store(tmp_path / "workbench")
    proposal = _proposal(route_store, proposal_id="route-owned")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        proposal_store=route_store,
        proposal_store_issuer=agent_routes._ROUTE_PROPOSAL_STORE_ISSUER,
    )

    decision = orchestrator.decline_proposal(
        proposal.proposal_id,
        actor_type="user",
        reason="route-owned lifecycle",
    )

    assert decision.status == "declined"
    assert route_store.latest_status(proposal.proposal_id) == "declined"
    assert len(repository.get_branch("chain-session")) == 1
    assert len(events.replay("chain-session")) == 1
