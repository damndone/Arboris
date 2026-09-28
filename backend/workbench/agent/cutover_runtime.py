"""Server-owned composition for the shared Agent/Notebook cutover runtime.

Provider manifests declare opaque executor identities.  This module accepts
the already constructed runtime contributions supplied by application
bootstrap, then delegates the declaration/code join to the existing trusted
registry and cutover capability catalog.  It deliberately has no import-path
or fixture/no-op loading path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.agent.orchestrator import AgentNotebookCompilerV1
from workbench.agent.trusted_executor_registry import (
    ProviderRuntimeContributionV1,
    ProviderRuntimeContextV1,
    TrustedExecutorRegistry,
    TrustedExecutorRegistryError,
)
from workbench.agent.workflow_capability_registry import CutoverCapabilityCatalogV1
from workbench.providers.catalog import ProviderCatalogV1


_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class EvidenceCommitReceiptV1:
    """Typed proof that a server evidence commit completed and is bound.

    The compiler accepts this receipt only after matching every execution
    identity field against its own provider context. A bare ``evidence:...``
    string is intentionally not an admissible completion proof.
    """

    evidence_ref: str
    evidence_digest: str
    compilation_record_id: str
    execution_instance_hash: str
    actor_ref: str
    session_ref: str
    project_ref: str
    persisted: bool = True

    def __post_init__(self) -> None:
        for name in (
            "evidence_ref",
            "compilation_record_id",
            "execution_instance_hash",
            "actor_ref",
            "session_ref",
            "project_ref",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be a non-empty string")
        if not self.evidence_ref.startswith("evidence:"):
            raise ValueError("evidence_ref must use the evidence: namespace")
        if type(self.evidence_digest) is not str or _SHA256.fullmatch(self.evidence_digest) is None:
            raise ValueError("evidence_digest must be a lowercase SHA-256 digest")
        if self.persisted is not True:
            raise ValueError("persisted evidence receipt is required")

    def matches_context(self, context: ProviderRuntimeContextV1) -> bool:
        return (
            type(context) is ProviderRuntimeContextV1
            and self.compilation_record_id == context.compilation_record_id
            and self.execution_instance_hash == context.execution_instance_hash
            and self.actor_ref == context.actor_ref
            and self.session_ref == context.session_ref
            and self.project_ref == context.project_ref
        )

    def matches_result(
        self,
        context: ProviderRuntimeContextV1,
        result: Mapping[str, Any],
    ) -> bool:
        """Bind the receipt digest to the exact server-dispatched result."""

        if not isinstance(result, Mapping):
            return False
        return self.evidence_digest == sha256_canonical(
            {
                "execution_instance_hash": context.execution_instance_hash,
                "result": dict(result),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "evidence-commit-receipt.v1",
            "evidence_ref": self.evidence_ref,
            "evidence_digest": self.evidence_digest,
            "compilation_record_id": self.compilation_record_id,
            "execution_instance_hash": self.execution_instance_hash,
            "actor_ref": self.actor_ref,
            "session_ref": self.session_ref,
            "project_ref": self.project_ref,
            "persisted": self.persisted,
        }


EvidenceCommitterV1 = Callable[
    [ProviderRuntimeContextV1, Mapping[str, Any]],
    EvidenceCommitReceiptV1 | None,
]


@dataclass(frozen=True)
class AgentNotebookRuntimeV1:
    """The immutable-by-convention runtime bundle installed by app bootstrap."""

    provider_catalog: ProviderCatalogV1
    runtime_registry: TrustedExecutorRegistry
    catalog: CutoverCapabilityCatalogV1
    compiler: AgentNotebookCompilerV1


def compose_agent_notebook_runtime(
    *,
    provider_catalog: ProviderCatalogV1,
    contributions: list[ProviderRuntimeContributionV1]
    | tuple[ProviderRuntimeContributionV1, ...],
    evidence_committer: EvidenceCommitterV1 | None,
    ttl_seconds: int = 900,
    clock: Callable[[], Any] | None = None,
) -> AgentNotebookRuntimeV1:
    """Compose one trusted Agent/Notebook runtime from server-owned inputs.

    The caller is responsible for constructing real contributions and their
    callables.  No manifest value is interpreted as Python code, and an empty
    or incomplete contribution set is rejected by the existing one-to-one
    registry/catalog join before a compiler is returned.
    """

    if type(provider_catalog) is not ProviderCatalogV1:
        raise TrustedExecutorRegistryError(
            "RUNTIME_PROVIDER_CATALOG_REQUIRED",
            "provider catalog must be the server-loaded ProviderCatalogV1",
        )
    if evidence_committer is not None and not callable(evidence_committer):
        raise TrustedExecutorRegistryError(
            "RUNTIME_EVIDENCE_COMMITTER_INVALID",
            "evidence committer must be callable",
        )
    if evidence_committer is None:
        raise TrustedExecutorRegistryError(
            "RUNTIME_EVIDENCE_COMMITTER_REQUIRED",
            "evidence committer is required before runtime bootstrap",
        )
    if type(contributions) not in {list, tuple}:
        raise TrustedExecutorRegistryError(
            "RUNTIME_CONTRIBUTIONS_INVALID",
            "bootstrap must provide a list or tuple of runtime contributions",
        )

    runtime_registry = TrustedExecutorRegistry(contributions)
    catalog = CutoverCapabilityCatalogV1.from_provider_catalog(
        provider_catalog,
        runtime_registry,
    )
    compiler = AgentNotebookCompilerV1(
        catalog=catalog,
        runtime_registry=runtime_registry,
        evidence_committer=evidence_committer,
        ttl_seconds=ttl_seconds,
        clock=clock,
    )
    return AgentNotebookRuntimeV1(
        provider_catalog=provider_catalog,
        runtime_registry=runtime_registry,
        catalog=catalog,
        compiler=compiler,
    )


__all__ = [
    "AgentNotebookRuntimeV1",
    "EvidenceCommitReceiptV1",
    "EvidenceCommitterV1",
    "compose_agent_notebook_runtime",
]
