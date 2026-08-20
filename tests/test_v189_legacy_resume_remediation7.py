from __future__ import annotations

from pathlib import Path

import pytest

from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import (
    LegacyProposalWriteBoundaryError,
    WorkbenchOrchestrator,
)
from workbench.agent.proposals import (
    ProposalStore,
    ProposalStoreCapabilityError,
    ProposalStoreCapabilityIssuerV1,
)
from workbench.agent import proposals as proposals_module
from workbench.agent.session import JsonlSessionRepository
from workbench.http import agent_routes


def _world(tmp_path: Path):
    root = tmp_path / "workbench"
    repository = JsonlSessionRepository(root)
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    events = AgentEventStream(root)
    return repository, events


def _proposal(store: ProposalStore, *, proposal_id: str) -> object:
    return store.create(
        proposal_id=proposal_id,
        session_id="chain-session",
        chain_id="chain-a",
        operation_id="model.rerun",
        target={"run_id": "run-1", "node_ref": "model-ols"},
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


def _snapshot(repository, events, store: ProposalStore, proposal_id: str):
    return (
        (store.proposals_dir / f"{proposal_id}.jsonl").read_bytes(),
        tuple(entry.to_dict() for entry in repository.get_branch("chain-session")),
        tuple(event.to_dict() for event in events.replay("chain-session")),
    )


def test_caller_created_issuer_cannot_self_register_and_mint_before_side_effects(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="caller-self-registration")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)
    caller_issuer = ProposalStoreCapabilityIssuerV1()

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        service_entry = caller_issuer._register_service_admission()
        caller_issuer._grant_mutation_admission()
        caller_capability = ProposalStore._issue_server_capability(
            tmp_path / "workbench",
            issuer=caller_issuer,
            service_admission=service_entry,
        )
        WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
            proposal_store=caller_capability,
            proposal_store_issuer=caller_issuer,
        ).decline_proposal(
            proposal.proposal_id,
            actor_type="user",
            reason="caller self-registration",
        )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_imported_default_route_issuer_cannot_be_directly_registered_then_minted(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="default-self-registration")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)
    issuer = agent_routes.DEFAULT_ROUTE_PROPOSAL_STORE_ISSUER
    original_mutation_admission = issuer._mutation_admission
    with proposals_module._PROPOSAL_STORE_CAPABILITY_LOCK:
        original_registry_admission = proposals_module._PROPOSAL_STORE_ISSUER_ADMISSIONS[
            id(issuer)
        ]

    try:
        with pytest.raises(
            (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
        ):
            service_entry = issuer._register_service_admission()
            issuer._grant_mutation_admission()
            capability = ProposalStore._issue_server_capability(
                tmp_path / "workbench",
                issuer=issuer,
                service_admission=service_entry,
            )
            WorkbenchOrchestrator(
                repository,
                events,
                main_session_id="main-session",
                proposal_store=capability,
                proposal_store_issuer=issuer,
            ).decline_proposal(
                proposal.proposal_id,
                actor_type="user",
                reason="default issuer direct registration",
            )
    finally:
        issuer._mutation_admission = original_mutation_admission
        with proposals_module._PROPOSAL_STORE_CAPABILITY_LOCK:
            proposals_module._PROPOSAL_STORE_ISSUER_ADMISSIONS[id(issuer)] = (
                original_registry_admission
            )

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before
