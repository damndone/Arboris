from __future__ import annotations

from fastapi import FastAPI
import pytest

from workbench.agent.cutover_runtime import EvidenceCommitReceiptV1
from workbench.agent.planning_contracts import DeploymentIdentityResolverV1
from workbench.app import (
    bootstrap_builtin_agent_notebook_host,
)
from workbench.canonical import sha256_canonical
from workbench.providers.catalog import load_builtin_catalog
from workbench.services.results_service import UnavailableReportEvidenceCapabilityV1
from tests.v189_cutover_test_host import CutoverTestHostCompiler


def _evidence_committer(context: object, result: dict[str, object]) -> EvidenceCommitReceiptV1:
    return EvidenceCommitReceiptV1(
        evidence_ref="evidence:host-bootstrap:test",
        evidence_digest=sha256_canonical(
            {
                "execution_instance_hash": context.execution_instance_hash,
                "result": dict(result),
            }
        ),
        compilation_record_id=context.compilation_record_id,
        execution_instance_hash=context.execution_instance_hash,
        actor_ref=context.actor_ref,
        session_ref=context.session_ref,
        project_ref=context.project_ref,
    )


def _identity_resolver(_request, project_ref: str, claimed_session_ref: str | None, _notebook_id):
    return ("principal:host", claimed_session_ref or "session:host", project_ref)


def _typed_identity_resolver() -> DeploymentIdentityResolverV1:
    """Create a typed seam without pretending this unit test owns host authority."""

    resolver = object.__new__(DeploymentIdentityResolverV1)
    object.__setattr__(resolver, "_scope_resolver", object())
    object.__setattr__(resolver, "_authenticated_identity_resolver", _identity_resolver)
    return resolver


def _report_identity_resolver(_request, _run_id):
    return None


def _kwargs(app_instance: FastAPI) -> dict[str, object]:
    return {
        "project_ref": "project:host-bootstrap",
        "session_ref": "session:host-bootstrap",
        "provider_catalog": load_builtin_catalog(),
        "evidence_committer": _evidence_committer,
        "host_compiler": CutoverTestHostCompiler(),
        "report_evidence_persistence": UnavailableReportEvidenceCapabilityV1(
            "TEST_REPORT_OWNER_EXPLICITLY_UNAVAILABLE"
        ),
        "notebook_identity_resolver": _typed_identity_resolver(),
        "report_identity_resolver": _report_identity_resolver,
        "app_instance": app_instance,
    }


def test_host_bootstrap_rejects_missing_authority_before_mutating_app_state() -> None:
    host_app = FastAPI()
    kwargs = _kwargs(host_app)
    kwargs["notebook_identity_resolver"] = None

    with pytest.raises(ValueError, match="notebook_identity_resolver"):
        bootstrap_builtin_agent_notebook_host(**kwargs)

    assert not hasattr(host_app.state, "agent_notebook_cutover_store")
    assert not hasattr(host_app.state, "report_evidence_persistence")


def test_host_bootstrap_installs_one_atomic_server_owned_bundle() -> None:
    host_app = FastAPI()

    runtime = bootstrap_builtin_agent_notebook_host(**_kwargs(host_app))

    assert host_app.state.agent_notebook_cutover_store.authorities[
        ("project:host-bootstrap", "session:host-bootstrap")
    ] is runtime.compiler
    assert host_app.state.report_evidence_persistence.reason_code == (
        "TEST_REPORT_OWNER_EXPLICITLY_UNAVAILABLE"
    )
    assert isinstance(
        host_app.state.notebook_cutover_identity_resolver,
        DeploymentIdentityResolverV1,
    )
    assert host_app.state.report_evidence_identity_resolver is _report_identity_resolver


def test_host_bootstrap_rolls_back_all_bindings_if_final_install_fails(monkeypatch) -> None:
    import workbench.app as app_module

    host_app = FastAPI()
    old_report = UnavailableReportEvidenceCapabilityV1("OLD_REPORT")
    old_notebook_resolver = lambda *_args: ("principal:old", "session:old", "project:old")
    old_report_resolver = lambda *_args: None
    app_module._bootstrap_app(host_app)
    host_app.state.report_evidence_persistence = old_report
    host_app.state.notebook_cutover_identity_resolver = old_notebook_resolver
    host_app.state.report_evidence_identity_resolver = old_report_resolver
    old_store = host_app.state.agent_notebook_cutover_store
    old_store.authorities[("project:host-bootstrap", "session:host-bootstrap")] = "old"

    def fail_final_install(**_kwargs):
        raise RuntimeError("final install failed")

    monkeypatch.setattr(app_module, "configure_agent_notebook_runtime_bundle", fail_final_install)

    with pytest.raises(RuntimeError, match="final install failed"):
        bootstrap_builtin_agent_notebook_host(**_kwargs(host_app))

    assert host_app.state.report_evidence_persistence is old_report
    assert host_app.state.notebook_cutover_identity_resolver is old_notebook_resolver
    assert host_app.state.report_evidence_identity_resolver is old_report_resolver
    assert host_app.state.agent_notebook_cutover_store is old_store
    assert old_store.authorities[("project:host-bootstrap", "session:host-bootstrap")] == "old"
