"""Candidate-only curator runtime with no analysis or authority dependencies."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .candidate_store import MemoryCandidateStore, MemoryCandidateStoreConflict
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
                # Curator eligibility is the bounded readiness check for this
                # producer. Its output is therefore ready for the existing
                # explicit user-review boundary, not an inert intermediate
                # state that the review API cannot approve.
                status="needs_review",
                created_at=summary.created_at,
            )
            created.append(self._append_reviewable_candidate(candidate))
        return tuple(created)

    def _append_reviewable_candidate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        """Append a reviewable candidate, progressing a matching legacy record."""

        try:
            return self.candidate_store.append(candidate)
        except MemoryCandidateStoreConflict:
            current = self.candidate_store.latest(candidate.candidate_id)
            if current.status == "proposed" and current == replace(candidate, status="proposed"):
                try:
                    return self.candidate_store.transition(
                        candidate.candidate_id,
                        expected_revision=current.revision,
                        status="needs_review",
                    )
                except MemoryCandidateStoreConflict:
                    current = self.candidate_store.latest(candidate.candidate_id)
            if current.status == "needs_review" and replace(current, revision=candidate.revision) == candidate:
                return current
            raise


__all__ = ["CuratorRuntime"]
