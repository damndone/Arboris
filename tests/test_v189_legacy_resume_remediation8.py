from __future__ import annotations

import copy
import os
import pickle
from pathlib import Path

import pytest

from workbench.agent import proposals as proposals_module
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import (
    LegacyProposalWriteBoundaryError,
    WorkbenchOrchestrator,
)
from workbench.agent.proposals import (
    ProposalStore,
    ProposalStoreCapabilityError,
    ProposalStoreCapabilityIssuerV1,
    ProposalStoreCapabilityV1,
    _ProposalStoreServerAuthorityV1,
)
from workbench.agent.session import JsonlSessionRepository
from workbench.http import agent_routes


def _world(tmp_path: Path):
    root = tmp_path / "workbench"
    repository = JsonlSessionRepository(root)
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    events = AgentEventStream(root)
    return repository, events


def _proposal(store: ProposalStore | ProposalStoreCapabilityV1, *, proposal_id: str):
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


def _decline(
    repository,
    events,
    capability: ProposalStoreCapabilityV1,
    issuer: ProposalStoreCapabilityIssuerV1,
    proposal_id: str,
):
    return WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        proposal_store=capability,
        proposal_store_issuer=issuer,
    ).decline_proposal(
        proposal_id,
        actor_type="user",
        reason="authority forgery probe",
    )


def test_direct_authority_constructor_cannot_reach_real_proposal_side_effects(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="direct-authority")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        authority = _ProposalStoreServerAuthorityV1()
        issuer, service_entry = authority.issue()
        capability = ProposalStore._issue_server_capability(
            raw_store.root,
            issuer=issuer,
            service_admission=service_entry,
        )
        _decline(repository, events, capability, issuer, proposal.proposal_id)

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_object_new_authority_with_self_consistent_fields_cannot_issue(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="object-new-authority")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)
    forged_authority = object.__new__(_ProposalStoreServerAuthorityV1)
    forged_authority._authority_secret = object()
    forged_authority._process_id = os.getpid()
    forged_authority._generation = proposals_module._PROPOSAL_STORE_PROCESS_GENERATION

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        issuer, service_entry = forged_authority.issue()
        capability = ProposalStore._issue_server_capability(
            raw_store.root,
            issuer=issuer,
            service_admission=service_entry,
        )
        _decline(repository, events, capability, issuer, proposal.proposal_id)

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_copied_authority_cannot_issue_before_side_effects(tmp_path: Path) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="copied-authority")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        copied_authority = copy.copy(proposals_module._PROPOSAL_STORE_SERVER_AUTHORITY)
        issuer, service_entry = copied_authority.issue()
        capability = ProposalStore._issue_server_capability(
            raw_store.root,
            issuer=issuer,
            service_admission=service_entry,
        )
        _decline(repository, events, capability, issuer, proposal.proposal_id)

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_live_authority_copy_and_pickle_are_rejected_before_side_effects(
    tmp_path: Path,
) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="serialized-authority")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)
    authority = proposals_module._PROPOSAL_STORE_SERVER_AUTHORITY

    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(authority)

    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(authority)

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_forged_entry_nonce_is_rejected_before_side_effects(tmp_path: Path) -> None:
    raw_store = ProposalStore(tmp_path / "workbench")
    proposal = _proposal(raw_store, proposal_id="forged-entry-nonce")
    repository, events = _world(tmp_path)
    before = _snapshot(repository, events, raw_store, proposal.proposal_id)
    issuer, service_entry = proposals_module._issue_server_owned_proposal_store_authority()
    service_entry._entry_nonce = "forged-entry-nonce"

    with pytest.raises(
        (TypeError, ProposalStoreCapabilityError, LegacyProposalWriteBoundaryError)
    ):
        capability = ProposalStore._issue_server_capability(
            raw_store.root,
            issuer=issuer,
            service_admission=service_entry,
        )
        _decline(repository, events, capability, issuer, proposal.proposal_id)

    assert _snapshot(repository, events, raw_store, proposal.proposal_id) == before


def test_route_owned_authority_remains_a_positive_path(tmp_path: Path) -> None:
    repository, events = _world(tmp_path)
    route_store = agent_routes._server_proposal_store(tmp_path / "workbench")
    proposal = _proposal(route_store, proposal_id="route-positive")

    decision = _decline(
        repository,
        events,
        route_store,
        agent_routes._ROUTE_PROPOSAL_STORE_ISSUER,
        proposal.proposal_id,
    )

    assert decision.status == "declined"
    assert route_store.latest_status(proposal.proposal_id) == "declined"
    assert len(repository.get_branch("chain-session")) == 1
    assert len(events.replay("chain-session")) == 1
