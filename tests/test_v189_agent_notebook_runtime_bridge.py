from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from workbench.agent.cutover_runtime import (
    EvidenceCommitReceiptV1,
    compose_agent_notebook_runtime,
)
from workbench.canonical import sha256_canonical
from workbench.agent.trusted_executor_registry import (
    ProviderRuntimeContributionV1,
    ProviderRuntimeContextV1,
    TrustedExecutorRegistryError,
)
from workbench.api_errors import WorkbenchAPIError
from workbench.api_errors import register_error_handlers
from workbench.app import (
    configure_agent_notebook_runtime,
    configure_notebook_cutover_identity_resolver,
)
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.http.agent_routes import (
    AgentNotebookCutoverCompileRequest,
    AgentNotebookCutoverScopeRequest,
    compile_agent_notebook_cutover,
    lookup_agent_notebook_cutover_authority,
    new_agent_notebook_cutover_authority_store,
    register_agent_notebook_cutover_authority,
    router as agent_router,
)
from workbench.providers.catalog import load_builtin_catalog
from tests.v189_cutover_test_host import CutoverTestHostCompiler


_SCOPE_A = {
    "project_ref": "project:runtime-bridge-a",
    "session_ref": "session:runtime-bridge-a",
    "actor_ref": "principal:runtime-bridge-a",
}
_SCOPE_B = {
    "project_ref": "project:runtime-bridge-b",
    "session_ref": "session:runtime-bridge-b",
    "actor_ref": "principal:runtime-bridge-b",
}
_UNBOUND_SCOPE = {
    "project_ref": "project:runtime-bridge-unbound",
    "session_ref": "session:runtime-bridge-unbound",
    "actor_ref": "principal:runtime-bridge-unbound",
}


def _contribution(
    provider_id: str,
    declaration: object,
) -> ProviderRuntimeContributionV1:
    adapter_id = declaration.adapter_id

    def validate_request(request: Mapping[str, object]) -> dict[str, object]:
        return dict(request)

    def validate_result(result: Mapping[str, object]) -> None:
        if not isinstance(result, Mapping):
            raise ValueError("result must be a mapping")

    def execute(
        context: ProviderRuntimeContextV1,
        request: Mapping[str, object],
    ) -> Mapping[str, object]:
        return {
            "status": "completed",
            "provider_id": provider_id,
            "adapter_id": adapter_id,
            "execution_instance_hash": context.execution_instance_hash,
            "request": dict(request),
        }

    return ProviderRuntimeContributionV1(
        provider_id=provider_id,
        adapter_id=adapter_id,
        executor_ref=declaration.executor_ref,
        owner="server:runtime-bridge-test",
        signature="runtime-bridge-test-v1",
        effect="read_only",
        request_contract_ref=declaration.request_schema_ref,
        result_contract_refs=declaration.output_refs,
        executor=execute,
        request_validator=validate_request,
        result_validator=validate_result,
    )


def _contributions(provider_catalog: object) -> list[ProviderRuntimeContributionV1]:
    return [
        _contribution(provider.provider_id, declaration)
        for provider in provider_catalog.providers
        for declaration in provider.adapter_declarations
    ]


