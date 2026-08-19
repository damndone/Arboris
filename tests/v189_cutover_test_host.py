"""Non-authoritative host compiler fixture for the v1.8.9 cutover tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from workbench.agent.planning_contracts import (
    HostCompilationRequestV1,
    HostCompilationResultV1,
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


__all__ = ["CutoverTestHostCompiler"]
