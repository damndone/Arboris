"""Server-owned builtin provider/runtime composition for v1.8.9.

Manifest JSON is declaration-only.  This module is the narrow composition
seam that joins those declarations to package-owned callables.  Providers
without a verified execution implementation are represented explicitly as a
blocked contribution; they can be discovered and explained, but cannot
silently execute or produce a fake result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from workbench.agent.trusted_executor_registry import (
    ProviderRuntimeContributionV1,
    ProviderRuntimeContextV1,
    TrustedExecutorRegistryError,
)
from workbench.contracts.common.provider import AdapterDeclarationV1, ProviderContributionV1
from workbench.providers.catalog import (
    ProviderCatalogV1,
    is_server_owned_catalog,
)


class ProviderRuntimeCompositionError(TrustedExecutorRegistryError):
    """A builtin declaration/code join could not be composed safely."""


def _blocked_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only the generic shape; dispatch is blocked before invocation."""

    if not isinstance(request, Mapping):
        raise ProviderRuntimeCompositionError("RUNTIME_REQUEST_REQUIRED")
    return dict(request)


def _blocked_result(_result: Mapping[str, Any]) -> None:
    raise ProviderRuntimeCompositionError("RUNTIME_EXECUTION_BLOCKED")


def _blocked_executor(
    _context: ProviderRuntimeContextV1,
    _request: Mapping[str, Any],
) -> Mapping[str, Any]:
    raise ProviderRuntimeCompositionError("RUNTIME_EXECUTION_BLOCKED")


def _blocked_contribution(
    provider: ProviderContributionV1,
    declaration: AdapterDeclarationV1,
) -> ProviderRuntimeContributionV1:
    return ProviderRuntimeContributionV1(
        provider_id=provider.provider_id,
        adapter_id=declaration.adapter_id,
        executor_ref=declaration.executor_ref,
        owner="workbench.server.bootstrap.blocked",
        signature="workbench.server.bootstrap.blocked.v1",
        effect="read_only",
        request_contract_ref=declaration.request_schema_ref,
        result_contract_refs=declaration.output_refs,
        executor=_blocked_executor,
        request_validator=_blocked_request,
        result_validator=_blocked_result,
        execution_allowed=False,
        metadata={
            "status": "unavailable",
            "reason_code": "RUNTIME_PROVIDER_IMPLEMENTATION_UNAVAILABLE",
            "provider_id": provider.provider_id,
            "adapter_id": declaration.adapter_id,
        },
    )


def _package_contribution(
    provider_catalog: ProviderCatalogV1,
    provider: ProviderContributionV1,
    declaration: AdapterDeclarationV1,
    *,
    data_consumer_execution_port: object | None = None,
    classification_execution_port: object | None = None,
    workflow_post_estimation_execution_port: object | None = None,
) -> ProviderRuntimeContributionV1 | None:
    if declaration.executor_ref == "executor:workbench.data_consumer.adapter":
        from workbench.data_operation_manifest import build_data_consumer_runtime_contribution

        return build_data_consumer_runtime_contribution(
            provider_catalog,
            execution_port=data_consumer_execution_port,
        )
    if declaration.executor_ref == "executor:workbench.classification_ml.adapter":
        from workbench.predictive_research.classification_adapters import (
            build_classification_runtime_contribution,
        )

        try:
            return build_classification_runtime_contribution(
                provider_catalog,
                execution_port=classification_execution_port,
            )
        except TrustedExecutorRegistryError as exc:
            raise ProviderRuntimeCompositionError(exc.code, str(exc)) from exc
    if declaration.executor_ref.startswith("executor:workflow.post_estimation."):
        from workbench.services.workflow_post_estimation_host import (
            build_workflow_post_estimation_runtime_contribution,
        )

        try:
            return build_workflow_post_estimation_runtime_contribution(
                provider,
                declaration,
                catalog_digest=provider_catalog.catalog_digest,
                execution_port=workflow_post_estimation_execution_port,
            )
        except TrustedExecutorRegistryError as exc:
            if workflow_post_estimation_execution_port is None:
                return None
            raise ProviderRuntimeCompositionError(exc.code, str(exc)) from exc
    return None


def build_builtin_runtime_contributions(
    provider_catalog: ProviderCatalogV1,
    *,
    data_consumer_execution_port: object | None = None,
    classification_execution_port: object | None = None,
    workflow_post_estimation_execution_port: object | None = None,
) -> tuple[ProviderRuntimeContributionV1, ...]:
    """Build exactly one trusted contribution for every live adapter declaration.

    The catalog itself remains the authority for identity and contract refs.
    A forged value-object clone, duplicate declaration, or package factory that
    returns an identity different from the declaration fails before composition.
    """

    if type(provider_catalog) is not ProviderCatalogV1 or not is_server_owned_catalog(provider_catalog):
        raise ProviderRuntimeCompositionError(
            "RUNTIME_PROVIDER_CATALOG_REQUIRED",
            "runtime composition requires the exact server-loaded provider catalog",
        )

    contributions: list[ProviderRuntimeContributionV1] = []
    for provider in provider_catalog.providers:
        if type(provider) is not ProviderContributionV1:
            raise ProviderRuntimeCompositionError("RUNTIME_CATALOG_INVALID")
        for declaration in provider.adapter_declarations:
            if type(declaration) is not AdapterDeclarationV1:
                raise ProviderRuntimeCompositionError("RUNTIME_ADAPTER_DECLARATION_INVALID")
            contribution = _package_contribution(
                provider_catalog,
                provider,
                declaration,
                data_consumer_execution_port=data_consumer_execution_port,
                classification_execution_port=classification_execution_port,
                workflow_post_estimation_execution_port=workflow_post_estimation_execution_port,
            )
            contributions.append(
                contribution
                if contribution is not None
                else _blocked_contribution(provider, declaration)
            )

    refs = [contribution.executor_ref for contribution in contributions]
    if len(refs) != len(set(refs)):
        raise ProviderRuntimeCompositionError("RUNTIME_DUPLICATE_EXECUTOR")
    return tuple(sorted(contributions, key=lambda item: item.executor_ref))


__all__ = [
    "ProviderRuntimeCompositionError",
    "build_builtin_runtime_contributions",
]
