from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_agent_proposal_operations import make_orchestrator, proposal_kwargs
from tests.test_v189_agent_notebook_cutover import _cutover, _intent
from tests.test_v189_legacy_route_authority import _server_receipt
from workbench.agent.orchestrator import CutoverCompilerError, WorkbenchOrchestrator
from workbench.agent.proposals import ProposalConfirmationError, ProposalStore
from workbench.api_errors import WorkbenchAPIError
from workbench.http import agent_routes


def _server_proposal(tmp_path, compiler=None):
    store = (
        compiler.server_proposal_store(tmp_path / "server-proposals")
        if compiler is not None
        else ProposalStore(tmp_path / "server-proposals")
    )
    proposal = store.create(
        session_id="session:1",
        chain_id="chain:1",
        operation_id="model.rerun",
        target={"run_id": "run:1"},
        preconditions={},
        changes={},
        evidence_refs=(),
        expected_effect=("rerun",),
        risks=(),
    )
    return store, proposal


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    (
        ("proposal_id", "proposal:forged"),
        ("revision", 99),
        ("fingerprint", "f" * 64),
    ),
)
def test_compile_for_proposal_rejects_caller_created_forged_identity(
    tmp_path, field_name, forged_value
) -> None:
    _store, persisted = _server_proposal(tmp_path)
    _catalog, compiler = _cutover()
    forged = replace(persisted, **{field_name: forged_value})

    with pytest.raises(CutoverCompilerError, match="ProposalStore|server-owned"):
        compiler.compile_for_proposal(
            _intent(),
            proposal=forged,
            entrypoint="agent",
        )


def test_bind_proposal_rejects_caller_revision_instead_of_promoting_it(
    tmp_path,
) -> None:
    _store, persisted = _server_proposal(tmp_path)
    _catalog, compiler = _cutover()
    preview = compiler.compile(_intent(), entrypoint="agent")
    forged = replace(persisted, fingerprint="caller-fingerprint")

    with pytest.raises(CutoverCompilerError, match="ProposalStore|server-owned"):
        compiler.bind_proposal(preview.compilation_record_id, forged)


def test_compile_for_persisted_proposal_rejects_forged_server_id(tmp_path) -> None:
    _catalog, compiler = _cutover()
    proposal_store, _proposal = _server_proposal(tmp_path, compiler)

    with pytest.raises(CutoverCompilerError, match="SERVER_PROPOSAL_UNKNOWN"):
        compiler.compile_for_persisted_proposal(
            _intent(),
            proposal_store=proposal_store,
            proposal_id="proposal:forged",
            entrypoint="agent",
        )


def test_compile_for_persisted_proposal_rejects_persisted_fingerprint_tamper(
    tmp_path,
) -> None:
    _catalog, compiler = _cutover()
    proposal_store, proposal = _server_proposal(tmp_path, compiler)
    proposal_path = (
        tmp_path / "server-proposals" / "proposals" / f"{proposal.proposal_id}.jsonl"
    )
    records = [json.loads(line) for line in proposal_path.read_text(encoding="utf-8").splitlines()]
    records[-1]["fingerprint"] = "f" * 64
    proposal_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    with pytest.raises(CutoverCompilerError, match="SERVER_PROPOSAL_INTEGRITY"):
        compiler.compile_for_persisted_proposal(
            _intent(),
            proposal_store=proposal_store,
            proposal_id=proposal.proposal_id,
            entrypoint="agent",
        )


def test_confirmation_without_real_server_proposal_fails_closed() -> None:
    _catalog, compiler = _cutover()
    preview = compiler.compile(_intent(), entrypoint="agent")

    with pytest.raises(CutoverCompilerError, match="proposal"):
        compiler.confirm(preview.compilation_record_id)