def _evidence_committer(
    context: ProviderRuntimeContextV1,
    result: Mapping[str, object],
) -> EvidenceCommitReceiptV1:
    return EvidenceCommitReceiptV1(
        evidence_ref="evidence:runtime-bridge:test",
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


def _runtime():
    provider_catalog = load_builtin_catalog()
    return compose_agent_notebook_runtime(
        provider_catalog=provider_catalog,
        contributions=_contributions(provider_catalog),
        evidence_committer=_evidence_committer,
        host_compiler=CutoverTestHostCompiler(),
    )


def _compile_request(scope: Mapping[str, str]) -> AgentNotebookCutoverCompileRequest:
    return AgentNotebookCutoverCompileRequest(
        text="请检查 dataset:runtime-bridge:1",
        actor_ref=scope["actor_ref"],
        session_ref=scope["session_ref"],
        project_ref=scope["project_ref"],
        normalized_fields={
            "capability_id": "fixture.contracts.capability",
            "target_ref": "dataset:runtime-bridge:1",
            "data_snapshot_ref": "dataset:snapshot:runtime-bridge",
            "data_snapshot_digest": "a" * 64,
            "requested_effect": "read",
            "sensitivity": "public",
        },
    )


def _bound_agent_client(
    *scoped_runtimes: tuple[Mapping[str, str], object],
) -> tuple[FastAPI, TestClient]:
    """Build the explicit HTTP host harness required by the route boundary."""

    host_app = FastAPI()
    register_error_handlers(host_app)
    host_app.include_router(agent_router)
    bindings = {
        scope["session_ref"]: scope
        for scope, _runtime in scoped_runtimes
    }
    for scope, runtime in scoped_runtimes:
        configure_agent_notebook_runtime(
            project_ref=scope["project_ref"],
            session_ref=scope["session_ref"],
            compiler=runtime.compiler,
            app_instance=host_app,
        )

    def resolve_identity(_request, _project_ref, claimed_session_ref, _notebook_id):
        scope = bindings.get(claimed_session_ref)
        if scope is None:
            raise WorkbenchAPIError(
                status_code=503,
                code="AGENT_NOTEBOOK_IDENTITY_NOT_BOUND",
                message="test host identity is not bound",
            )
        return scope["actor_ref"], scope["session_ref"], scope["project_ref"]

    configure_notebook_cutover_identity_resolver(
        resolve_identity,
        app_instance=host_app,
    )
    return host_app, TestClient(host_app)


@pytest.fixture(autouse=True)
def _clear_test_scopes():
    for scope in (_SCOPE_A, _SCOPE_B, _UNBOUND_SCOPE):
        configure_agent_notebook_runtime(
            project_ref=scope["project_ref"],
            session_ref=scope["session_ref"],
            compiler=None,
        )
    yield
    for scope in (_SCOPE_A, _SCOPE_B, _UNBOUND_SCOPE):
        configure_agent_notebook_runtime(
            project_ref=scope["project_ref"],
            session_ref=scope["session_ref"],
            compiler=None,
        )


def test_runtime_composition_joins_real_contributions_once() -> None:
    runtime = _runtime()

    assert runtime.compiler.evidence_committer is _evidence_committer
    assert runtime.runtime_registry.executor_refs
    assert runtime.catalog.require("fixture.contracts.capability").executor_ref == (
        "executor:fixture.contracts.adapter"
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("missing", "RUNTIME_CONTRIBUTION_MISSING"),
        ("duplicate", "RUNTIME_DUPLICATE_EXECUTOR"),
        ("contract", "RUNTIME_REQUEST_CONTRACT_MISMATCH"),
    ),
)
def test_runtime_composition_fails_closed_for_invalid_join(
    case: str,
    expected_code: str,
) -> None:
    provider_catalog = load_builtin_catalog()
    contributions = _contributions(provider_catalog)
    if case == "missing":
        contributions = contributions[:-1]
    elif case == "duplicate":
        contributions = [*contributions, contributions[0]]
    else:
        bad_ref = ContractRefV1(
            kind="schema",
            logical_id="runtime-bridge.wrong-schema",
            semantic_version="1.0",
            contract_digest="f" * 64,
        )
        contributions[0] = replace(contributions[0], request_contract_ref=bad_ref)

    with pytest.raises(TrustedExecutorRegistryError) as error:
        compose_agent_notebook_runtime(
            provider_catalog=provider_catalog,
            contributions=contributions,
            evidence_committer=_evidence_committer,
            host_compiler=CutoverTestHostCompiler(),
        )

    assert error.value.code == expected_code


def test_runtime_composition_requires_evidence_committer() -> None:
    provider_catalog = load_builtin_catalog()

    with pytest.raises(TrustedExecutorRegistryError) as error:
        compose_agent_notebook_runtime(
            provider_catalog=provider_catalog,
            contributions=_contributions(provider_catalog),
            evidence_committer=None,
            host_compiler=CutoverTestHostCompiler(),
        )

    assert error.value.code == "RUNTIME_EVIDENCE_COMMITTER_REQUIRED"


