from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_v189_agent_notebook_cutover import _cutover, _intent
from workbench.agent.orchestrator import CutoverCompilerError
from workbench.agent.proposals import ProposalRevision, ProposalStore
from workbench.api_errors import WorkbenchAPIError
from workbench.http import agent_routes


def _complete_proposal(tmp_path, compiler):
    preview = compiler.compile(_intent(), entrypoint="agent")
    record = compiler.record(preview.compilation_record_id)
    target = {"run_id": "run:1"}
    store = ProposalStore(tmp_path)
    proposal = store.create(
        session_id=record.session_ref,
        chain_id="chain:1",
        operation_id="model.rerun",
        target=target,
        preconditions={
            "server_compilation": {
                "compilation_record_id": record.record_id,
                "confirmation_id": "confirmation:pending",
                "actor_ref": record.principal_ref,
                "session_ref": record.session_ref,
                "project_ref": record.project_ref,
                "semantic_plan_hash": record.semantic_plan_hash,
                "target": target,
                "chain_id": "chain:1",
                "operation_id": "model.rerun",
            }
        },
        changes={},
        evidence_refs=(),
        expected_effect=("rerun",),
        risks=(),
    )
    return store, proposal, record


def _canonical_route_fixture(tmp_path):
    """Create one real compiler/store/route receipt lifecycle for direct probes."""

    _catalog, compiler = _cutover()
    session_id = "session:route-4"
    actor_ref = "principal:agent:route-4"
    project_ref = "project:remediation-4"
    intent = replace(
        _intent(actor=actor_ref, session=session_id),
        project_ref=project_ref,
    )
    preview = compiler.compile(intent, entrypoint="agent")
    record = compiler.record(preview.compilation_record_id)
    target = {"run_id": "run:route-4"}
    compiler_store = compiler.server_proposal_store(tmp_path)
    proposal = compiler_store.create(
        session_id=session_id,
        chain_id="chain:route-4",
        operation_id="model.rerun",
        target=target,
        preconditions={
            "server_compilation": {
                "compilation_record_id": record.record_id,
                "confirmation_id": "confirmation:route-4",
                "actor_ref": record.principal_ref,
                "session_ref": record.session_ref,
                "project_ref": record.project_ref,
                "semantic_plan_hash": record.semantic_plan_hash,
                "target": target,
                "chain_id": "chain:route-4",
                "operation_id": "model.rerun",
            }
        },
        changes={},
        evidence_refs=(),
        expected_effect=("rerun",),
        risks=(),
    )
    compiler.bind_persisted_proposal(record.record_id, compiler_store, proposal.proposal_id)
    receipt = compiler.confirm(record.record_id)
    assert receipt.confirmation_id == proposal.preconditions["server_compilation"]["confirmation_id"]
    assert receipt.confirmation_id != "confirmation:route-4"

    route_store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    route_store.authorities[(project_ref, session_id)] = compiler
    route_store.retain_confirmation(
        project_ref,
        session_id,
        record.record_id,
        receipt,
        authority=compiler,
    )
    route_capability = agent_routes._server_proposal_store(tmp_path)
    reference = agent_routes._proposal_for_session(
        route_capability,
        proposal_id=proposal.proposal_id,
        session_id=session_id,
        chain_id="chain:route-4",
        actor_ref=actor_ref,
        project_ref=project_ref,
    )
    return {
        "compiler": compiler,
        "store": route_store,
        "reference": reference,
        "proposal": proposal,
        "receipt": receipt,
        "record": record,
        "project_ref": project_ref,
        "session_id": session_id,
        "actor_ref": actor_ref,
    }


def test_caller_created_complete_store_is_not_compiler_admission(tmp_path, monkeypatch):
    _catalog, compiler = _cutover()
    store, proposal, record = _complete_proposal(tmp_path, compiler)
    record_calls: list[str] = []
    monkeypatch.setattr(
        compiler,
        "record",
        lambda record_id: record_calls.append(record_id) or record,
    )

    with pytest.raises(CutoverCompilerError) as error:
        compiler.bind_persisted_proposal(record.record_id, store, proposal.proposal_id)

    assert error.value.code == "SERVER_PROPOSAL_STORE_CAPABILITY_REQUIRED"
    assert record_calls == []
    assert compiler._proposal_bindings == {}


