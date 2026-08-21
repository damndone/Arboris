"""FastAPI application assembly.

Owns the single ``app`` instance and error-handler registration. Route clusters
live in ``http/*_routes.py`` as ``APIRouter``s and are mounted here via
``include_router``. ``api.py`` re-exports this ``app`` (uvicorn target
``workbench.api:app``) and, during the v1.6.10 D1 router migration, still attaches
the not-yet-migrated routes onto it.

Extracted from ``api.py`` in v1.6.10 (D1 decomposition, Phase 4).
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .agent.cutover_runtime import AgentNotebookRuntimeV1
from .agent.authority import HostAuthorityHandleV1
from .agent.planning_contracts import DeploymentIdentityResolverV1
from .agent.orchestrator import AgentNotebookCompilerV1
from .agent.trace import TraceSchemaDescriptor, register_trace_catalog
from .api_errors import register_error_handlers
from .capability_factory.notebook_catalog import CapabilityBindingCatalog
from .capability_factory.notebook_bridge import AuthorizedCapabilityExecutionGateway
from .capability_factory.dependency_service import DependencyService
from .capability_factory.runtime import CapabilityFactoryRuntime, DependencyAdmissionGate
from .capability_factory.trace_contracts import trace_catalog as capability_trace_catalog
from .control_plane import control_plane_capability, validate_control_plane
from .domain_memory.local_runtime import (
    LocalDomainMemoryRuntime,
    LocalDomainMemoryRuntimeError,
    bootstrap_local_domain_memory_runtime,
)
from .domain_memory.service import DomainMemoryService
from .domain_memory.review_service import MemoryReviewService
from .domain_memory.trace_contracts import (
    _DOMAIN_EVENT_FIELDS as _DOMAIN_MEMORY_EVENT_FIELDS,
    _EVENT_FIELDS as _PROJECT_MEMORY_EVENT_FIELDS,
)
from .native_containment.trace_contracts import _EVENT_FIELDS as _CONTAINMENT_EVENT_FIELDS
from .services.execution_profile import current_execution_profile
from .services.results_service import (
    ServerOwnedReportEvidencePersistenceV1,
    UnavailableReportEvidenceCapabilityV1,
    configure_report_evidence_persistence,
)
from .http.agent_routes import (
    configure_agent_notebook_cutover_authority,
    new_agent_notebook_cutover_authority_store,
    router as agent_router,
    set_default_agent_notebook_cutover_authority_store,
)
from .http.drafts_routes import router as drafts_router
from .http.data_operation_routes import router as data_operation_router
from .http.graph_routes import router as graph_router
from .http.llm_routes import router as llm_router
from .http.memory_routes import router as memory_router
from .http.notebook_routes import router as notebook_router
from .http.projects_routes import router as projects_router
from .http.rerun_routes import router as rerun_router
from .http.runs_routes import router as runs_router
from .http.statistical_exploration_routes import router as statistical_exploration_router

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _validate_supported_deployment()
    persistence = getattr(
        _app.state,
        "report_evidence_persistence",
        None,
    )
    if persistence is None:
        # ``None`` means that the deployment did not inject the host-issued
        # capability.  Only at this explicit capability check do we produce a
        # typed unavailable result; the application state never advertises the
        # unavailable sentinel as its default product owner.
        persistence = UnavailableReportEvidenceCapabilityV1()
    if type(persistence) not in {
        ServerOwnedReportEvidencePersistenceV1,
        UnavailableReportEvidenceCapabilityV1,
    }:
        raise TypeError(
            "report_evidence_persistence must be a server-owned C0 capability"
        )
    _app.state.report_evidence_persistence = persistence
    configure_report_evidence_persistence(persistence)
    try:
        yield
    finally:
        configure_report_evidence_persistence(None)
        # After shutdown, retain only the typed bootstrap result.  The
        # pre-start state remains empty and therefore cannot be mistaken for a
        # configured product owner.
        _app.state.report_evidence_persistence = (
            persistence
            if type(persistence) is UnavailableReportEvidenceCapabilityV1
            else UnavailableReportEvidenceCapabilityV1("EVIDENCE_HOST_AUTHORITY_CLOSED")
        )


app = FastAPI(title="Local Econometrics Workbench", lifespan=_lifespan)
register_error_handlers(app)
app.state.notebook_capability_bindings = None
app.state.notebook_execution_gateway = None
app.state.agent_notebook_cutover_store = new_agent_notebook_cutover_authority_store()
# Direct route-function compatibility calls and real HTTP requests point at
# this same object. There is no second authority or confirmation map.
set_default_agent_notebook_cutover_authority_store(app.state.agent_notebook_cutover_store)
app.state.notebook_cutover_identity_resolver = None
# The deployment host must inject a real C0 owner before lifespan startup.
# Keep the pre-start state empty so an unavailable result cannot masquerade as
# the product's default persistence owner.
app.state.report_evidence_persistence = None
app.state.report_evidence_identity_resolver = None
app.state.capability_factory_runtime = None
app.state.domain_memory_service = None
app.state.domain_memory_review_service = None
app.state.domain_memory_context_provider = None
app.state.domain_memory_runtime = None
app.state.domain_memory_bootstrap_error = None
app.state.domain_memory_mutations_enabled = False


def _bootstrap_app(app_instance: FastAPI | None) -> FastAPI:
    target = app if app_instance is None else app_instance
    if not isinstance(target, FastAPI):
        raise TypeError("app_instance must be a FastAPI instance")
    if type(getattr(target.state, "agent_notebook_cutover_store", None)) is not type(
        app.state.agent_notebook_cutover_store
    ):
        target.state.agent_notebook_cutover_store = new_agent_notebook_cutover_authority_store()
    if not hasattr(target.state, "notebook_cutover_identity_resolver"):
        target.state.notebook_cutover_identity_resolver = None
    if not hasattr(target.state, "report_evidence_persistence"):
        target.state.report_evidence_persistence = None
    if not hasattr(target.state, "report_evidence_identity_resolver"):
        target.state.report_evidence_identity_resolver = None
    return target


def configure_report_evidence_owner(
    persistence: ServerOwnedReportEvidencePersistenceV1 | UnavailableReportEvidenceCapabilityV1 | None,
    *,
    identity_resolver: Callable[..., object] | None = None,
    app_instance: FastAPI | None = None,
) -> None:
    """Install the server-owned C0 Report capability and request identity seam."""

    target = _bootstrap_app(app_instance)
    if persistence is not None and type(persistence) not in {
        ServerOwnedReportEvidencePersistenceV1,
        UnavailableReportEvidenceCapabilityV1,
    }:
        raise TypeError(
            "persistence must be a server-owned Report capability or None"
        )
    if identity_resolver is not None and not callable(identity_resolver):
        raise TypeError("identity_resolver must be callable or None")
    target.state.report_evidence_persistence = persistence
    target.state.report_evidence_identity_resolver = identity_resolver


def register_v183_trace_catalogs() -> None:
    """Register package-owned event fields before the app serves requests."""

    register_trace_catalog("capability_factory", capability_trace_catalog())
    register_trace_catalog(
        "native_containment",
        _trace_descriptors(_CONTAINMENT_EVENT_FIELDS),
    )
    memory_fields = {
        **_PROJECT_MEMORY_EVENT_FIELDS,
        **_DOMAIN_MEMORY_EVENT_FIELDS,
    }
    # Core Agent Trace owns this Notebook retrieval envelope and adds the
    # bounded preference/count fields. The package-local builder remains a
    # compatibility contract, but it must not claim a second persisted schema.
    memory_fields.pop("domain_memory.retrieval.completed", None)
    register_trace_catalog("domain_memory", _trace_descriptors(memory_fields))


def _trace_descriptors(
    fields: dict[str, frozenset[str]],
) -> dict[str, TraceSchemaDescriptor]:
    return {
        event_type: TraceSchemaDescriptor(
            payload_schema=event_type.replace(".", "-").replace("_", "-") + "/v1",
            required=tuple(sorted(event_fields)),
        )
        for event_type, event_fields in fields.items()
    }


# Trace event ownership is application bootstrap, not a request-time extension
# point.  Persisted traces therefore have one collision-checked vocabulary in
# every process that imports the Workbench app.
register_v183_trace_catalogs()


def configure_notebook_capability_bindings(
    catalog: CapabilityBindingCatalog | None,
) -> None:
    """Install the server-owned Notebook binding catalog for this app.

    This is an application bootstrap seam, not an HTTP operation.  Authority
    construction and registration remain outside the Notebook/Agent route;
    the route can only consume an already-created catalog or the legacy native
    path when no catalog is configured.
    """

    if catalog is not None and not isinstance(catalog, CapabilityBindingCatalog):
        raise TypeError("catalog must be a CapabilityBindingCatalog or None")
    app.state.capability_factory_runtime = None
    app.state.notebook_capability_bindings = catalog


def configure_agent_notebook_runtime(
    *,
    project_ref: str,
    session_ref: str,
    compiler: AgentNotebookCompilerV1 | None,
    app_instance: FastAPI | None = None,
) -> None:
    """Install one server-owned Agent/Notebook compiler at application bootstrap.

    The HTTP route retains only the exact project/session binding.  Passing
    ``None`` removes that binding and its retained confirmation handles.
    """

    target = _bootstrap_app(app_instance)
    if compiler is not None and type(compiler) is not AgentNotebookCompilerV1:
        raise TypeError("compiler must be an AgentNotebookCompilerV1 or None")
    if compiler is not None and not callable(getattr(compiler, "evidence_committer", None)):
        raise ValueError("compiler must have a server-owned evidence committer")
    configure_agent_notebook_cutover_authority(
        project_ref=project_ref,
        session_ref=session_ref,
        compiler=compiler,
        app_instance=target,
    )


def configure_notebook_cutover_identity_resolver(
    resolver: Callable[..., tuple[str, str] | tuple[str, str, str]] | None,
    *,
    app_instance: FastAPI | None = None,
) -> None:
    """Install the server-owned identity/session binding for Notebook cutover.

    The resolver is supplied by the host authentication/session layer and is
    called as ``resolver(request, project_ref, claimed_session_ref, notebook_id)``.
    Notebook and Agent requests may only assert the returned actor/session;
    they cannot mint either identity themselves.
    """

    target = _bootstrap_app(app_instance)
    if resolver is not None and not callable(resolver):
        raise TypeError("resolver must be callable or None")
    target.state.notebook_cutover_identity_resolver = resolver


def configure_agent_notebook_runtime_bundle(
    *,
    project_ref: str,
    session_ref: str,
    runtime: AgentNotebookRuntimeV1 | None,
    app_instance: FastAPI | None = None,
) -> None:
    """Install or remove a composed runtime bundle for one exact scope."""

    if runtime is not None and type(runtime) is not AgentNotebookRuntimeV1:
        raise TypeError("runtime must be an AgentNotebookRuntimeV1 or None")
    configure_agent_notebook_runtime(
        project_ref=project_ref,
        session_ref=session_ref,
        compiler=None if runtime is None else runtime.compiler,
        app_instance=app_instance,
    )


def bootstrap_builtin_agent_notebook_runtime(
    *,
    project_ref: str,
    session_ref: str,
    provider_catalog: Any,
    evidence_committer: Any,
    host_compiler: Any,
    data_project_root: Path | str | None = None,
    data_consumer_execution_port: Any | None = None,
    classification_execution_port: Any | None = None,
    ttl_seconds: int = 900,
    clock: Callable[[], Any] | None = None,
    app_instance: FastAPI | None = None,
) -> AgentNotebookRuntimeV1:
    """Compose and install one shared Agent/Notebook runtime for a scope.

    This is application bootstrap only.  HTTP callers cannot invoke it, and
    no default catalog, evidence owner, host compiler, or executor is created
    when a deployment omits one of those authorities.
    """

    target = _bootstrap_app(app_instance)
    from .agent.runtime_bootstrap import compose_builtin_agent_notebook_runtime

    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=provider_catalog,
        evidence_committer=evidence_committer,
        host_compiler=host_compiler,
        project_ref=project_ref,
        session_ref=session_ref,
        data_project_root=data_project_root,
        data_consumer_execution_port=data_consumer_execution_port,
        classification_execution_port=classification_execution_port,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )
    configure_agent_notebook_runtime_bundle(
        project_ref=project_ref,
        session_ref=session_ref,
        runtime=runtime,
        app_instance=target,
    )
    return runtime


def bootstrap_builtin_agent_notebook_host(
    *,
    project_ref: str,
    session_ref: str,
    provider_catalog: Any,
    evidence_committer: Any,
    host_compiler: Any,
    report_evidence_persistence: ServerOwnedReportEvidencePersistenceV1
    | UnavailableReportEvidenceCapabilityV1,
    notebook_identity_resolver: DeploymentIdentityResolverV1,
    report_identity_resolver: Callable[..., object] | None = None,
    data_project_root: Path | str | None = None,
    data_consumer_execution_port: Any | None = None,
    classification_execution_port: Any | None = None,
    ttl_seconds: int = 900,
    clock: Callable[[], Any] | None = None,
    app_instance: FastAPI | None = None,
) -> AgentNotebookRuntimeV1:
    """Atomically install the server-owned Agent/Notebook host bundle.

    This is the production host boundary.  All authorities are supplied by
    the embedding service; neither HTTP callers nor this function infer a
    provider, identity, persistence root, or project scope.  Composition is
    deliberately completed before application state is touched.  The explicit
    unavailable Report capability is accepted as a typed fail-closed choice;
    production deployments that expose Report must inject a real C0 owner.
    """

    if type(project_ref) is not str or not project_ref.strip() or "\x00" in project_ref:
        raise ValueError("project_ref must be a non-empty scope reference")
    if type(session_ref) is not str or not session_ref.strip() or "\x00" in session_ref:
        raise ValueError("session_ref must be a non-empty scope reference")
    if type(report_evidence_persistence) not in {
        ServerOwnedReportEvidencePersistenceV1,
        UnavailableReportEvidenceCapabilityV1,
    }:
        raise TypeError(
            "report_evidence_persistence must be a server-owned Report capability"
        )
    if type(notebook_identity_resolver) is not DeploymentIdentityResolverV1:
        raise ValueError(
            "notebook_identity_resolver must be a deployment identity resolver"
        )
    if report_identity_resolver is not None and not callable(report_identity_resolver):
        raise ValueError("report_identity_resolver must be callable or None")

    # Build the whole runtime before touching the app.  A bad catalog join,
    # missing evidence committer, or missing host compiler therefore cannot
    # leave behind an apparently configured identity or Report owner.
    from .agent.runtime_bootstrap import compose_builtin_agent_notebook_runtime

    runtime = compose_builtin_agent_notebook_runtime(
        provider_catalog=provider_catalog,
        evidence_committer=evidence_committer,
        host_compiler=host_compiler,
        project_ref=project_ref,
        session_ref=session_ref,
        data_project_root=data_project_root,
        data_consumer_execution_port=data_consumer_execution_port,
        classification_execution_port=classification_execution_port,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )

    target = _bootstrap_app(app_instance)
    store = target.state.agent_notebook_cutover_store
    store_fields = (
        "authorities",
        "confirmations",
        "confirmation_digests",
        "confirmation_authorities",
        "confirmation_receipts",
        "confirmation_serializations",
        "legacy_proposal_bindings",
    )
    previous_state = {
        "report_evidence_persistence": getattr(
            target.state, "report_evidence_persistence", None
        ),
        "report_evidence_identity_resolver": getattr(
            target.state, "report_evidence_identity_resolver", None
        ),
        "notebook_cutover_identity_resolver": getattr(
            target.state, "notebook_cutover_identity_resolver", None
        ),
        "store": store,
        "store_fields": {
            name: dict(getattr(store, name))
            for name in store_fields
        },
    }
    try:
        target.state.report_evidence_persistence = report_evidence_persistence
        target.state.report_evidence_identity_resolver = report_identity_resolver
        target.state.notebook_cutover_identity_resolver = notebook_identity_resolver
        configure_agent_notebook_runtime_bundle(
            project_ref=project_ref,
            session_ref=session_ref,
            runtime=runtime,
            app_instance=target,
        )
    except Exception:
        target.state.report_evidence_persistence = previous_state[
            "report_evidence_persistence"
        ]
        target.state.report_evidence_identity_resolver = previous_state[
            "report_evidence_identity_resolver"
        ]
        target.state.notebook_cutover_identity_resolver = previous_state[
            "notebook_cutover_identity_resolver"
        ]
        for name, snapshot in previous_state["store_fields"].items():
            current = getattr(store, name)
            current.clear()
            current.update(snapshot)
        raise
    return runtime


def build_deployment_agent_notebook_identity_resolver(
    *,
    host_authority_handle: HostAuthorityHandleV1 | None,
    authenticated_identity_resolver: Callable[..., object] | None,
) -> DeploymentIdentityResolverV1:
    """Build the application resolver over an admitted external authority.

    The deployment callback observes authenticated request identity only. The
    returned resolver asks the external authority to issue and revalidate the
    exact scope on every request; no local binding or request assertion is
    promoted to authority.
    """

    if type(host_authority_handle) is not HostAuthorityHandleV1:
        raise ValueError("host authority handle must be a deployment-admitted handle")
    if not callable(authenticated_identity_resolver):
        raise ValueError("authenticated_identity_resolver must be callable")
    return DeploymentIdentityResolverV1.from_host_handle(
        host_authority_handle,
        authenticated_identity_resolver,
    )


def bootstrap_builtin_agent_notebook_host_from_deployment(
    *,
    host_authority_handle: HostAuthorityHandleV1 | None,
    authenticated_identity_resolver: Callable[..., object] | None,
    project_ref: str,
    session_ref: str,
    provider_catalog: Any,
    evidence_committer: Any,
    host_compiler: Any,
    report_evidence_persistence: ServerOwnedReportEvidencePersistenceV1
    | UnavailableReportEvidenceCapabilityV1,
    report_identity_resolver: Callable[..., object] | None = None,
    data_project_root: Path | str | None = None,
    data_consumer_execution_port: Any | None = None,
    classification_execution_port: Any | None = None,
    ttl_seconds: int = 900,
    clock: Callable[[], Any] | None = None,
    app_instance: FastAPI | None = None,
) -> AgentNotebookRuntimeV1:
    """Bootstrap the shared host bundle with an external identity authority."""

    identity_resolver = build_deployment_agent_notebook_identity_resolver(
        host_authority_handle=host_authority_handle,
        authenticated_identity_resolver=authenticated_identity_resolver,
    )
    return bootstrap_builtin_agent_notebook_host(
        project_ref=project_ref,
        session_ref=session_ref,
        provider_catalog=provider_catalog,
        evidence_committer=evidence_committer,
        host_compiler=host_compiler,
        report_evidence_persistence=report_evidence_persistence,
        notebook_identity_resolver=identity_resolver,
        report_identity_resolver=report_identity_resolver,
        data_project_root=data_project_root,
        data_consumer_execution_port=data_consumer_execution_port,
        classification_execution_port=classification_execution_port,
        ttl_seconds=ttl_seconds,
        clock=clock,
        app_instance=app_instance,
    )


def configure_notebook_execution_gateway(gateway: object | None) -> None:
    """Clear the legacy gateway slot; production installation is runtime-only.

    ``None`` is the normal fail-closed configuration on hosts without a
    verified containment/supervisor stack.  The HTTP layer never constructs a
    gateway or falls back to in-process execution.  A non-``None`` gateway
    must be installed through ``configure_capability_factory_runtime`` so the
    server-owned dependency admission gate and authority identity cannot be
    omitted.
    """

    if gateway is not None and not isinstance(gateway, AuthorizedCapabilityExecutionGateway):
        raise TypeError("gateway must be an AuthorizedCapabilityExecutionGateway or None")
    if gateway is not None:
        raise ValueError(
            "gateway must be installed through configure_capability_factory_runtime"
        )
    app.state.capability_factory_runtime = None
    app.state.notebook_execution_gateway = gateway


def configure_capability_factory_runtime(
    runtime: CapabilityFactoryRuntime | None,
) -> None:
    """Install the complete server-owned factory seam atomically.

    Deployment code calls this once after constructing the catalog and the
    already-authorized gateway. The HTTP layer never receives a binding loader,
    signer, dependency receipt, or executor constructor.
    """

    if runtime is not None and not isinstance(runtime, CapabilityFactoryRuntime):
        raise TypeError("runtime must be a CapabilityFactoryRuntime or None")
    if runtime is not None:
        runtime.validate_for_bootstrap()
    app.state.capability_factory_runtime = runtime
    app.state.notebook_capability_bindings = runtime.catalog if runtime else None
    app.state.notebook_execution_gateway = runtime.execution_gateway if runtime else None


def configure_local_experimental_capability_runtime(
    *,
    authority_id: str,
    catalog: CapabilityBindingCatalog,
    dependency_service: DependencyService,
    binding_factory: Callable[..., Any],
    result_sink: Callable[[Any], None] | None = None,
    enable: bool,
) -> CapabilityFactoryRuntime:
    """Explicitly install the local Darwin experimental execution profile.

    This is a deployment/bootstrap operation, never an HTTP operation. The
    caller must deliberately pass ``enable=True`` and provide server-owned
    catalog, dependency service, and per-attempt binding factory objects. The
    gateway still enforces the fixed experimental profile, the high-risk
    ``model.custom`` mode, dependency admission, and the native canary before
    any reservation or process spawn. There is no default or weaker fallback.
    """

    if enable is not True:
        raise ValueError(
            "local experimental capability execution requires enable=True"
        )
    if not isinstance(catalog, CapabilityBindingCatalog):
        raise TypeError("catalog must be a CapabilityBindingCatalog")
    if not isinstance(dependency_service, DependencyService):
        raise TypeError("dependency_service must be a DependencyService")
    if not callable(getattr(dependency_service.supply_chain_verifier, "verify", None)):
        raise ValueError(
            "local experimental capability execution requires a configured supply-chain verifier"
        )
    if not callable(binding_factory):
        raise TypeError("binding_factory must be callable")
    gateway = AuthorizedCapabilityExecutionGateway(
        binding_factory=binding_factory,
        result_sink=result_sink,
        dependency_binding_validator=DependencyAdmissionGate(dependency_service),
    )
    runtime = CapabilityFactoryRuntime(
        authority_id=authority_id,
        catalog=catalog,
        execution_gateway=gateway,
        dependency_service=dependency_service,
    )
    configure_capability_factory_runtime(runtime)
    return runtime


def configure_deployment_capability_factory_runtime(
    *,
    authority: Any,
    dependency_service: DependencyService,
    binding_factory: Callable[..., Any],
    report_attestation_source: Any,
    attestation_binding: Any,
    result_sink: Callable[[Any], None] | None = None,
) -> CapabilityFactoryRuntime:
    """Atomically install a deployment-provided authority and scanner runtime.

    This accepts only deployment ports.  It never manufactures signing keys,
    allows unsigned containment reports, or replaces an absent scanner with a
    local fallback.  The per-attempt binding factory receives an authenticated
    report verifier and must mount it in its B1 broker.
    """

    from .capability_factory.deployment_authority import (
        build_deployment_capability_factory_runtime,
    )

    runtime = build_deployment_capability_factory_runtime(
        authority=authority,
        dependency_service=dependency_service,
        binding_factory=binding_factory,
        report_attestation_source=report_attestation_source,
        attestation_binding=attestation_binding,
        result_sink=result_sink,
    )
    configure_capability_factory_runtime(runtime)
    return runtime


def configure_domain_memory_services(
    service: DomainMemoryService | None,
    review_service: MemoryReviewService | None,
) -> None:
    """Install server-owned domain-memory control-plane services.

    This is application bootstrap only. The HTTP adapter cannot construct a
    scope, open a store, or promote a candidate on its own.
    """

    if service is not None and not isinstance(service, DomainMemoryService):
        raise TypeError("service must be a DomainMemoryService or None")
    if review_service is not None and not isinstance(review_service, MemoryReviewService):
        raise TypeError("review_service must be a MemoryReviewService or None")
    app.state.domain_memory_service = service
    app.state.domain_memory_review_service = review_service


def bootstrap_local_domain_memory_services() -> LocalDomainMemoryRuntime | None:
    """Install the empty local memory library or leave memory fail-closed.

    A failure is intentionally non-fatal to the rest of Workbench: Notebook
    analysis keeps working without memory, while the memory routes and any
    explicit opt-in receive the existing unavailable response.
    """

    try:
        runtime = bootstrap_local_domain_memory_runtime()
    except LocalDomainMemoryRuntimeError:
        app.state.domain_memory_runtime = None
        app.state.domain_memory_bootstrap_error = "DOMAIN_MEMORY_LOCAL_RUNTIME_UNAVAILABLE"
        configure_domain_memory_services(None, None)
        return None
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_bootstrap_error = None
    configure_domain_memory_services(runtime.service, runtime.review_service)
    return runtime


def configure_domain_memory_context_provider(provider: object | None) -> None:
    """Install a server-owned Notebook memory projection provider.

    The callable receives the request-owned Notebook inputs and returns the
    already bounded ``domain-memory-context-input/v1`` projection. A missing
    provider is a deliberate fail-closed no-memory configuration.
    """

    if provider is not None and not callable(provider):
        raise TypeError("provider must be callable or None")
    app.state.domain_memory_context_provider = provider


def _validate_supported_deployment() -> None:
    validate_control_plane()
    current_execution_profile()
    if (
        getattr(app.state, "domain_memory_service", None) is None
        and getattr(app.state, "domain_memory_review_service", None) is None
    ):
        bootstrap_local_domain_memory_services()
    runtime = getattr(app.state, "capability_factory_runtime", None)
    if runtime is not None:
        runtime.validate_for_bootstrap()


@app.get("/health")
def health() -> dict[str, object]:
    runtime = getattr(app.state, "capability_factory_runtime", None)
    return {
        "status": "ok",
        **control_plane_capability(),
        "execution_profile": current_execution_profile().profile,
        **{
            key: value
            for key, value in current_execution_profile().public_status().items()
            if key != "profile"
        },
        "capability_factory": (
            runtime.public_status()
            if isinstance(runtime, CapabilityFactoryRuntime)
            else {
                "configured": False,
                "catalog_configured": False,
                "execution_gateway_configured": False,
                "dependency_gate_configured": False,
            }
        ),
    }

app.include_router(projects_router)
app.include_router(runs_router)
app.include_router(statistical_exploration_router)
app.include_router(graph_router)
app.include_router(drafts_router)
app.include_router(data_operation_router)
app.include_router(agent_router)
app.include_router(notebook_router)
app.include_router(rerun_router)
app.include_router(llm_router)
app.include_router(memory_router)
