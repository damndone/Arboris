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
from typing import Any

from fastapi import FastAPI

from .agent.trace import TraceSchemaDescriptor, register_trace_catalog
from .api_errors import register_error_handlers
from .capability_factory.notebook_catalog import CapabilityBindingCatalog
from .capability_factory.notebook_bridge import AuthorizedCapabilityExecutionGateway
from .capability_factory.dependency_service import DependencyService
from .capability_factory.runtime import CapabilityFactoryRuntime, DependencyAdmissionGate
from .capability_factory.trace_contracts import trace_catalog as capability_trace_catalog
from .control_plane import control_plane_capability, validate_control_plane
from .domain_memory.service import DomainMemoryService
from .domain_memory.review_service import MemoryReviewService
from .domain_memory.trace_contracts import (
    _DOMAIN_EVENT_FIELDS as _DOMAIN_MEMORY_EVENT_FIELDS,
    _EVENT_FIELDS as _PROJECT_MEMORY_EVENT_FIELDS,
)
from .native_containment.trace_contracts import _EVENT_FIELDS as _CONTAINMENT_EVENT_FIELDS
from .services.execution_profile import current_execution_profile
from .http.agent_routes import router as agent_router
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

app = FastAPI(title="Local Econometrics Workbench")
register_error_handlers(app)
app.state.notebook_capability_bindings = None
app.state.notebook_execution_gateway = None
app.state.capability_factory_runtime = None
app.state.domain_memory_service = None
app.state.domain_memory_review_service = None
app.state.domain_memory_context_provider = None


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


def configure_domain_memory_context_provider(provider: object | None) -> None:
    """Install a server-owned Notebook memory projection provider.

    The callable receives the request-owned Notebook inputs and returns the
    already bounded ``domain-memory-context-input/v1`` projection. A missing
    provider is a deliberate fail-closed no-memory configuration.
    """

    if provider is not None and not callable(provider):
        raise TypeError("provider must be callable or None")
    app.state.domain_memory_context_provider = provider


@app.on_event("startup")
def _validate_supported_deployment() -> None:
    validate_control_plane()
    current_execution_profile()
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