def test_compile_for_persisted_proposal_reloads_latest_revision_before_binding(
    tmp_path, monkeypatch
) -> None:
    _catalog, compiler = _cutover()
    preview = compiler.compile(_intent(), entrypoint="agent")
    record = compiler.record(preview.compilation_record_id)
    proposal_store = compiler.server_proposal_store(tmp_path / "server-proposals")
    proposal = proposal_store.create(
        session_id=record.session_ref,
        chain_id="chain:1",
        operation_id="model.rerun",
        target={"run_id": "run:1"},
        preconditions={
            "server_compilation": {
                "compilation_record_id": record.record_id,
                "confirmation_id": "confirmation:pending",
                "actor_ref": record.principal_ref,
                "session_ref": record.session_ref,
                "project_ref": record.project_ref,
                "semantic_plan_hash": record.semantic_plan_hash,
                "target": {"run_id": "run:1"},
                "chain_id": "chain:1",
                "operation_id": "model.rerun",
            }
        },
        changes={},
        evidence_refs=(),
        expected_effect=("rerun",),
        risks=(),
    )
    proposal_store.revise(
        proposal.proposal_id,
        base_revision=proposal.revision,
        changes={"rebound": True},
    )
    compiler.bind_persisted_proposal(
        preview.compilation_record_id,
        proposal_store,
        proposal.proposal_id,
    )
    receipt = compiler.confirm(preview.compilation_record_id)
    latest = proposal_store.latest_revision(proposal.proposal_id)

    assert latest.revision == 2
    assert receipt.proposal_revision == latest.revision
    assert receipt.proposal_fingerprint == latest.fingerprint


def test_legacy_semantic_hash_is_required_before_authority_record_or_execute(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-semantic-required"
    semantic_plan_hash = "a" * 64
    proposal = SimpleNamespace(
        proposal_id="proposal-a",
        revision=1,
        fingerprint="fingerprint-a",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-a",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-a",
                "operation_id": "model.rerun",
                # Deliberately omitted: semantic_plan_hash.
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
                "data_snapshot_digest": "d" * 64,
            }
        },
    )
    authority_calls: list[tuple[str, str]] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []

    class Compiler:
        def record(self, compilation_record_id):
            record_calls.append(compilation_record_id)
            return SimpleNamespace(
                record_id=record_id,
                semantic_plan_hash=semantic_plan_hash,
                principal_ref=actor_ref,
                session_ref=session_id,
                project_ref=project_ref,
            )

        def execute(self, compilation_record_id, *_args, **_kwargs):
            execute_calls.append(compilation_record_id)
            return SimpleNamespace(
                to_dict=lambda: {"operation_id": "model.rerun", "status": "completed"}
            )

    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.retain_confirmation(project_ref, session_id, record_id, _server_receipt(
        confirmation_id="confirmation-a",
        compilation_record_id=record_id,
        proposal_id="proposal-a",
        proposal_revision=1,
        proposal_fingerprint="fingerprint-a",
        semantic_plan_hash=semantic_plan_hash,
        actor_ref=actor_ref,
        session_ref=session_id,
        project_ref=project_ref,
    ))
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: (
            authority_calls.append((project, session)) or Compiler()
        ),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id=proposal.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert authority_calls == []
    assert record_calls == []
    assert execute_calls == []
    assert store.legacy_proposal_bindings == {}


def test_legacy_semantic_hash_mismatch_fails_before_authority_record_or_execute(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-semantic-mismatch"
    proposal_semantic_hash = "b" * 64
    receipt_semantic_hash = "a" * 64
    proposal = SimpleNamespace(
        proposal_id="proposal-a",
        revision=1,
        fingerprint="fingerprint-a",
        session_id=session_id,
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-a",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-a",
                "operation_id": "model.rerun",
                "semantic_plan_hash": proposal_semantic_hash,
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
            }
        },
    )
    authority_calls: list[tuple[str, str]] = []

    class Compiler:
        def record(self, _record_id):
            pytest.fail("record must not be reached after semantic mismatch")

        def execute(self, *_args, **_kwargs):
            pytest.fail("execute must not be reached after semantic mismatch")

    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.retain_confirmation(
        project_ref,
        session_id,
        record_id,
        _server_receipt(
            confirmation_id="confirmation-a",
            compilation_record_id=record_id,
            proposal_id="proposal-a",
            proposal_revision=1,
            proposal_fingerprint="fingerprint-a",
            semantic_plan_hash=receipt_semantic_hash,
            actor_ref=actor_ref,
            session_ref=session_id,
            project_ref=project_ref,
        ),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: (
            authority_calls.append((project, session)) or Compiler()
        ),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id=proposal.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert authority_calls == []
    assert store.legacy_proposal_bindings == {}


def test_legacy_route_rejects_caller_path_id_before_authority_or_claim(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    proposal = SimpleNamespace(
        proposal_id="proposal-server",
        revision=1,
        fingerprint="fingerprint-server",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": "record-a",
                "confirmation_id": "confirmation-a",
                "semantic_plan_hash": "a" * 64,
            }
        },
    )
    authority_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: authority_calls.append((project, session)),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id="proposal-caller",
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert authority_calls == []


