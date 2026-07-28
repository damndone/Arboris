"""Fail-closed CF1 candidate resolution."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    CandidateSet,
    CapabilityRequirementRevision,
    ImplementationCandidate,
    ResolutionBinding,
    ResolutionPolicySnapshot,
    SelectionDecision,
)
from .freshness import ValidityCursorSnapshot, assess_freshness
from .policy import ComparisonProtocolSnapshot


class ResolverError(ValueError):
    """Raised when immutable inputs to resolution do not bind together."""


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    decision: SelectionDecision
    binding: ResolutionBinding | None


def _decision(
    *,
    outcome: str,
    candidate_set: CandidateSet,
    policy: ResolutionPolicySnapshot,
    selected: str | None,
    reason: str,
    compared: tuple[str, ...],
) -> SelectionDecision:
    return SelectionDecision(
        outcome=outcome,
        candidate_set_digest=candidate_set.content_digest,
        policy_digest=policy.content_digest,
        selected_candidate_id=selected,
        reason_code=reason,
        compared_candidate_ids=compared,
    )


class CapabilityResolver:
    """Resolve only current, feasible candidates under a frozen policy."""

    def resolve(
        self,
        *,
        requirement: CapabilityRequirementRevision,
        policy: ResolutionPolicySnapshot,
        candidate_set: CandidateSet,
        current_validity: ValidityCursorSnapshot,
        comparison_protocol: ComparisonProtocolSnapshot | None = None,
    ) -> ResolutionResult:
        if candidate_set.requirement_digest != requirement.content_digest:
            raise ResolverError("candidate set is bound to a different requirement")

        current: list[ImplementationCandidate] = []
        stale_seen = False
        unavailable_seen = False
        incompatible_seen = False
        for candidate in candidate_set.candidates:
            implementation = candidate.implementation
            if (
                implementation.profile_id != requirement.semantic_profile.profile_id
                or implementation.profile_revision != requirement.semantic_profile.revision
                or implementation.profile_digest != requirement.semantic_profile.content_digest
                or implementation.input_schema_digest != requirement.input_schema_digest
                or not set(requirement.requested_operations) <= set(implementation.operations)
                or any(
                    implementation.consumer_support[slot] != requirement.semantic_profile.consumers[slot]
                    or requirement.semantic_profile.consumers[slot] is None
                    for slot in requirement.requested_consumers
                )
            ):
                incompatible_seen = True
                continue
            if not candidate.feasible or not candidate.available:
                unavailable_seen = True
                continue
            freshness = assess_freshness(
                required_domains=policy.required_validity_domains,
                candidate_refs=candidate.validity_refs,
                current=current_validity,
            )
            if freshness.status == "current":
                current.append(candidate)
            elif freshness.status == "stale":
                stale_seen = True
            else:
                unavailable_seen = True

        if not current:
            if stale_seen:
                decision = _decision(
                    outcome="stale", candidate_set=candidate_set, policy=policy,
                    selected=None, reason="candidate_validity_stale", compared=(),
                )
            elif incompatible_seen:
                decision = _decision(
                    outcome="incomparable", candidate_set=candidate_set, policy=policy,
                    selected=None, reason="semantic_profile_incompatible", compared=(),
                )
            else:
                decision = _decision(
                    outcome="unavailable", candidate_set=candidate_set, policy=policy,
                    selected=None, reason="no_current_feasible_candidate", compared=(),
                )
            return ResolutionResult(decision, None)

        ranked = {tier: rank for rank, tier in enumerate(policy.trust_order)}
        best_rank = min(ranked[item.implementation.trust_tier] for item in current)
        top = [item for item in current if ranked[item.implementation.trust_tier] == best_rank]
        if len(top) == 1:
            return self._selected(candidate_set, policy, current_validity, top[0], "trust_order")

        compared = tuple(sorted(item.candidate_id for item in top))
        if comparison_protocol is None or policy.comparison_protocol_ref != comparison_protocol.content_digest:
            decision = _decision(
                outcome="no_dominant_choice", candidate_set=candidate_set, policy=policy,
                selected=None, reason="comparison_protocol_missing_or_unbound", compared=compared,
            )
            return ResolutionResult(decision, None)

        winners: list[ImplementationCandidate] = []
        saw_incomparable = False
        all_tied = True
        for candidate in top:
            dominates_all = True
            for other in top:
                if other.candidate_id == candidate.candidate_id:
                    continue
                relation = comparison_protocol.compare(candidate.candidate_id, other.candidate_id)
                if relation == "incomparable" or relation is None:
                    saw_incomparable = True
                    dominates_all = False
                elif relation != "left_dominates":
                    dominates_all = False
                if relation != "tie":
                    all_tied = False
            if dominates_all:
                winners.append(candidate)
        if saw_incomparable:
            decision = _decision(
                outcome="incomparable", candidate_set=candidate_set, policy=policy,
                selected=None, reason="comparison_incomparable", compared=compared,
            )
            return ResolutionResult(decision, None)
        if all_tied:
            decision = _decision(
                outcome="tied", candidate_set=candidate_set, policy=policy,
                selected=None, reason="comparison_tie", compared=compared,
            )
            return ResolutionResult(decision, None)
        if len(winners) == 1:
            return self._selected(candidate_set, policy, current_validity, winners[0], "comparison_dominance")
        decision = _decision(
            outcome="no_dominant_choice", candidate_set=candidate_set, policy=policy,
            selected=None, reason="comparison_has_no_unique_dominant_candidate", compared=compared,
        )
        return ResolutionResult(decision, None)

    @staticmethod
    def _selected(
        candidate_set: CandidateSet,
        policy: ResolutionPolicySnapshot,
        current_validity: ValidityCursorSnapshot,
        candidate: ImplementationCandidate,
        reason: str,
    ) -> ResolutionResult:
        decision = _decision(
            outcome="selected", candidate_set=candidate_set, policy=policy,
            selected=candidate.candidate_id, reason=reason,
            compared=(candidate.candidate_id,),
        )
        binding = ResolutionBinding(
            requirement_digest=candidate_set.requirement_digest,
            policy_digest=policy.content_digest,
            candidate_set_digest=candidate_set.content_digest,
            selection_digest=decision.content_digest,
            implementation_ref=candidate.implementation.content_digest,
            validity_cursor_digest=current_validity.content_digest,
        )
        return ResolutionResult(decision, binding)


__all__ = ["CapabilityResolver", "ResolutionResult", "ResolverError"]
