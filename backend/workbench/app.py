"""FastAPI application assembly.

Owns the single ``app`` instance and error-handler registration. Route clusters
live in ``http/*_routes.py`` as ``APIRouter``s and are mounted here via
``include_router``. ``api.py`` re-exports this ``app`` (uvicorn target
``workbench.api:app``) and, during the v1.6.10 D1 router migration, still attaches
the not-yet-migrated routes onto it.

Extracted from ``api.py`` in v1.6.10 (D1 decomposition, Phase 4).
"""
from __future__ import annotations

from fastapi import FastAPI

from .api_errors import register_error_handlers
from .capability_factory.notebook_catalog import CapabilityBindingCatalog
from .capability_factory.notebook_bridge import AuthorizedCapabilityExecutionGateway
from .capability_factory.runtime import CapabilityFactoryRuntime
from .control_plane import control_plane_capability, validate_control_plane
from .domain_memory.service import DomainMemoryService
from .domain_memory.review_service import MemoryReviewService
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