def test_retained_receipt_serialization_tamper_fails_before_authority(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-serialization-tamper"
    semantic_plan_hash = "a" * 64
    proposal = SimpleNamespace(
        proposal_id="proposal-b",
        revision=1,
        fingerprint="fingerprint-b",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-b",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-b",
                "operation_id": "model.rerun",
                "semantic_plan_hash": semantic_plan_hash,
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
                "data_snapshot_digest": "d" * 64,
            }
        },
    )
    receipt_a = _server_receipt(
        confirmation_id="confirmation-a",
        compilation_record_id=record_id,
        proposal_id="proposal-a",
        proposal_revision=1,
        proposal_fingerprint="fingerprint-a",
        semantic_plan_hash=semantic_plan_hash,
        actor_ref=actor_ref,
        session_ref=session_id,
        project_ref=project_ref,
    )
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.retain_confirmation(project_ref, session_id, record_id, receipt_a)
    # Keep the digest but mutate the serialized proposal identity. Only the
    # server-retained canonical snapshot can distinguish this from a valid
    # receipt for proposal B.
    store.confirmations[(project_ref, session_id, record_id)] = replace(
        receipt_a,
        proposal_id="proposal-b",
        proposal_fingerprint="fingerprint-b",
    )
    authority_calls: list[tuple[str, str]] = []

    class Compiler:
        def record(self, _record_id):
            pytest.fail("record must not be reached after receipt tamper")

        def execute(self, *_args, **_kwargs):
            pytest.fail("execute must not be reached after receipt tamper")

    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: (
            authority_calls.append((project, session)) or Compiler()
        ),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id=proposal.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert authority_calls == []
    assert store.legacy_proposal_bindings == {}


def test_receipt_proposal_identity_mismatch_fails_before_authority_or_claim(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-proposal-identity-mismatch"
    semantic_plan_hash = "a" * 64
    proposal = SimpleNamespace(
        proposal_id="proposal-b",
        revision=1,
        fingerprint="fingerprint-b",
        session_id=session_id,
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-b",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-b",
                "operation_id": "model.rerun",
                "semantic_plan_hash": semantic_plan_hash,
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
            }
        },
    )
    receipt_a = _server_receipt(
        confirmation_id="confirmation-a",
        compilation_record_id=record_id,
        proposal_id="proposal-a",
        proposal_revision=1,
        proposal_fingerprint="fingerprint-a",
        semantic_plan_hash=semantic_plan_hash,
        actor_ref=actor_ref,
        session_ref=session_id,
        project_ref=project_ref,
    )
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.retain_confirmation(project_ref, session_id, record_id, receipt_a)
    authority_calls: list[tuple[str, str]] = []

    class Compiler:
        def record(self, _record_id):
            pytest.fail("record must not be reached after receipt proposal mismatch")

        def execute(self, *_args, **_kwargs):
            pytest.fail("execute must not be reached after receipt proposal mismatch")

    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: (
            authority_calls.append((project, session)) or Compiler()
        ),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id=proposal.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert authority_calls == []
    assert store.legacy_proposal_bindings == {}


def test_direct_workbench_confirmation_fails_before_legacy_store_writes(
    tmp_path,
) -> None:
    bootstrap = make_orchestrator(tmp_path)
    proposal_store = agent_routes._server_proposal_store(tmp_path / "workbench")
    orchestrator = WorkbenchOrchestrator(
        bootstrap.repository,
        bootstrap.events,
        main_session_id="main-session",
        proposal_store=proposal_store,
    )
    chain_session_id, chain_agent = bootstrap._chains["chain-a"]
    orchestrator.register_chain("chain-a", chain_session_id, chain_agent)
    proposal = orchestrator.create_proposal(**proposal_kwargs())
    proposal_path = proposal_store.root / "proposals" / f"{proposal.proposal_id}.jsonl"
    before_proposal = proposal_path.read_bytes()

    with pytest.raises(ProposalConfirmationError) as error:
        asyncio.run(
            asyncio.to_thread(
                orchestrator.confirm_proposal,
                proposal.proposal_id,
                revision=proposal.revision,
                fingerprint=proposal.fingerprint,
                actor_type="user",
                current_context_fingerprint="ctx-1",
                current_active_head_run_id="run-1",
            )
        )

    assert getattr(error.value, "code", None) == "AGENT_NOTEBOOK_CUTOVER_REQUIRED"
    assert proposal_path.read_bytes() == before_proposal
    assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "pending"
    assert orchestrator.operation_store.list_records() == []
