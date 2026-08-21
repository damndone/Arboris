from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from workbench.api_errors import WorkbenchAPIError
from workbench.http import agent_routes
from workbench.http.agent_routes import (
    AgentProposalConfirmRequest,
    AgentNotebookCutoverCompileRequest,
    AgentNotebookCutoverExecuteRequest,
    AgentNotebookCutoverScopeRequest,
    compile_agent_notebook_cutover,
    confirm_agent_notebook_cutover,
    execute_agent_notebook_cutover,
)


def _compile_body() -> AgentNotebookCutoverCompileRequest:
    return AgentNotebookCutoverCompileRequest(
        text="请检查 dataset:identity-boundary",
        actor_ref="principal:caller",
        session_ref="session:caller",
        project_ref="project:caller",
        normalized_fields={},
    )


def _scope_body() -> AgentNotebookCutoverScopeRequest:
    return AgentNotebookCutoverScopeRequest(
        actor_ref="principal:caller",
        session_ref="session:caller",
        project_ref="project:caller",
    )


@pytest.mark.parametrize(
    ("invoke", "expected_record_id"),
    [
        (lambda _record_id: compile_agent_notebook_cutover(_compile_body()), None),
        (
            lambda record_id: confirm_agent_notebook_cutover(
                record_id,
                _scope_body(),
            ),
            "compilation-record:caller",
        ),
        (
            lambda record_id: execute_agent_notebook_cutover(
                record_id,
                AgentNotebookCutoverExecuteRequest(
                    **_scope_body().model_dump(),
                    confirmation_id="confirmation:caller",
                ),
            ),
            "compilation-record:caller",
        ),
    ],
)
def test_request_none_fails_before_identity_or_cutover_side_effects(
    invoke,
    expected_record_id: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct route call cannot promote caller metadata into authority."""

    resolver_calls: list[object] = []
    cutover_calls: list[tuple[str, str]] = []

    def resolver(*_args: object, **_kwargs: object) -> tuple[str, str, str]:
        resolver_calls.append(object())
        return ("principal:server", "session:server", "project:server")

    def cutover_authority(project_ref: str, session_ref: str, **_kwargs: object):
        cutover_calls.append((project_ref, session_ref))
        raise AssertionError("request=None reached the cutover authority")

    monkeypatch.setattr(agent_routes, "resolve_agent_notebook_server_identity", resolver)
    monkeypatch.setattr(agent_routes, "_cutover_authority", cutover_authority)

    with pytest.raises(WorkbenchAPIError) as error:
        invoke(expected_record_id)

    assert error.value.code == "AGENT_NOTEBOOK_IDENTITY_NOT_BOUND"
    assert resolver_calls == []
    assert cutover_calls == []


def test_legacy_confirmation_request_none_fails_before_repository_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The legacy route must reject an absent host request before session IO."""

    def repository_tripwire(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request=None reached the Agent repository")

    monkeypatch.setattr(agent_routes, "_get_session", repository_tripwire)

    async def invoke() -> None:
        await agent_routes.confirm_agent_proposal(
            "session:caller",
            "proposal:caller",
            str(tmp_path),
            AgentProposalConfirmRequest(
                revision=1,
                fingerprint="caller-fingerprint",
                active_head_run_id="run:caller",
            ),
        )

    with pytest.raises(WorkbenchAPIError) as error:
        asyncio.run(invoke())

    assert error.value.code == "AGENT_NOTEBOOK_IDENTITY_NOT_BOUND"
