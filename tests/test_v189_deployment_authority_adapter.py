from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from workbench.agent import planning_contracts
from workbench.agent.authority import HostAuthorityHandleV1
from workbench.app import (
    build_deployment_agent_notebook_identity_resolver,
    bootstrap_builtin_agent_notebook_host,
    bootstrap_builtin_agent_notebook_host_from_deployment,
)
from workbench.services.results_service import UnavailableReportEvidenceCapabilityV1


def test_deployment_identity_resolver_rejects_non_admitted_handle() -> None:
    with pytest.raises(ValueError, match="host authority handle"):
        build_deployment_agent_notebook_identity_resolver(
            host_authority_handle=object(),
            authenticated_identity_resolver=lambda *_args: (
                "principal:test",
                "session:test",
            ),
        )


def test_deployment_identity_resolver_rejects_dead_admitted_handle() -> None:
    with pytest.raises(ValueError, match="host authority handle"):
        build_deployment_agent_notebook_identity_resolver(
            host_authority_handle=object.__new__(HostAuthorityHandleV1),
            authenticated_identity_resolver=lambda *_args: (
                "principal:test",
                "session:test",
            ),
        )


def test_deployment_identity_resolver_requires_authenticated_identity_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = object.__new__(HostAuthorityHandleV1)
    fake_scope_resolver = object.__new__(planning_contracts.ScopeAuthorityResolverV1)
    monkeypatch.setattr(
        planning_contracts.ScopeAuthorityResolverV1,
        "from_host_handle",
        classmethod(lambda _cls, _handle: fake_scope_resolver),
    )

    with pytest.raises(ValueError, match="authenticated_identity_resolver"):
        build_deployment_agent_notebook_identity_resolver(
            host_authority_handle=handle,
            authenticated_identity_resolver=None,
        )


def test_deployment_identity_resolver_revalidates_scope_through_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = object.__new__(HostAuthorityHandleV1)
    fake_scope_resolver = object.__new__(planning_contracts.ScopeAuthorityResolverV1)
    monkeypatch.setattr(
        planning_contracts.ScopeAuthorityResolverV1,
        "from_host_handle",
        classmethod(lambda _cls, _handle: fake_scope_resolver),
    )

    binding = object.__new__(planning_contracts.ServerScopeBindingV1)
    object.__setattr__(binding, "scope_ref", "project:host")
    object.__setattr__(binding, "principal_ref", "principal:alice")
    object.__setattr__(binding, "session_ref", "session:abc")
    object.__setattr__(binding, "project_ref", "project:host")
    object.__setattr__(binding, "_binding_id", "binding:host")
    monkeypatch.setattr(
        planning_contracts.ScopeAuthorityResolverV1,
        "resolve",
        lambda _self, **kwargs: (kwargs, binding)[1],
    )

    resolver = build_deployment_agent_notebook_identity_resolver(
        host_authority_handle=handle,
        authenticated_identity_resolver=lambda *_args: (
            "principal:alice",
            "session:abc",
        ),
    )

    assert resolver(
        SimpleNamespace(),
        "project:host",
        "session:hint",
        "notebook:1",
    ) == ("principal:alice", "session:abc", "project:host")


def test_deployment_identity_resolver_rejects_scope_authority_scope_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = object.__new__(HostAuthorityHandleV1)
    fake_scope_resolver = object.__new__(planning_contracts.ScopeAuthorityResolverV1)
    monkeypatch.setattr(
        planning_contracts.ScopeAuthorityResolverV1,
        "from_host_handle",
        classmethod(lambda _cls, _handle: fake_scope_resolver),
    )

    binding = object.__new__(planning_contracts.ServerScopeBindingV1)
    object.__setattr__(binding, "scope_ref", "scope:wrong")
    object.__setattr__(binding, "principal_ref", "principal:alice")
    object.__setattr__(binding, "session_ref", "session:abc")
    object.__setattr__(binding, "project_ref", "project:host")
    object.__setattr__(binding, "_binding_id", "binding:wrong-scope")
    monkeypatch.setattr(
        planning_contracts.ScopeAuthorityResolverV1,
        "resolve",
        lambda _self, **_kwargs: binding,
    )

    resolver = build_deployment_agent_notebook_identity_resolver(
        host_authority_handle=handle,
        authenticated_identity_resolver=lambda *_args: (
            "principal:alice",
            "session:abc",
        ),
    )

    with pytest.raises(ValueError, match="mismatched binding"):
        resolver(SimpleNamespace(), "project:host", "session:hint", "notebook:1")


def test_deployment_bootstrap_rejects_missing_external_authority_before_state_change() -> None:
    host_app = FastAPI()

    with pytest.raises(ValueError, match="host authority handle"):
        bootstrap_builtin_agent_notebook_host_from_deployment(
            host_authority_handle=None,
            authenticated_identity_resolver=lambda *_args: (
                "principal:test",
                "session:test",
            ),
            project_ref="project:test",
            session_ref="session:test",
            provider_catalog=object(),
            evidence_committer=lambda *_args: None,
            host_compiler=object(),
            report_evidence_persistence=UnavailableReportEvidenceCapabilityV1("TEST"),
            app_instance=host_app,
        )

    assert not hasattr(host_app.state, "agent_notebook_cutover_store")
    assert not hasattr(host_app.state, "report_evidence_persistence")


def test_generic_host_bootstrap_rejects_untyped_identity_callback_before_state_change() -> None:
    host_app = FastAPI()

    with pytest.raises(ValueError, match="deployment identity resolver"):
        bootstrap_builtin_agent_notebook_host(
            project_ref="project:test",
            session_ref="session:test",
            provider_catalog=object(),
            evidence_committer=lambda *_args: None,
            host_compiler=object(),
            report_evidence_persistence=UnavailableReportEvidenceCapabilityV1("TEST"),
            notebook_identity_resolver=lambda *_args: (
                "principal:test",
                "session:test",
                "project:test",
            ),
            app_instance=host_app,
        )

    assert not hasattr(host_app.state, "agent_notebook_cutover_store")
    assert not hasattr(host_app.state, "report_evidence_persistence")