def test_reconstructed_store_over_complete_file_is_not_compiler_admission(tmp_path):
    _catalog, compiler = _cutover()
    original, proposal, record = _complete_proposal(tmp_path, compiler)
    assert original.latest_revision(proposal.proposal_id) == proposal
    reconstructed = ProposalStore(tmp_path, create=False)

    with pytest.raises(CutoverCompilerError) as error:
        compiler.bind_persisted_proposal(record.record_id, reconstructed, proposal.proposal_id)

    assert error.value.code == "SERVER_PROPOSAL_STORE_CAPABILITY_REQUIRED"
    assert compiler._proposal_bindings == {}


def test_legacy_boundary_rejects_synthetic_proposal_before_any_side_effect(
    tmp_path, monkeypatch
):
    proposal = SimpleNamespace(
        proposal_id="proposal-a",
        revision=1,
        fingerprint="fingerprint-a",
        session_id="session-1",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": "record-a",
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-a",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-a",
                "operation_id": "model.rerun",
                "semantic_plan_hash": "a" * 64,
                "actor_ref": "actor:agent:session-1",
                "session_ref": "session-1",
                "project_ref": f"project:{tmp_path.resolve()}",
            }
        },
    )
    binding_calls: list[str] = []
    scope_calls: list[str] = []
    authority_calls: list[str] = []
    claim_calls: list[str] = []
    original_binding = agent_routes._legacy_cutover_binding
    monkeypatch.setattr(
        agent_routes,
        "_legacy_cutover_binding",
        lambda value: binding_calls.append(type(value).__name__) or original_binding(value),
    )
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: scope_calls.append("scope")
        or ("actor:agent:session-1", "session-1", f"project:{tmp_path.resolve()}"),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda *_args, **_kwargs: authority_calls.append("authority"),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_store",
        lambda **_kwargs: claim_calls.append("store")
        or agent_routes.AgentNotebookCutoverAuthorityStoreV1(),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id=proposal.proposal_id,
            root=tmp_path,
            session_id="session-1",
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert binding_calls == []
    assert scope_calls == []
    assert authority_calls == []
    assert claim_calls == []


def test_legacy_boundary_rejects_reconstructed_revision_before_any_side_effect(
    tmp_path, monkeypatch
):
    root = tmp_path
    session_id = "session-1"
    project_ref = f"project:{root.resolve()}"
    target = {"run_id": "run:1"}
    store = ProposalStore(root)
    persisted = store.create(
        session_id=session_id,
        chain_id="chain-1",
        operation_id="model.rerun",
        target=target,
        preconditions={
            "server_compilation": {
                "compilation_record_id": "record-a",
                "confirmation_id": "confirmation-a",
                "actor_ref": f"actor:agent:{session_id}",
                "session_ref": session_id,
                "project_ref": project_ref,
                "semantic_plan_hash": "a" * 64,
                "target": target,
                "chain_id": "chain-1",
                "operation_id": "model.rerun",
            }
        },
        changes={},
        evidence_refs=(),
        expected_effect=("rerun",),
        risks=(),
    )
    reconstructed = ProposalRevision.from_dict(persisted.to_dict())
    assert reconstructed is not persisted
    binding_calls: list[str] = []
    original_binding = agent_routes._legacy_cutover_binding
    monkeypatch.setattr(
        agent_routes,
        "_legacy_cutover_binding",
        lambda value: binding_calls.append(type(value).__name__) or original_binding(value),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda *_args, **_kwargs: pytest.fail("authority lookup must not run"),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            reconstructed,
            proposal_id=persisted.proposal_id,
            root=root,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert binding_calls == []


def test_caller_created_receipt_cannot_enter_the_bound_authority_store(tmp_path):
    fixture = _canonical_route_fixture(tmp_path)
    forged = replace(fixture["receipt"], proposal_id="proposal:forged")
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    key = (fixture["project_ref"], fixture["session_id"])
    store.authorities[key] = fixture["compiler"]

    with pytest.raises(WorkbenchAPIError) as error:
        store.retain_confirmation(
            fixture["project_ref"],
            fixture["session_id"],
            fixture["record"].record_id,
            forged,
            authority=fixture["compiler"],
        )

    assert error.value.code == "AGENT_CONFIRMATION_AUTHORITY_REQUIRED"
    assert store.confirmations == {}
    assert store.confirmation_digests == {}


def test_real_route_reference_succeeds_once_then_replay_fails_closed(
    tmp_path, monkeypatch
):
    fixture = _canonical_route_fixture(tmp_path)
    compiler = fixture["compiler"]
    record_id = fixture["record"].record_id
    authority_calls: list[tuple[str, str]] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []
    original_record = compiler.record
    original_execute = compiler.execute
    monkeypatch.setattr(
        compiler,
        "record",
        lambda compilation_record_id: record_calls.append(compilation_record_id)
        or original_record(compilation_record_id),
    )
    monkeypatch.setattr(
        compiler,
        "execute",
        lambda compilation_record_id, confirmation, **kwargs: execute_calls.append(
            compilation_record_id
        )
        or original_execute(compilation_record_id, confirmation, **kwargs),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: fixture["store"])
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (
            fixture["actor_ref"],
            fixture["session_id"],
            fixture["project_ref"],
        ),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project_ref, session_ref, **_kwargs: authority_calls.append(
            (project_ref, session_ref)
        )
        or compiler,
    )

    result = agent_routes._execute_legacy_agent_proposal_via_server_boundary(
        fixture["reference"],
        proposal_id=fixture["proposal"].proposal_id,
        root=tmp_path,
        session_id=fixture["session_id"],
        request=None,
    )
    assert result["status"] == "completed"
    assert authority_calls == [(fixture["project_ref"], fixture["session_id"])]
    assert record_calls == [record_id, record_id]
    assert execute_calls == [record_id]

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            fixture["reference"],
            proposal_id=fixture["proposal"].proposal_id,
            root=tmp_path,
            session_id=fixture["session_id"],
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_PROPOSAL_BINDING_REPLAY"
    assert authority_calls == [(fixture["project_ref"], fixture["session_id"])]
    assert record_calls == [record_id, record_id]
    assert execute_calls == [record_id]


