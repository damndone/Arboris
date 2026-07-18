"""Small proposal-building seam for the Agent Analysis Loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .contracts import SourceRunContract
from .plan import PlanDiff, build_plan_diff, confirmed_payload_hash_for_plan
from .storage import PlanDiffStore


class AnalysisLoopProposalError(ValueError):
    """The canonical plan cannot be represented as a model.rerun proposal."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def _require_non_empty(value: Any, field_name: str, *, code: str) -> str:
    if type(value) is not str or not value:
        raise AnalysisLoopProposalError(
            f"{field_name} must be a non-empty string",
            code=code,
        )
    return value


def _proposal_target(plan: PlanDiff) -> dict[str, Any]:
    source = dict(plan.source_identity)
    required = ("run_id", "node_ref", "node_hash", "forest_node_key")
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise AnalysisLoopProposalError(
            "PlanDiff source identity is not an exact model.rerun target",
            code="SOURCE_TARGET_IDENTITY_REQUIRED",
            details={"missing": missing},
        )
    return {
        **{key: source[key] for key in required},
        "target_hash": plan.target_identity["target_hash"],
    }


@dataclass(frozen=True)
class AnalysisLoopProposalSpec:
    """All fields needed by the existing ``ProposalStore``/orchestrator."""

    plan_diff: PlanDiff
    proposal_id: str
    operation_id: str
    operation_version: str
    target: Mapping[str, Any]
    preconditions: Mapping[str, Any]
    changes: Mapping[str, Any]
    evidence_refs: tuple[str, ...]
    expected_effect: tuple[str, ...]
    risks: tuple[str, ...]
    confirmed_payload_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", MappingProxyType(dict(self.target)))
        object.__setattr__(self, "preconditions", MappingProxyType(dict(self.preconditions)))
        object.__setattr__(self, "changes", MappingProxyType(dict(self.changes)))

    @property
    def plan(self) -> PlanDiff:
        return self.plan_diff

    def to_proposal_kwargs(
        self,
        *,
        chain_id: str,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        """Return arguments accepted by ``WorkbenchOrchestrator.create_proposal``."""

        return {
            "chain_id": chain_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "target": dict(self.target),
            "preconditions": dict(self.preconditions),
            "changes": dict(self.changes),
            "evidence_refs": list(self.evidence_refs),
            "expected_effect": list(self.expected_effect),
            "risks": list(self.risks),
            "command_id": command_id,
            "proposal_id": self.proposal_id,
        }


def build_analysis_loop_proposal(
    *,
    plan_store: PlanDiffStore,
    source: SourceRunContract,
    intent: Mapping[str, Any],
    cluster_values: Sequence[Any],
    model_row_ids: Sequence[str],
    requested_result_id: str | None = None,
    target: Mapping[str, Any] | None = None,
    source_context_fingerprint: str | None = None,
    source_identity: Mapping[str, Any] | None = None,
    active_head_run_id: str | None = None,
    context_version: str = "node-operation-context/v1",
    owner_resolution: str | None = None,
    operation_version: str = "v1",
    evidence_refs: Sequence[str] = ("analysis_loop:plan_diff",),
    expected_effect: Sequence[str] = (
        "create one model.rerun child with clustered covariance",
    ),
    risks: Sequence[str] = (
        "only inference configuration changes; point estimates remain unchanged",
    ),
) -> AnalysisLoopProposalSpec:
    """Build one persisted PlanDiff and its existing Proposal payload seam.

    ``source`` and the cluster rows are already resolved by the caller.  The
    intent remains untrusted and is passed unchanged to ``build_plan_diff``;
    no ProposalStore, OperationRecordStore, child run, or effect is touched.
    """

    if not isinstance(plan_store, PlanDiffStore):
        raise TypeError("plan_store must be a PlanDiffStore")
    active_head = _require_non_empty(
        active_head_run_id or source.run_id,
        "active_head_run_id",
        code="ACTIVE_HEAD_REQUIRED",
    )
    context_version = _require_non_empty(
        context_version,
        "context_version",
        code="CONTEXT_VERSION_REQUIRED",
    )
    operation_version = _require_non_empty(
        operation_version,
        "operation_version",
        code="OPERATION_VERSION_REQUIRED",
    )

    plan = build_plan_diff(
        source=source,
        intent=intent,
        requested_result_id=requested_result_id,
        target=target,
        cluster_values=cluster_values,
        model_row_ids=model_row_ids,
        source_context_fingerprint=source_context_fingerprint,
        source_identity=source_identity,
    )
    proposal_target = _proposal_target(plan)
    resolved_owner = owner_resolution or (
        "active_head_contains_node" if active_head == source.run_id else "selected_run_hint"
    )
    resolved_owner = _require_non_empty(
        resolved_owner,
        "owner_resolution",
        code="OWNER_RESOLUTION_REQUIRED",
    )

    packet = plan_store.persist_terminal_plan(plan)
    plan = packet.plan_diff
    proposal_id = f"proposal_analysis_loop_{plan.logical_key}"
    changes = dict(plan.wire_patch)
    binding = {
        "plan_logical_key": plan.logical_key,
        "plan_hash": plan.plan_hash,
        "canonical_patch_hash": plan.canonical_patch_hash,
        "source_context_fingerprint": plan.source_context_fingerprint,
        "target_hash": plan.target_identity["target_hash"],
    }
    preconditions: dict[str, Any] = {
        "context_version": context_version,
        "context_fingerprint": plan.source_context_fingerprint,
        "active_head_run_id": active_head,
        "owner_resolution": resolved_owner,
        **binding,
        "analysis_loop": dict(binding),
    }
    confirmed_hash = confirmed_payload_hash_for_plan(
        plan,
        proposal_id=proposal_id,
        revision=1,
        operation_version=operation_version,
        target=proposal_target,
        preconditions=preconditions,
        changes=changes,
    )
    preconditions["confirmed_payload_hash"] = confirmed_hash
    preconditions["analysis_loop"]["confirmed_payload_hash"] = confirmed_hash
    return AnalysisLoopProposalSpec(
        plan_diff=plan,
        proposal_id=proposal_id,
        operation_id=plan.operation_id,
        operation_version=operation_version,
        target=proposal_target,
        preconditions=preconditions,
        changes=changes,
        evidence_refs=tuple(evidence_refs),
        expected_effect=tuple(expected_effect),
        risks=tuple(risks),
        confirmed_payload_hash=confirmed_hash,
    )


__all__ = [
    "AnalysisLoopProposalError",
    "AnalysisLoopProposalSpec",
    "build_analysis_loop_proposal",
]
