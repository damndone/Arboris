from __future__ import annotations

from workbench.domain_memory.curator_contracts import AcceptedAnalysisSummary
from workbench.domain_memory.curator_eligibility import CuratorPolicy, check_curator_eligibility
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.scope import MemoryScope

from test_memory_curator_contracts import _summary


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _effective(iteration: bool = True):
    return resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=iteration))


def test_eligibility_requires_iteration_and_complete_review_point() -> None:
    assert check_curator_eligibility(_summary(), _effective(False)).reason == "DOMAIN_MEMORY_DISABLED"
    assert check_curator_eligibility(_summary(critical_omission=True), _effective()).reason == "DOMAIN_MEMORY_SUMMARY_INCOMPLETE"
    assert check_curator_eligibility(_summary(complete=False), _effective()).reason == "DOMAIN_MEMORY_SUMMARY_INCOMPLETE"


def test_eligibility_is_policy_gated_and_does_not_infer_user_preference() -> None:
    denied = check_curator_eligibility(_summary(), _effective(), CuratorPolicy(allow_iteration=False))
    assert denied.reason == "DOMAIN_MEMORY_POLICY_DENIED"
    allowed = check_curator_eligibility(_summary(), _effective())
    assert allowed.eligible is True
    assert isinstance(allowed.summary, AcceptedAnalysisSummary)
