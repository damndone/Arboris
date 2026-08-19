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
