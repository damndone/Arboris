"""Small proposal-building seam for the Agent Analysis Loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .contracts import SourceRunContract
from .plan import (
    PlanBindingError,
    PlanDiff,
    build_plan_diff,
    confirmed_payload_hash_for_plan,
    validate_confirmation_binding,
)
from .preflight import validate_source_contract
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


def _binding_value(preconditions: Mapping[str, Any], key: str) -> Any:
    nested = preconditions.get("analysis_loop")
    if isinstance(nested, Mapping) and key in nested:
        return nested[key]
    return preconditions.get(key)


def create_analysis_loop_proposal(
    *,
    orchestrator: Any,
    chain_id: str,
    command_id: str | None = None,
    **build_kwargs: Any,
) -> Any:
    """Adapt the pure spec into the existing ProposalStore lifecycle."""

    spec = build_analysis_loop_proposal(**build_kwargs)
    proposal_kwargs = spec.to_proposal_kwargs(
        chain_id=chain_id,
        command_id=command_id,
    )
    from ..agent.proposals import ProposalConfirmationError

    try:
        existing = orchestrator.proposal_store.latest_revision(spec.proposal_id)
    except (KeyError, ValueError):
        existing = None
    if existing is not None:
        if (
            existing.operation_id == spec.operation_id
            and existing.operation_version == spec.operation_version
            and existing.target == proposal_kwargs["target"]
            and existing.preconditions == proposal_kwargs["preconditions"]
            and existing.changes == proposal_kwargs["changes"]
        ):
            return existing
        raise AnalysisLoopProposalError(
            "analysis-loop proposal identity is already bound to other content",
            code="ANALYSIS_LOOP_PROPOSAL_CONFLICT",
            details={"proposal_id": spec.proposal_id},
        )
    try:
        return orchestrator.create_proposal(**proposal_kwargs)
    except ProposalConfirmationError as exc:
        # ProposalStore.create is append-only and the deterministic id makes a
        # concurrent retry safe. Only convert a duplicate into the existing
        # proposal; preserve all registry/validation failures unchanged.
        try:
            existing = orchestrator.proposal_store.latest_revision(spec.proposal_id)
        except (KeyError, ValueError):
            raise
        if (
            existing.operation_id == spec.operation_id
            and existing.target == proposal_kwargs["target"]
            and existing.preconditions == proposal_kwargs["preconditions"]
            and existing.changes == proposal_kwargs["changes"]
        ):
            return existing
        raise AnalysisLoopProposalError(
            "analysis-loop proposal identity is already bound to other content",
            code="ANALYSIS_LOOP_PROPOSAL_CONFLICT",
            details={"proposal_id": spec.proposal_id},
        ) from exc


def confirm_analysis_loop_proposal(
    *,
    orchestrator: Any,
    plan_store: PlanDiffStore,
    proposal_id: str,
    current_source: SourceRunContract,
    current_source_context_fingerprint: str,
    current_active_head_run_id: str,
    revision: int,
    fingerprint: str,
    confirmed_payload_hash: str,
    actor_type: str = "user",
) -> Any:
    """Validate an analysis-loop binding, then use existing confirmation code."""

    proposal = orchestrator.proposal_store.latest_revision(proposal_id)
    if revision != proposal.revision:
        raise PlanBindingError(
            "analysis-loop proposal revision is stale",
            code="STALE_PLAN",
            details={"expected_revision": proposal.revision, "actual_revision": revision},
        )
    logical_key = _binding_value(proposal.preconditions, "plan_logical_key")
    if type(logical_key) is not str or not logical_key:
        raise PlanBindingError(
            "analysis-loop proposal has no PlanDiff logical key",
            code="STALE_PLAN",
        )
    packet = plan_store.get_terminal_packet(logical_key)
    if packet is None:
        raise PlanBindingError(
            "analysis-loop PlanDiff terminal packet is unavailable",
            code="STALE_PLAN",
            details={"logical_key": logical_key},
        )
    plan = packet.plan_diff
    bound_plan_hash = _binding_value(proposal.preconditions, "plan_hash")
    bound_canonical_patch_hash = _binding_value(
        proposal.preconditions,
        "canonical_patch_hash",
    )
    bound_source_context_fingerprint = _binding_value(
        proposal.preconditions,
        "source_context_fingerprint",
    )
    bound_target_hash = _binding_value(proposal.preconditions, "target_hash")
    if not all(
        type(value) is str and value
        for value in (
            bound_plan_hash,
            bound_canonical_patch_hash,
            bound_source_context_fingerprint,
            bound_target_hash,
        )
    ):
        raise PlanBindingError(
            "analysis-loop proposal binding is incomplete",
            code="STALE_PLAN",
        )
    validate_confirmation_binding(
        plan,
        bound_plan_hash=bound_plan_hash,
        bound_canonical_patch_hash=bound_canonical_patch_hash,
        bound_target_hash=bound_target_hash,
        bound_source_context_fingerprint=bound_source_context_fingerprint,
        current_source_context_fingerprint=current_source_context_fingerprint,
        confirmed_payload_hash=confirmed_payload_hash,
        proposal_id=proposal.proposal_id,
        revision=proposal.revision,
        operation_version=proposal.operation_version,
        target=proposal.target,
        preconditions=proposal.preconditions,
        changes=proposal.changes,
    )
    source_validation = validate_source_contract(current_source)
    if (
        current_source.run_id != proposal.target.get("run_id")
        or current_source.status != "completed"
        or not source_validation.valid
    ):
        raise PlanBindingError(
            "current source run is no longer the completed PlanDiff source",
            code="STALE_PLAN",
            details={
                "source_run_id": current_source.run_id,
                "source_status": current_source.status,
                "source_validation": source_validation.code,
            },
        )
    expected_active_head = proposal.preconditions.get("active_head_run_id")
    if current_active_head_run_id != expected_active_head:
        raise PlanBindingError(
            "current active head no longer matches the analysis-loop proposal",
            code="STALE_PLAN",
            details={
                "expected_active_head_run_id": expected_active_head,
                "actual_active_head_run_id": current_active_head_run_id,
            },
        )
    return orchestrator.confirm_proposal(
        proposal_id,
        revision=revision,
        fingerprint=fingerprint,
        actor_type=actor_type,
        current_context_fingerprint=current_source_context_fingerprint,
        current_active_head_run_id=current_active_head_run_id,
    )


__all__ = [
    "AnalysisLoopProposalError",
    "AnalysisLoopProposalSpec",
    "build_analysis_loop_proposal",
    "confirm_analysis_loop_proposal",
    "create_analysis_loop_proposal",
]
