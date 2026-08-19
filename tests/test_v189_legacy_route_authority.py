from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from workbench.api_errors import WorkbenchAPIError
from workbench.http import agent_routes, notebook_routes


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

    assert error.value.code == "AGENT_LEGACY_COMPILATION_REQUIRED"


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

    assert error.value.code == "AGENT_LEGACY_BINDING_MISMATCH"
    if mismatch_field == "project_ref":
        assert authority_calls == []
