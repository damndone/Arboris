"""Candidate-only curator runtime with no analysis or authority dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate_store import MemoryCandidateStore
from .contracts import MemoryCandidate
from .curator_contracts import AcceptedAnalysisSummary
from .curator_eligibility import CuratorEligibilityDecision, CuratorPolicy, check_curator_eligibility
from .preferences import EffectiveDomainMemoryPreferences


@dataclass(frozen=True, slots=True)
class CuratorRuntime:
    candidate_store: MemoryCandidateStore
    policy: CuratorPolicy = CuratorPolicy()

    def generate(self, summary: AcceptedAnalysisSummary, preferences: EffectiveDomainMemoryPreferences) -> tuple[MemoryCandidate, ...]:
        decision = check_curator_eligibility(summary, preferences, self.policy)
        if not decision.eligible:
            return ()
        created: list[MemoryCandidate] = []
        for observation in decision.summary.observations:
            candidate_id = "candidate-" + summary.idempotency_key[:32] + "-" + observation.observation_ref
            candidate = MemoryCandidate(
                candidate_id=candidate_id,
                revision=1,
                scope=summary.scope,
                memory_kind=observation.memory_kind,
                domain_tags=observation.domain_tags,
                applicability_predicates=observation.applicability_predicates,
                compact_lesson=observation.compact_lesson,
                recommended_effect_kind=observation.recommended_effect_kind,
                recommended_target_refs=observation.recommended_target_refs,
                source_summary_refs=observation.source_summary_refs,
                created_from_manifest_ref=summary.summary_ref,
                status="proposed",
                created_at=summary.created_at,
            )
            created.append(self.candidate_store.append(candidate))
        return tuple(created)


__all__ = ["CuratorRuntime"]
