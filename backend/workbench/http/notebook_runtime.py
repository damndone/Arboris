"""HTTP-owned Notebook runtime assembly shared by Agent and Notebook routes."""
from ..agent.notebook import NotebookService
from ..capability_factory.notebook_catalog import CapabilityBindingCatalog
from ..capability_factory.notebook_bridge import AuthorizedCapabilityExecutionGateway
from ..api_errors import WorkbenchAPIError


def notebook_service_from_state(root, state):
    runtime = getattr(state, "capability_factory_runtime", None)
    catalog = (
        runtime.catalog
        if runtime is not None
        else getattr(state, "notebook_capability_bindings", None)
    )
    if catalog is not None and not isinstance(catalog, CapabilityBindingCatalog):
        raise WorkbenchAPIError(
            status_code=500,
            code="NOTEBOOK_CAPABILITY_BINDING_PROVIDER_INVALID",
            message="The server-owned Notebook capability binding provider is invalid.",
        )
    gateway = (
        runtime.execution_gateway
        if runtime is not None
        else getattr(state, "notebook_execution_gateway", None)
    )
    if gateway is not None and not isinstance(gateway, AuthorizedCapabilityExecutionGateway):
        raise WorkbenchAPIError(
            status_code=500,
            code="NOTEBOOK_EXECUTION_GATEWAY_PROVIDER_INVALID",
            message="The server-owned Notebook execution gateway is invalid.",
        )
    return NotebookService(
        root,
        capability_bindings=catalog,
        execution_gateway=gateway,
    )