def test_real_route_rejects_receipt_serialization_tamper_before_authority(
    tmp_path, monkeypatch
):
    fixture = _canonical_route_fixture(tmp_path)
    key = (fixture["project_ref"], fixture["session_id"], fixture["record"].record_id)
    fixture["store"].confirmations[key] = replace(
        fixture["receipt"],
        confirmation_digest="d" * 64,
    )
    authority_calls: list[str] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda *_args, **_kwargs: authority_calls.append("authority"),
    )
    monkeypatch.setattr(
        fixture["compiler"],
        "record",
        lambda record_id: record_calls.append(record_id),
    )
    monkeypatch.setattr(
        fixture["compiler"],
        "execute",
        lambda record_id, *_args, **_kwargs: execute_calls.append(record_id),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: fixture["store"])
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (
            fixture["actor_ref"],
            fixture["session_id"],
            fixture["project_ref"],
        ),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            fixture["reference"],
            proposal_id=fixture["proposal"].proposal_id,
            root=tmp_path,
            session_id=fixture["session_id"],
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_BINDING_MISMATCH"
    assert authority_calls == []
    assert record_calls == []
    assert execute_calls == []
    assert fixture["store"].legacy_proposal_bindings == {}


def test_real_route_rejects_persisted_target_tamper_before_claim_or_authority(
    tmp_path, monkeypatch
):
    fixture = _canonical_route_fixture(tmp_path)
    proposal_path = tmp_path / "proposals" / f"{fixture['proposal'].proposal_id}.jsonl"
    records = [
        json.loads(line)
        for line in proposal_path.read_text(encoding="utf-8").splitlines()
    ]
    records[-1]["target"] = {"run_id": "run:foreign"}
    proposal_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    authority_calls: list[str] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda *_args, **_kwargs: authority_calls.append("authority"),
    )
    monkeypatch.setattr(
        fixture["compiler"],
        "record",
        lambda record_id: record_calls.append(record_id),
    )
    monkeypatch.setattr(
        fixture["compiler"],
        "execute",
        lambda record_id, *_args, **_kwargs: execute_calls.append(record_id),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: fixture["store"])
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (
            fixture["actor_ref"],
            fixture["session_id"],
            fixture["project_ref"],
        ),
    )

    with pytest.raises(WorkbenchAPIError, match="integrity|fingerprint|proposal"):
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            fixture["reference"],
            proposal_id=fixture["proposal"].proposal_id,
            root=tmp_path,
            session_id=fixture["session_id"],
            request=None,
        )

    assert authority_calls == []
    assert record_calls == []
    assert execute_calls == []
    assert fixture["store"].legacy_proposal_bindings == {}
