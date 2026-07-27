"""Pure eligibility gate for candidate-only memory iteration."""

from __future__ import annotations

from dataclasses import dataclass

from .curator_contracts import AcceptedAnalysisSummary, CuratorReviewPoint
from .preferences import EffectiveDomainMemoryPreferences


@dataclass(frozen=True, slots=True)
class CuratorPolicy:
    allow_iteration: bool = True
    require_explicit_review_point: bool = True
    max_observations: int = 16

    def __post_init__(self) -> None:
        if type(self.allow_iteration) is not bool or type(self.require_explicit_review_point) is not bool:
            raise ValueError("curator policy gates must be booleans")
        if not isinstance(self.max_observations, int) or isinstance(self.max_observations, bool) or not 1 <= self.max_observations <= 16:
            raise ValueError("curator observation budget is invalid")


@dataclass(frozen=True, slots=True)
class CuratorEligibilityDecision:
    eligible: bool
    reason: str
    summary: AcceptedAnalysisSummary


def check_curator_eligibility(
    summary: AcceptedAnalysisSummary,
    preferences: EffectiveDomainMemoryPreferences,
    policy: CuratorPolicy | None = None,
) -> CuratorEligibilityDecision:
    if not isinstance(summary, AcceptedAnalysisSummary) or not isinstance(preferences, EffectiveDomainMemoryPreferences):
        raise ValueError("summary and effective preferences are required")
    policy = policy or CuratorPolicy()
    if not preferences.iteration:
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_DISABLED", summary)
    if not policy.allow_iteration:
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_POLICY_DENIED", summary)
    if policy.require_explicit_review_point and summary.review_point not in set(CuratorReviewPoint):
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_REVIEW_POINT_REQUIRED", summary)
    if summary.analysis_state not in {"accepted", "abandoned"} or not summary.complete or summary.critical_omission:
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_SUMMARY_INCOMPLETE", summary)
    if len(summary.observations) == 0:
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_NO_OBSERVATION", summary)
    if len(summary.observations) > policy.max_observations:
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_BUDGET_EXCEEDED", summary)
    if not summary.policy_allows:
        return CuratorEligibilityDecision(False, "DOMAIN_MEMORY_POLICY_DENIED", summary)
    return CuratorEligibilityDecision(True, "ELIGIBLE", summary)


__all__ = ["CuratorEligibilityDecision", "CuratorPolicy", "check_curator_eligibility"]