def test_runtime_composition_requires_a_host_compiler() -> None:
    provider_catalog = load_builtin_catalog()

    with pytest.raises(TrustedExecutorRegistryError) as error:
        compose_agent_notebook_runtime(
            provider_catalog=provider_catalog,
            contributions=_contributions(provider_catalog),
            evidence_committer=_evidence_committer,
            host_compiler=None,
        )

    assert error.value.code == "RUNTIME_HOST_COMPILER_REQUIRED"


def test_app_bootstrap_installs_compiler_for_one_exact_scope() -> None:
    runtime = _runtime()
    host_app, client = _bound_agent_client((_SCOPE_A, runtime))

    assert lookup_agent_notebook_cutover_authority(
        _SCOPE_A["project_ref"],
        _SCOPE_A["session_ref"],
        request=SimpleNamespace(app=host_app),
    ) is runtime.compiler
    response = client.post("/agent/cutover/compile", json=_compile_request(_SCOPE_A).model_dump())
    assert response.status_code == 200, response.text
    assert response.json()["preview"]["entrypoint"] == "agent"


def test_scope_lookup_does_not_leak_authority_or_confirmation_across_scopes() -> None:
    runtime_a = _runtime()
    runtime_b = _runtime()
    register_agent_notebook_cutover_authority(
        project_ref=_SCOPE_A["project_ref"],
        session_ref=_SCOPE_A["session_ref"],
        compiler=runtime_a.compiler,
    )
    register_agent_notebook_cutover_authority(
        project_ref=_SCOPE_B["project_ref"],
        session_ref=_SCOPE_B["session_ref"],
        compiler=runtime_b.compiler,
    )

    assert lookup_agent_notebook_cutover_authority(
        _SCOPE_A["project_ref"], _SCOPE_A["session_ref"]
    ) is runtime_a.compiler
    assert lookup_agent_notebook_cutover_authority(
        _SCOPE_B["project_ref"], _SCOPE_B["session_ref"]
    ) is runtime_b.compiler
    with pytest.raises(WorkbenchAPIError) as unbound:
        lookup_agent_notebook_cutover_authority(
            _UNBOUND_SCOPE["project_ref"], _UNBOUND_SCOPE["session_ref"]
        )
    assert unbound.value.code == "AGENT_NOTEBOOK_CUTOVER_NOT_BOUND"

    runtime_host, client = _bound_agent_client(
        (_SCOPE_A, runtime_a),
        (_SCOPE_B, runtime_b),
    )
    response = client.post("/agent/cutover/compile", json=_compile_request(_SCOPE_A).model_dump())
    assert response.status_code == 200, response.text
    record_id = response.json()["preview"]["compilation_record_id"]
    assert isinstance(record_id, str)
    cross_scope = client.post(
        f"/agent/cutover/{record_id}/confirm",
        json=AgentNotebookCutoverScopeRequest(**_SCOPE_B).model_dump(),
    )
    assert cross_scope.status_code == 409, cross_scope.text
    assert cross_scope.json()["error"]["code"] == "SERVER_RECORD_UNKNOWN"


def test_http_authority_store_isolated_per_application_instance() -> None:
    runtime = _runtime()
    app_a = SimpleNamespace(
        state=SimpleNamespace(agent_notebook_cutover_store=new_agent_notebook_cutover_authority_store())
    )
    app_b = SimpleNamespace(
        state=SimpleNamespace(agent_notebook_cutover_store=new_agent_notebook_cutover_authority_store())
    )
    request_a = SimpleNamespace(app=app_a)
    request_b = SimpleNamespace(app=app_b)

    from workbench.http.agent_routes import configure_agent_notebook_cutover_authority

    configure_agent_notebook_cutover_authority(
        project_ref=_SCOPE_A["project_ref"],
        session_ref=_SCOPE_A["session_ref"],
        compiler=runtime.compiler,
        app_instance=app_a,
    )

    assert lookup_agent_notebook_cutover_authority(
        _SCOPE_A["project_ref"],
        _SCOPE_A["session_ref"],
        request=request_a,
    ) is runtime.compiler
    with pytest.raises(WorkbenchAPIError) as isolated:
        lookup_agent_notebook_cutover_authority(
            _SCOPE_A["project_ref"],
            _SCOPE_A["session_ref"],
            request=request_b,
        )
    assert isolated.value.code == "AGENT_NOTEBOOK_CUTOVER_NOT_BOUND"


