from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_v189_agent_notebook_cutover import _cutover, _intent
from tests.test_v189_legacy_route_authority import _server_receipt
from workbench.agent.orchestrator import CutoverCompilerError
from workbench.agent.proposals import ProposalStore
from workbench.api_errors import WorkbenchAPIError
from workbench.http import agent_routes


def _proposal_store(
    tmp_path,
    *,
    preconditions: dict[str, object],
    compiler=None,
    target: dict[str, object] | None = None,
    chain_id: str = "chain:1",
    operation_id: str = "model.rerun",
    session_id: str = "session:1",
    store_root=None,
):
    store_root = store_root or (tmp_path / "server-proposals")
    store = (
        compiler.server_proposal_store(store_root)
        if compiler is not None
        else ProposalStore(store_root)
    )
    proposal = store.create(
        session_id=session_id,
        chain_id=chain_id,
        operation_id=operation_id,
        target=target or {"run_id": "run:1"},
        preconditions=preconditions,
        changes={},
        evidence_refs=(),
        expected_effect=("rerun",),
        risks=(),
    )
    return store, proposal


def _record_backed_proposal(tmp_path):
    _catalog, compiler = _cutover()
    preview = compiler.compile(_intent(), entrypoint="agent")
    record = compiler.record(preview.compilation_record_id)
    target = {"run_id": "run:1"}
    server_compilation = {
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
    store, proposal = _proposal_store(
        tmp_path,
        preconditions={"server_compilation": server_compilation},
        compiler=compiler,
        target=target,
        session_id=record.session_ref,
    )
    return compiler, record, store, proposal, server_compilation


def test_compile_rejects_generic_proposal_without_server_compilation_before_binding(
    tmp_path, monkeypatch
) -> None:
    _catalog, compiler = _cutover()
    store, proposal = _proposal_store(tmp_path, preconditions={}, compiler=compiler)
    compile_calls: list[str] = []
    monkeypatch.setattr(
        compiler,
        "compile",
        lambda *_args, **_kwargs: compile_calls.append("compile"),
    )

    with pytest.raises(CutoverCompilerError) as error:
        compiler.compile_for_persisted_proposal(
            _intent(),
            proposal_store=store,
            proposal_id=proposal.proposal_id,
            entrypoint="agent",
        )

    assert error.value.code == "SERVER_PROPOSAL_COMPILATION_REQUIRED"
    assert compile_calls == []
    assert compiler._proposal_bindings == {}


@pytest.mark.parametrize("missing_field", [
    "actor_ref",
    "session_ref",
    "project_ref",
    "semantic_plan_hash",
    "target",
    "chain_id",
    "operation_id",
    "compilation_record_id",
])
def test_bind_rejects_incomplete_server_compilation_fields_before_binding(
    tmp_path, missing_field, monkeypatch
) -> None:
    compiler, record, _store, _proposal, server_compilation = _record_backed_proposal(tmp_path)
    record_calls: list[str] = []
    monkeypatch.setattr(
        compiler,
        "record",
        lambda record_id: record_calls.append(record_id)
        or pytest.fail("compiler.record must not run for incomplete server_compilation"),
    )
    incomplete = dict(server_compilation)
    incomplete.pop(missing_field)
    store, proposal = _proposal_store(
        tmp_path / f"missing-{missing_field}",
        preconditions={"server_compilation": incomplete},
        target={"run_id": "run:1"},
        session_id=record.session_ref,
        compiler=compiler,
    )

    with pytest.raises(CutoverCompilerError) as error:
        compiler.bind_persisted_proposal(record.record_id, store, proposal.proposal_id)

    assert error.value.code == "SERVER_PROPOSAL_COMPILATION_REQUIRED"
    assert record_calls == []
    assert compiler._proposal_bindings == {}


def test_bind_rejects_target_chain_operation_cross_scope_before_binding(
    tmp_path, monkeypatch
) -> None:
    compiler, record, _store, _proposal, server_compilation = _record_backed_proposal(tmp_path)
    record_calls: list[str] = []
    monkeypatch.setattr(
        compiler,
        "record",
        lambda record_id: record_calls.append(record_id)
        or pytest.fail("compiler.record must not run for cross-scope server_compilation"),
    )
    forged = {
        **server_compilation,
        "target": {"run_id": "run:foreign"},
        "chain_id": "chain:foreign",
        "operation_id": "graph.fork",
    }
    store, proposal = _proposal_store(
        tmp_path / "cross-scope",
        preconditions={"server_compilation": forged},
        target={"run_id": "run:1"},
        chain_id="chain:1",
        operation_id="model.rerun",
        session_id=record.session_ref,
        compiler=compiler,
    )

    with pytest.raises(CutoverCompilerError) as error:
        compiler.bind_persisted_proposal(record.record_id, store, proposal.proposal_id)

    assert error.value.code == "PROPOSAL_SCOPE_MISMATCH"
    assert record_calls == []
    assert compiler._proposal_bindings == {}


def test_route_rejects_persisted_target_tamper_with_original_fingerprint_before_execute(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    target = {"run_id": "run:1"}
    project_ref = f"project:{tmp_path.resolve()}"
    preconditions = {
        "server_compilation": {
            "compilation_record_id": "record-target-tamper",
            "confirmation_id": "confirmation-target-tamper",
            "actor_ref": f"actor:agent:{session_id}",
            "session_ref": session_id,
            "project_ref": project_ref,
            "semantic_plan_hash": "a" * 64,
            "target": target,
            "chain_id": "chain:1",
            "operation_id": "model.rerun",
        }
    }
    store, proposal = _proposal_store(
        tmp_path,
        preconditions=preconditions,
        target=target,
        chain_id="chain:1",
        operation_id="model.rerun",
        session_id=session_id,
        store_root=tmp_path,
    )
    proposal_path = tmp_path / "proposals" / f"{proposal.proposal_id}.jsonl"
    records = [json.loads(line) for line in proposal_path.read_text(encoding="utf-8").splitlines()]
    original_fingerprint = records[-1]["fingerprint"]
    records[-1]["target"] = {"run_id": "run:tampered"}
    records[-1]["fingerprint"] = original_fingerprint
    proposal_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    repository = SimpleNamespace(root=tmp_path)
    authority_calls: list[tuple[str, str]] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []
    cutover_store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()

    class Compiler:
        def record(self, record_id):
            record_calls.append(record_id)
            raise AssertionError("compiler.record must not run after proposal tamper")

        def execute(self, record_id, *_args, **_kwargs):
            execute_calls.append(record_id)
            raise AssertionError("compiler.execute must not run after proposal tamper")

    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (repository, SimpleNamespace(), {"chain_id": "chain:1"}),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project_ref, session_ref, **_kwargs: authority_calls.append(
            (project_ref, session_ref)
        ) or Compiler(),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: cutover_store)

    with pytest.raises(WorkbenchAPIError, match="integrity|fingerprint|proposal") as error:
        asyncio.run(
            agent_routes.confirm_agent_proposal(
                session_id,
                proposal.proposal_id,
                str(tmp_path),
                agent_routes.AgentProposalConfirmRequest(
                    revision=proposal.revision,
                    fingerprint=proposal.fingerprint,
                    active_head_run_id="run:1",
                ),
            )
        )

    assert error.value.status_code in {403, 409}
    assert authority_calls == []
    assert record_calls == []
    assert execute_calls == []
    assert cutover_store.legacy_proposal_bindings == {}
    assert store.latest_revision(proposal.proposal_id).target == {"run_id": "run:tampered"}


def test_route_rejects_incomplete_persisted_compilation_before_execute(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    store, proposal = _proposal_store(
        tmp_path,
        preconditions={},
        session_id=session_id,
        chain_id="chain:1",
        store_root=tmp_path,
    )
    repository = SimpleNamespace(root=tmp_path)
    authority_calls: list[tuple[str, str]] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []
    cutover_store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()

    class Compiler:
        def record(self, record_id):
            record_calls.append(record_id)
            raise AssertionError("compiler.record must not run for incomplete proposal")

        def execute(self, record_id, *_args, **_kwargs):
            execute_calls.append(record_id)
            raise AssertionError("compiler.execute must not run for incomplete proposal")

    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (repository, SimpleNamespace(), {"chain_id": "chain:1"}),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project_ref, session_ref, **_kwargs: authority_calls.append(
            (project_ref, session_ref)
        ) or Compiler(),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: cutover_store)

    with pytest.raises(WorkbenchAPIError, match="compilation|proposal") as error:
        asyncio.run(
            agent_routes.confirm_agent_proposal(
                session_id,
                proposal.proposal_id,
                str(tmp_path),
                agent_routes.AgentProposalConfirmRequest(
                    revision=proposal.revision,
                    fingerprint=proposal.fingerprint,
                    active_head_run_id="run:1",
                ),
            )
        )

    assert error.value.status_code in {403, 409}
    assert authority_calls == []
    assert record_calls == []
    assert execute_calls == []
    assert cutover_store.legacy_proposal_bindings == {}
    assert store.latest_revision(proposal.proposal_id).proposal_id == proposal.proposal_id


def test_route_rejects_cross_scope_server_compilation_before_execute(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    target = {"run_id": "run:1"}
    preconditions = {
        "server_compilation": {
            "compilation_record_id": "record-cross-scope",
            "confirmation_id": "confirmation-cross-scope",
            "actor_ref": f"actor:agent:{session_id}",
            "session_ref": session_id,
            "project_ref": "project:foreign",
            "semantic_plan_hash": "a" * 64,
            "target": target,
            "chain_id": "chain:foreign",
            "operation_id": "graph.fork",
        }
    }
    store, proposal = _proposal_store(
        tmp_path,
        preconditions=preconditions,
        target=target,
        chain_id="chain:1",
        operation_id="model.rerun",
        session_id=session_id,
        store_root=tmp_path,
    )
    repository = SimpleNamespace(root=tmp_path)
    authority_calls: list[tuple[str, str]] = []
    record_calls: list[str] = []
    execute_calls: list[str] = []
    cutover_store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()

    class Compiler:
        def record(self, record_id):
            record_calls.append(record_id)
            raise AssertionError("compiler.record must not run for cross-scope proposal")

        def execute(self, record_id, *_args, **_kwargs):
            execute_calls.append(record_id)
            raise AssertionError("compiler.execute must not run for cross-scope proposal")

    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (repository, SimpleNamespace(), {"chain_id": "chain:1"}),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project_ref, session_ref, **_kwargs: authority_calls.append(
            (project_ref, session_ref)
        ) or Compiler(),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: cutover_store)

    with pytest.raises(WorkbenchAPIError, match="scope|proposal") as error:
        asyncio.run(
            agent_routes.confirm_agent_proposal(
                session_id,
                proposal.proposal_id,
                str(tmp_path),
                agent_routes.AgentProposalConfirmRequest(
                    revision=proposal.revision,
                    fingerprint=proposal.fingerprint,
                    active_head_run_id="run:1",
                ),
            )
        )

    assert error.value.status_code in {403, 409}
    assert authority_calls == []
    assert record_calls == []
    assert execute_calls == []
    assert cutover_store.legacy_proposal_bindings == {}
    assert store.latest_revision(proposal.proposal_id).session_id == session_id


def test_forged_caller_revision_is_not_authority_and_does_not_bind(tmp_path) -> None:
    store, persisted = _proposal_store(tmp_path, preconditions={})
    _catalog, compiler = _cutover()
    forged = replace(persisted, target={"run_id": "run:forged"})

    with pytest.raises(CutoverCompilerError, match="caller-created ProposalRevision"):
        compiler.compile_for_proposal(
            _intent(),
            proposal_store=store,
            proposal_id=persisted.proposal_id,
            proposal=forged,
            entrypoint="agent",
        )

    assert compiler._proposal_bindings == {}


def _route_binding_proposal(tmp_path, *, semantic_plan_hash: str = "a" * 64):
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    proposal_id = "proposal-a"
    record_id = "record-receipt"
    target = {"run_id": "run:1"}
    actor_ref = f"actor:agent:{session_id}"
    binding = {
        "compilation_record_id": record_id,
        "confirmation_id": "confirmation-a",
        "proposal_id": proposal_id,
        "proposal_revision": 1,
        "proposal_fingerprint": "fingerprint-a",
        "operation_id": "model.rerun",
        "semantic_plan_hash": semantic_plan_hash,
        "actor_ref": actor_ref,
        "session_ref": session_id,
        "project_ref": project_ref,
        "target": target,
        "chain_id": "chain:1",
    }
    proposal = SimpleNamespace(
        proposal_id=proposal_id,
        revision=1,
        fingerprint="fingerprint-a",
        session_id=session_id,
        chain_id="chain:1",
        operation_id="model.rerun",
        target=target,
        preconditions={"server_compilation": binding},
    )
    return proposal, project_ref, session_id, actor_ref, record_id, binding


def test_forged_retained_receipt_fails_before_authority_record_execute_or_claim(
    tmp_path, monkeypatch
) -> None:
    proposal, project_ref, session_id, actor_ref, record_id, _binding = _route_binding_proposal(tmp_path)
    receipt = _server_receipt(
        confirmation_id="confirmation-a",
        compilation_record_id=record_id,
        proposal_id="proposal-a",
        proposal_revision=1,
        proposal_fingerprint="fingerprint-a",
        semantic_plan_hash="a" * 64,
        actor_ref=actor_ref,
        session_ref=session_id,
        project_ref=project_ref,
    )
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.retain_confirmation(project_ref, session_id, record_id, receipt)
    store.confirmations[(project_ref, session_id, record_id)] = replace(
        receipt,
        proposal_id="proposal-forged",
        proposal_fingerprint="fingerprint-forged",
    )
    authority_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: authority_calls.append((project, session)),
    )
    monkeypatch.setattr(agent_routes, "_cutover_store", lambda **_kwargs: store)
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )

    with pytest.raises(WorkbenchAPIError):
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal,
            proposal_id=proposal.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert authority_calls == []
    assert store.legacy_proposal_bindings == {}


def test_replayed_route_binding_fails_before_authority_record_execute_or_write(
    tmp_path, monkeypatch
) -> None:
    proposal, project_ref, session_id, actor_ref, record_id, binding = _route_binding_proposal(tmp_path)
    receipt = _server_receipt(
        confirmation_id="confirmation-a",
        compilation_record_id=record_id,
        proposal_id="proposal-a",
        proposal_revision=1,
        proposal_fingerprint="fingerprint-a",
        semantic_plan_hash="a" * 64,
        actor_ref=actor_ref,
        session_ref=session_id,
        project_ref=project_ref,
    )
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.retain_confirmation(project_ref, session_id, record_id, receipt)
    key = (project_ref, session_id, record_id)
    store.legacy_proposal_bindings[key] = dict(binding)
    authority_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project, session, **_kwargs: authority_calls.append((project, session)),
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
    assert store.legacy_proposal_bindings[key] == binding
