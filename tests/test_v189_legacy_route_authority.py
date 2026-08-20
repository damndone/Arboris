from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from workbench.api_errors import WorkbenchAPIError
from workbench.agent.orchestrator import ServerConfirmationReceiptV1
from workbench.contracts.agent.planning import (
    CompilationRecordReferenceV1,
    ConfirmationBindingV1,
)
from workbench.contracts.common.envelope import ContractError
from workbench.http import agent_routes, notebook_routes


def _server_receipt(
    *,
    confirmation_id: str,
    compilation_record_id: str,
    proposal_id: str,
    proposal_revision: int,
    proposal_fingerprint: str,
    semantic_plan_hash: str,
    actor_ref: str,
    session_ref: str,
    project_ref: str,
) -> ServerConfirmationReceiptV1:
    return ServerConfirmationReceiptV1(
        confirmation_id=confirmation_id,
        confirmation_digest="c" * 64,
        compilation_record_id=compilation_record_id,
        proposal_id=proposal_id,
        proposal_revision=proposal_revision,
        proposal_fingerprint=proposal_fingerprint,
        semantic_plan_hash=semantic_plan_hash,
        actor_ref=actor_ref,
        session_ref=session_ref,
        project_ref=project_ref,
        _authority_token=object(),
    )


def test_historical_agent_confirm_requires_server_compilation_before_orchestrator(
    tmp_path, monkeypatch
) -> None:
    """A legacy Agent proposal must not instantiate the old executor authority."""

    proposal = SimpleNamespace(
        proposal_id="proposal-1",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={},
        changes={},
    )
    repository = SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (repository, SimpleNamespace(), {}),
    )
    monkeypatch.setattr(
        agent_routes,
        "_proposal_for_session",
        lambda *_args, **_kwargs: proposal,
    )
    monkeypatch.setattr(
        agent_routes,
        "_authoritative_active_head",
        lambda *_args, **_kwargs: "run-1",
    )
    monkeypatch.setattr(
        agent_routes,
        "_current_proposal_context_fingerprint",
        lambda *_args, **_kwargs: "context-1",
    )
    monkeypatch.setattr(agent_routes, "_ensure_main_session", lambda *_args: "agent_main")

    class LegacyOrchestratorMustNotBeCalled:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("legacy WorkbenchOrchestrator was used as execution authority")

    monkeypatch.setattr(
        agent_routes, "WorkbenchOrchestrator", LegacyOrchestratorMustNotBeCalled
    )

    with pytest.raises(WorkbenchAPIError) as error:
        asyncio.run(
            agent_routes.confirm_agent_proposal(
                "session-1",
                "proposal-1",
                str(tmp_path),
                agent_routes.AgentProposalConfirmRequest(
                    revision=1,
                    fingerprint="context-1",
                    active_head_run_id="run-1",
                ),
            )
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"


def test_historical_notebook_confirm_paths_fail_closed_before_legacy_execution(
    tmp_path, monkeypatch
) -> None:
    """Both historical Notebook execution-shaped routes share the same gate."""

    current = SimpleNamespace(
        option_revision=1,
        typed_proposal_id="proposal-1",
        typed_proposal_revision=1,
        materializable=False,
        capability_resolution_binding_ref=None,
    )
    proposal = SimpleNamespace(operation_id="operation.multi_step")
    view = SimpleNamespace(
        current_revision=current,
        current_stored_revision=SimpleNamespace(proposal=proposal),
    )

    class Store:
        def read_option(self, _notebook_id, _option_id):
            return view

    class LegacyNotebookService:
        store = Store()

        def confirm_and_execute_workflow(self, *_args, **_kwargs):
            pytest.fail("legacy Notebook compile_workflow/execute_workflow path was used")

        def confirm_and_execute(self, *_args, **_kwargs):
            pytest.fail("legacy Notebook execution dispatch was used")

    service = LegacyNotebookService()
    monkeypatch.setattr(
        notebook_routes,
        "_service",
        lambda _request, _project_root: (tmp_path, service),
    )
    monkeypatch.setattr(
        notebook_routes,
        "_compile",
        lambda *_args, **_kwargs: (SimpleNamespace(), SimpleNamespace(trace_id="trace-1")),
    )
    body = notebook_routes.ConfirmOptionRequest(
        option_revision=1,
        proposal_id="proposal-1",
        proposal_revision=1,
    )

    for endpoint in (
        notebook_routes.confirm_option_endpoint,
        notebook_routes.confirm_and_execute_option_endpoint,
    ):
        with pytest.raises(WorkbenchAPIError) as error:
            endpoint(object(), str(tmp_path), "notebook-1", "option-1", body)
        assert error.value.code == "NOTEBOOK_LEGACY_COMPILATION_REQUIRED"


def test_historical_notebook_v10_confirm_paths_never_reach_service_execution(
    tmp_path, monkeypatch
) -> None:
    """v1.0/non-materializable options cannot use the old service authority."""

    current = SimpleNamespace(
        option_revision=1,
        typed_proposal_id="proposal-v10",
        typed_proposal_revision=1,
        materializable=False,
        contract_version="1.0",
        capability_resolution_binding_ref=None,
    )
    proposal = SimpleNamespace(operation_id="statistical.explore")
    view = SimpleNamespace(
        current_revision=current,
        current_stored_revision=SimpleNamespace(proposal=proposal),
    )

    class Store:
        def read_option(self, _notebook_id, _option_id):
            return view

    class LegacyNotebookService:
        store = Store()

        def confirm(self, *_args, **_kwargs):
            pytest.fail("v1.0 confirm reached the legacy service execution authority")

        def confirm_and_execute(self, *_args, **_kwargs):
            pytest.fail(
                "v1.0 confirm-and-execute reached the legacy service execution authority"
            )

    service = LegacyNotebookService()
    monkeypatch.setattr(
        notebook_routes,
        "_service",
        lambda _request, _project_root: (tmp_path, service),
    )
    monkeypatch.setattr(
        notebook_routes,
        "_compile",
        lambda *_args, **_kwargs: (SimpleNamespace(), SimpleNamespace(trace_id="trace-v10")),
    )
    body = notebook_routes.ConfirmOptionRequest(
        option_revision=1,
        proposal_id="proposal-v10",
        proposal_revision=1,
    )

    for endpoint in (
        notebook_routes.confirm_option_endpoint,
        notebook_routes.confirm_and_execute_option_endpoint,
    ):
        with pytest.raises(WorkbenchAPIError) as error:
            endpoint(object(), str(tmp_path), "notebook-v10", "option-v10", body)
        assert error.value.code == "NOTEBOOK_LEGACY_COMPILATION_REQUIRED"


@pytest.mark.parametrize(
    "mismatch_field",
    [
        "proposal_id",
        "proposal_revision",
        "proposal_fingerprint",
        "operation_id",
        "semantic_plan_hash",
        "project_ref",
    ],
)
def test_agent_legacy_binding_cannot_select_scope_or_mismatch_proposal(
    tmp_path, monkeypatch, mismatch_field
) -> None:
    """A proposal envelope cannot select a compiler or rewrite its identity."""

    session_id = "session-1"
    canonical_project = f"project:{tmp_path.resolve()}"
    canonical_actor = f"actor:agent:{session_id}"
    record_id = "record-1"
    semantic_plan_hash = "a" * 64
    binding = {
        "compilation_record_id": record_id,
        "confirmation_id": "confirmation-1",
        "proposal_id": "proposal-1",
        "proposal_revision": 3,
        "proposal_fingerprint": "proposal-fingerprint",
        "operation_id": "model.rerun",
        "semantic_plan_hash": semantic_plan_hash,
        "actor_ref": canonical_actor,
        "session_ref": session_id,
        "project_ref": canonical_project,
    }
    record_scope = {
        "principal_ref": canonical_actor,
        "session_ref": session_id,
        "project_ref": canonical_project,
    }
    confirmation_scope = {
        "confirmation_id": "confirmation-1",
        "compilation_record_id": record_id,
        "actor_ref": canonical_actor,
        "session_ref": session_id,
        "project_ref": canonical_project,
        "semantic_plan_hash": semantic_plan_hash,
    }
    if mismatch_field == "proposal_id":
        binding["proposal_id"] = "other-proposal"
    elif mismatch_field == "proposal_revision":
        binding["proposal_revision"] = 4
    elif mismatch_field == "proposal_fingerprint":
        binding["proposal_fingerprint"] = "other-fingerprint"
    elif mismatch_field == "operation_id":
        binding["operation_id"] = "graph.fork"
    elif mismatch_field == "semantic_plan_hash":
        binding["semantic_plan_hash"] = "b" * 64
    elif mismatch_field == "project_ref":
        binding["project_ref"] = "project:attacker"
        record_scope["project_ref"] = "project:attacker"
        confirmation_scope["project_ref"] = "project:attacker"

    proposal = SimpleNamespace(
        proposal_id="proposal-1",
        revision=3,
        fingerprint="proposal-fingerprint",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={"server_compilation": binding},
        changes={},
    )
    repository = SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (repository, SimpleNamespace(), {"chain_id": "chain-1"}),
    )
    monkeypatch.setattr(
        agent_routes,
        "_proposal_for_session",
        lambda *_args, **_kwargs: proposal,
    )
    monkeypatch.setattr(
        agent_routes,
        "_public_proposal",
        lambda *_args, **_kwargs: {"proposal_id": proposal.proposal_id},
    )
    authority_calls: list[tuple[str, str]] = []

    class Compiler:
        def record(self, _record_id):
            return SimpleNamespace(
                record_id=record_id,
                semantic_plan_hash=semantic_plan_hash,
                **record_scope,
            )

        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(
                to_dict=lambda: {
                    "operation_id": "model.rerun",
                    "status": "completed",
                }
            )

    compiler = Compiler()
    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda project_ref, session_ref, request=None: (
            authority_calls.append((project_ref, session_ref)) or compiler
        ),
    )
    confirmation = SimpleNamespace(**confirmation_scope)
    monkeypatch.setattr(
        agent_routes,
        "_cutover_store",
        lambda request=None: SimpleNamespace(
            confirmations={(canonical_project, session_id, record_id): confirmation}
        ),
    )

    with pytest.raises(WorkbenchAPIError) as error:
        asyncio.run(
            agent_routes.confirm_agent_proposal(
                session_id,
                proposal.proposal_id,
                str(tmp_path),
                agent_routes.AgentProposalConfirmRequest(
                    revision=3,
                    fingerprint="proposal-fingerprint",
                    active_head_run_id="run-1",
                ),
            )
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    if mismatch_field == "project_ref":
        assert authority_calls == []


def test_reused_legacy_compilation_confirmation_cannot_execute_a_second_proposal(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-a"
    semantic_plan_hash = "a" * 64
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.legacy_proposal_bindings[(project_ref, session_id, record_id)] = {
        "proposal_id": "proposal-a",
        "proposal_revision": 1,
        "proposal_fingerprint": "fingerprint-a",
        "operation_id": "model.rerun",
        "semantic_plan_hash": semantic_plan_hash,
        "confirmation_id": "confirmation-a",
        "actor_ref": actor_ref,
        "session_ref": session_id,
        "project_ref": project_ref,
    }
    proposal_b = SimpleNamespace(
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
    compiler_calls: list[str] = []

    class Compiler:
        def record(self, _record_id):
            return SimpleNamespace(
                record_id=record_id,
                semantic_plan_hash=semantic_plan_hash,
                principal_ref=actor_ref,
                session_ref=session_id,
                project_ref=project_ref,
            )

        def execute(self, *_args, **_kwargs):
            compiler_calls.append(record_id)
            return SimpleNamespace(
                to_dict=lambda: {"operation_id": "model.rerun", "status": "completed"}
            )

    monkeypatch.setattr(
        agent_routes,
        "_cutover_authority",
        lambda *_args, **_kwargs: Compiler(),
    )
    monkeypatch.setattr(
        agent_routes,
        "_cutover_store",
        lambda **_kwargs: store,
    )
    monkeypatch.setattr(
        agent_routes,
        "_legacy_agent_route_scope",
        lambda *_args, **_kwargs: (actor_ref, session_id, project_ref),
    )
    confirmation = _server_receipt(
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
    store.retain_confirmation(project_ref, session_id, record_id, confirmation)

    with pytest.raises(WorkbenchAPIError) as error:
        agent_routes._execute_legacy_agent_proposal_via_server_boundary(
            proposal_b,
            proposal_id=proposal_b.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert compiler_calls == []


def test_first_legacy_claim_uses_server_receipt_proposal_identity_before_execute(
    tmp_path, monkeypatch
) -> None:
    """A receipt for proposal A cannot be claimed by proposal B on first use."""

    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-a"
    semantic_plan_hash = "a" * 64
    proposal_b = SimpleNamespace(
        proposal_id="proposal-b",
        revision=1,
        fingerprint="fingerprint-b",
        chain_id="chain-1",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                # These are untrusted compatibility hints and must not become
                # the binding authority for the retained receipt.
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
    authority_calls: list[tuple[str, str]] = []
    record_calls: list[str] = []
    compiler_calls: list[str] = []

    class Compiler:
        def record(self, _record_id):
            record_calls.append(_record_id)
            return SimpleNamespace(
                record_id=record_id,
                semantic_plan_hash=semantic_plan_hash,
                principal_ref=actor_ref,
                session_ref=session_id,
                project_ref=project_ref,
            )

        def execute(self, *_args, **_kwargs):
            compiler_calls.append(record_id)
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
            proposal_b,
            proposal_id=proposal_b.proposal_id,
            root=tmp_path,
            session_id=session_id,
            request=None,
        )

    assert error.value.code == "AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED"
    assert authority_calls == []
    assert record_calls == []
    assert compiler_calls == []
    assert store.legacy_proposal_bindings == {}


def test_server_confirmation_receipt_serializes_proposal_identity() -> None:
    receipt = ServerConfirmationReceiptV1(
        confirmation_id="confirmation:a",
        confirmation_digest="c" * 64,
        compilation_record_id="record-a",
        proposal_id="proposal-a",
        proposal_revision=2,
        proposal_fingerprint="fingerprint-a",
        semantic_plan_hash="a" * 64,
        actor_ref="actor:agent:session-1",
        session_ref="session-1",
        project_ref="project:test",
        _authority_token=object(),
    )

    payload = receipt.to_dict()

    assert payload["proposal_id"] == "proposal-a"
    assert payload["proposal_revision"] == 2
    assert payload["proposal_fingerprint"] == "fingerprint-a"


def test_confirmation_binding_serialization_tamper_rejects_proposal_identity() -> None:
    binding = ConfirmationBindingV1(
        confirmation_id="confirmation:a",
        compilation_record_ref=CompilationRecordReferenceV1(
            record_id="record-a",
            record_digest="d" * 64,
            semantic_plan_hash="a" * 64,
        ),
        actor_ref="actor:agent:session-1",
        session_ref="session-1",
        project_ref="project:test",
        semantic_plan_hash="a" * 64,
        method_snapshot_ref="method:snapshot:1",
        risk_snapshot_ref="risk:snapshot:1",
        policy_snapshot_ref="policy:snapshot:1",
        confirmed_at="2026-08-19T19:00:00+00:00",
        expires_at="2026-08-19T20:00:00+00:00",
        proposal_id="proposal-a",
        proposal_revision=1,
        proposal_fingerprint="fingerprint-a",
    )

    restored = ConfirmationBindingV1.from_dict(binding.to_dict())
    assert restored.proposal_id == "proposal-a"
    tampered = binding.to_dict()
    tampered["proposal_id"] = "proposal-b"
    with pytest.raises(ContractError, match="digest"):
        ConfirmationBindingV1.from_dict(tampered)


def test_same_legacy_proposal_can_claim_once_but_replay_fails_closed(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-a"
    semantic_plan_hash = "a" * 64
    proposal = SimpleNamespace(
        proposal_id="proposal-a",
        revision=1,
        fingerprint="fingerprint-a",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-a",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-a",
                "operation_id": "model.rerun",
                "semantic_plan_hash": semantic_plan_hash,
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
            }
        },
    )
    compiler_calls: list[str] = []

    class Compiler:
        def record(self, _record_id):
            return SimpleNamespace(
                record_id=record_id,
                semantic_plan_hash=semantic_plan_hash,
                principal_ref=actor_ref,
                session_ref=session_id,
                project_ref=project_ref,
            )

        def execute(self, *_args, **_kwargs):
            compiler_calls.append(record_id)
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
    monkeypatch.setattr(agent_routes, "_cutover_authority", lambda *_args, **_kwargs: Compiler())
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
    assert compiler_calls == []


def test_serialized_legacy_confirmation_handle_cannot_execute(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-a"
    proposal = SimpleNamespace(
        proposal_id="proposal-a",
        revision=1,
        fingerprint="fingerprint-a",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-a",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-a",
                "operation_id": "model.rerun",
                "semantic_plan_hash": "a" * 64,
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
            }
        },
    )
    compiler_calls: list[str] = []

    class Compiler:
        def record(self, _record_id):
            return SimpleNamespace(
                record_id=record_id,
                semantic_plan_hash="a" * 64,
                principal_ref=actor_ref,
                session_ref=session_id,
                project_ref=project_ref,
            )

        def execute(self, *_args, **_kwargs):
            compiler_calls.append(record_id)
            return SimpleNamespace(to_dict=lambda: {"operation_id": "model.rerun", "status": "completed"})

    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    store.confirmations[(project_ref, session_id, record_id)] = {
        "confirmation_id": "confirmation-a",
        "compilation_record_id": record_id,
        "proposal_id": "proposal-a",
        "proposal_revision": 1,
        "proposal_fingerprint": "fingerprint-a",
        "semantic_plan_hash": "a" * 64,
        "actor_ref": actor_ref,
        "session_ref": session_id,
        "project_ref": project_ref,
    }
    store.confirmation_digests[(project_ref, session_id, record_id)] = "c" * 64
    monkeypatch.setattr(agent_routes, "_cutover_authority", lambda *_args, **_kwargs: Compiler())
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
    assert compiler_calls == []


def test_tampered_retained_receipt_fails_before_authority_or_claim(
    tmp_path, monkeypatch
) -> None:
    session_id = "session-1"
    project_ref = f"project:{tmp_path.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    record_id = "record-a"
    semantic_plan_hash = "a" * 64
    proposal = SimpleNamespace(
        proposal_id="proposal-a",
        revision=1,
        fingerprint="fingerprint-a",
        operation_id="model.rerun",
        preconditions={
            "server_compilation": {
                "compilation_record_id": record_id,
                "confirmation_id": "confirmation-a",
                "proposal_id": "proposal-a",
                "proposal_revision": 1,
                "proposal_fingerprint": "fingerprint-a",
                "operation_id": "model.rerun",
                "semantic_plan_hash": semantic_plan_hash,
                "actor_ref": actor_ref,
                "session_ref": session_id,
                "project_ref": project_ref,
            }
        },
    )
    store = agent_routes.AgentNotebookCutoverAuthorityStoreV1()
    receipt = _server_receipt(
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
    store.retain_confirmation(project_ref, session_id, record_id, receipt)
    store.confirmations[(project_ref, session_id, record_id)] = replace(
        receipt,
        confirmation_digest="d" * 64,
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


def test_legacy_reconcile_fails_closed_before_constructing_old_orchestrator(
    tmp_path, monkeypatch
) -> None:
    record = SimpleNamespace(
        agent_session_id="session-1",
        operation_id="model.rerun",
        status="running",
    )

    class Store:
        def __init__(self, _root):
            pass

        def get(self, _record_id):
            return record

    class LegacyOrchestratorMustNotBeCalled:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("legacy WorkbenchOrchestrator was used by reconcile")

    monkeypatch.setattr(agent_routes, "_project_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        agent_routes,
        "_get_session",
        lambda _root, _session_id: (SimpleNamespace(root=tmp_path), SimpleNamespace(), {}),
    )
    monkeypatch.setattr(agent_routes, "OperationRecordStore", Store)
    monkeypatch.setattr(
        agent_routes, "WorkbenchOrchestrator", LegacyOrchestratorMustNotBeCalled
    )

    with pytest.raises(WorkbenchAPIError) as error:
        asyncio.run(
            agent_routes.reconcile_agent_operation(
                "session-1", "record-1", str(tmp_path)
            )
        )

    assert error.value.code == "AGENT_LEGACY_RECONCILE_COMPILATION_REQUIRED"