def test_real_agent_http_requires_server_identity_and_canonical_project() -> None:
    runtime = _runtime()
    host_app = FastAPI()
    register_error_handlers(host_app)
    host_app.include_router(agent_router)
    configure_agent_notebook_runtime(
        project_ref=_SCOPE_A["project_ref"],
        session_ref=_SCOPE_A["session_ref"],
        compiler=runtime.compiler,
        app_instance=host_app,
    )
    configure_notebook_cutover_identity_resolver(
        lambda _request, _project, _session, _notebook: (
            _SCOPE_A["actor_ref"],
            _SCOPE_A["session_ref"],
            _SCOPE_A["project_ref"],
        ),
        app_instance=host_app,
    )
    client = TestClient(host_app)
    payload = _compile_request(_SCOPE_A).model_dump()

    try:
        accepted = client.post("/agent/cutover/compile", json=payload)
        assert accepted.status_code == 200, accepted.text

        forged_actor = client.post(
            "/agent/cutover/compile",
            json={**payload, "actor_ref": "principal:forged"},
        )
        assert forged_actor.status_code == 403, forged_actor.text
        assert forged_actor.json()["error"]["code"] == "AGENT_NOTEBOOK_IDENTITY_MISMATCH"

        forged_project = client.post(
            "/agent/cutover/compile",
            json={**payload, "project_ref": "project:other"},
        )
        assert forged_project.status_code == 403, forged_project.text
        assert forged_project.json()["error"]["code"] == "AGENT_NOTEBOOK_PROJECT_MISMATCH"
    finally:
        configure_agent_notebook_runtime(
            project_ref=_SCOPE_A["project_ref"],
            session_ref=_SCOPE_A["session_ref"],
            compiler=None,
            app_instance=host_app,
        )
        configure_notebook_cutover_identity_resolver(None, app_instance=host_app)


def test_unbound_route_remains_explicit_503() -> None:
    with pytest.raises(WorkbenchAPIError) as error:
        compile_agent_notebook_cutover(_compile_request(_UNBOUND_SCOPE))

    assert error.value.status_code == 503
    assert error.value.code == "AGENT_NOTEBOOK_IDENTITY_NOT_BOUND"


def test_app_bootstrap_can_unbind_one_scope_without_affecting_another() -> None:
    runtime_a = _runtime()
    runtime_b = _runtime()
    configure_agent_notebook_runtime(
        project_ref=_SCOPE_A["project_ref"],
        session_ref=_SCOPE_A["session_ref"],
        compiler=runtime_a.compiler,
    )
    configure_agent_notebook_runtime(
        project_ref=_SCOPE_B["project_ref"],
        session_ref=_SCOPE_B["session_ref"],
        compiler=runtime_b.compiler,
    )

    configure_agent_notebook_runtime(
        project_ref=_SCOPE_A["project_ref"],
        session_ref=_SCOPE_A["session_ref"],
        compiler=None,
    )

    with pytest.raises(WorkbenchAPIError) as removed:
        lookup_agent_notebook_cutover_authority(
            _SCOPE_A["project_ref"], _SCOPE_A["session_ref"]
        )
    assert removed.value.code == "AGENT_NOTEBOOK_CUTOVER_NOT_BOUND"
    assert lookup_agent_notebook_cutover_authority(
        _SCOPE_B["project_ref"], _SCOPE_B["session_ref"]
    ) is runtime_b.compiler
