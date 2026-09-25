"""Explicit server bootstrap for the shared Agent/Notebook runtime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from workbench.agent.cutover_runtime import (
    AgentNotebookRuntimeV1,
    EvidenceCommitterV1,
    compose_agent_notebook_runtime,
)
from workbench.agent.provider_runtime_contributions import (
    ProviderRuntimeCompositionError,
    build_builtin_runtime_contributions,
)
from workbench.providers.catalog import ProviderCatalogV1


RuntimeBootstrapError = ProviderRuntimeCompositionError


def compose_builtin_agent_notebook_runtime(
    *,
    provider_catalog: ProviderCatalogV1,
    evidence_committer: EvidenceCommitterV1 | None,
    host_compiler: Any | None,
    project_ref: str | None = None,
    session_ref: str | None = None,
    data_project_root: Path | str | None = None,
    data_consumer_execution_port: Any | None = None,
    classification_execution_port: Any | None = None,
    workflow_post_estimation_execution_port: Any | None = None,
    ttl_seconds: int = 900,
    clock: Callable[[], Any] | None = None,
) -> AgentNotebookRuntimeV1:
    """Compose one shared runtime from explicit host-owned dependencies."""

    if evidence_committer is None:
        raise RuntimeBootstrapError(
            "RUNTIME_EVIDENCE_COMMITTER_REQUIRED",
            "server evidence persistence must be injected before bootstrap",
        )
    if host_compiler is None or not callable(getattr(host_compiler, "compile", None)):
        raise RuntimeBootstrapError(
            "RUNTIME_HOST_COMPILER_REQUIRED",
            "a host compilation authority must be injected before bootstrap",
        )
    if data_project_root is not None:
        if project_ref is None or session_ref is None:
            raise RuntimeBootstrapError(
                "RUNTIME_DATA_SCOPE_REQUIRED",
                "data_project_root requires the exact project_ref and session_ref",
            )
        if data_consumer_execution_port is not None:
            raise RuntimeBootstrapError(
                "RUNTIME_DATA_PORT_DUPLICATE",
                "supply data_project_root or a data execution port, not both",
            )
        from workbench.services.data_consumer_host_resolver import (
            build_server_owned_data_consumer_execution_port,
        )

        data_consumer_execution_port = build_server_owned_data_consumer_execution_port(
            project_root=data_project_root,
            project_ref=project_ref,
            session_ref=session_ref,
            catalog_digest=provider_catalog.catalog_digest,
        )
    contributions = build_builtin_runtime_contributions(
        provider_catalog,
        data_consumer_execution_port=data_consumer_execution_port,
        classification_execution_port=classification_execution_port,
        workflow_post_estimation_execution_port=workflow_post_estimation_execution_port,
    )
    return compose_agent_notebook_runtime(
        provider_catalog=provider_catalog,
        contributions=contributions,
        evidence_committer=evidence_committer,
        host_compiler=host_compiler,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )


__all__ = [
    "RuntimeBootstrapError",
    "build_builtin_runtime_contributions",
    "compose_builtin_agent_notebook_runtime",
]
