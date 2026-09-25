"""Non-authoritative host compiler fixture for the v1.8.9 cutover tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from workbench.agent.planning_contracts import (
    DeploymentIdentityResolverV1,
    HostCompilationRequestV1,
    HostCompilationResultV1,
    ServerScopeBindingV1,
)
from workbench.canonical import sha256_canonical
from workbench.contracts.agent.planning import (
    CompilationRecordV1,
    CompiledWorkflowV1,
    ServerCompilationRecordReferenceV1,
)


class CutoverTestHostCompiler:
    """A deterministic test adapter; it is not a production authority."""

    def compile(self, request: HostCompilationRequestV1) -> HostCompilationResultV1:
        if type(request) is not HostCompilationRequestV1:
            raise TypeError("cutover host request is required")
        compiled = CompiledWorkflowV1.from_draft(
            request.draft,
            compiler_version="compiler:test:v1.8.9",
            server_execution_identity=f"compile:test:{request.idempotency_key}",
            preview_fingerprint=sha256_canonical(
                {
                    "semantic_plan_hash": request.draft.semantic_plan_hash,
                    "compiler_version": "compiler:test:v1.8.9",
                    "idempotency_key": request.idempotency_key,
                }
            ),
            plan_diff={
                "effect": request.draft.effect.value,
                "data_impact": "read_dataset" if "read_refs" in request.draft.data_impact else "none",
            },
            risk_level=request.draft.risk_level,
            effect=request.draft.effect,
            resource_budget=request.draft.resource_budget,
            contract_snapshot_refs=request.draft.contract_snapshot_refs,
            catalog_snapshot_ref=request.draft.catalog_snapshot_ref,
        )
        created_at = datetime.now(UTC)
        record = CompilationRecordV1.from_compiled(
            compiled,
            record_id=f"compilation-record:{request.idempotency_key}",
            principal_ref=request.principal_ref,
            session_ref=request.session_ref,
            project_ref=request.project_ref,
            source_commitments=dict(request.source_commitments),
            created_at=created_at.isoformat(),
            expires_at=(created_at + timedelta(minutes=10)).isoformat(),
        )
        return HostCompilationResultV1(
            compiled_plan=compiled,
            record=record,
            reference=ServerCompilationRecordReferenceV1(
                record_id=record.record_id,
                record_digest=record.record_digest,
                semantic_plan_hash=record.semantic_plan_hash,
            ),
        )


class _TestScopeAuthority:
    """Non-authoritative scope adapter used only after route-boundary tests."""

    def resolve(
        self,
        *,
        scope_ref: str,
        principal_ref: str,
        session_ref: str,
        project_ref: str,
    ) -> ServerScopeBindingV1:
        return ServerScopeBindingV1(
            scope_ref=scope_ref,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref,
        )


def make_test_identity_resolver(
    callback: Callable[..., Any],
) -> DeploymentIdentityResolverV1:
    """Wrap a deterministic callback in the typed resolver test seam.

    The production app setter accepts only ``DeploymentIdentityResolverV1``.
    Route tests still need a deterministic identity fixture without pretending
    that a caller-created object is a deployment authority, so this helper is
    deliberately isolated from production code and never used by startup.
    """

    def authenticated_identity(*args: Any) -> Any:
        resolved = callback(*args)
        # The historical test callbacks used ``None`` as the optional project
        # slot.  The typed deployment contract represents that as its 2-tuple
        # form; a real 3-tuple must carry the request's exact project scope.
        if isinstance(resolved, tuple) and len(resolved) == 3 and resolved[2] is None:
            return resolved[:2]
        return resolved

    resolver = object.__new__(DeploymentIdentityResolverV1)
    object.__setattr__(resolver, "_scope_resolver", _TestScopeAuthority())
    object.__setattr__(resolver, "_authenticated_identity_resolver", authenticated_identity)
    return resolver


__all__ = ["CutoverTestHostCompiler", "make_test_identity_resolver"]
