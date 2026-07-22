from __future__ import annotations

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.time_series_diagnostics import (
    TimeSeriesDiagnosticFacts,
    derive_assessment,
)


def _facts(
    *,
    has_hard_input_violation: bool = False,
    required_component_unavailable: bool = False,
    adf_outcome: str = "reject",
    kpss_outcome: str = "fail_to_reject",
    trend_status: str = "completed",
    trend_evidence: str = "absent",
    trend_advisory_preconditions: str = "false",
) -> TimeSeriesDiagnosticFacts:
    return TimeSeriesDiagnosticFacts(
        has_hard_input_violation=has_hard_input_violation,
        required_component_unavailable=required_component_unavailable,
        adf_outcome=adf_outcome,
        kpss_outcome=kpss_outcome,
        trend_status=trend_status,
        trend_evidence=trend_evidence,
        trend_advisory_preconditions=trend_advisory_preconditions,
    )


@pytest.mark.parametrize(
    ("adf_outcome", "kpss_outcome", "expected"),
    [
        ("reject", "reject", "inconclusive"),
        ("reject", "fail_to_reject", "suitable_with_caveats"),
        ("reject", "undetermined", "inconclusive"),
        ("fail_to_reject", "reject", "suitable_with_caveats"),
        ("fail_to_reject", "fail_to_reject", "inconclusive"),
        ("fail_to_reject", "undetermined", "inconclusive"),
        ("undetermined", "reject", "inconclusive"),
        ("undetermined", "fail_to_reject", "inconclusive"),
        ("undetermined", "undetermined", "inconclusive"),
    ],
)
def test_completed_null_test_truth_table_has_one_conclusion(
    adf_outcome: str, kpss_outcome: str, expected: str
) -> None:
    assert derive_assessment(
        _facts(adf_outcome=adf_outcome, kpss_outcome=kpss_outcome)
    ).conclusion == expected


def test_hard_input_violation_has_priority_over_all_other_facts() -> None:
    assessment = derive_assessment(
        _facts(
            has_hard_input_violation=True,
            required_component_unavailable=True,
            adf_outcome="undetermined",
            kpss_outcome="undetermined",
        )
    )

    assert assessment.conclusion == "not_suitable"
    assert assessment.advisories == ()


@pytest.mark.parametrize(
    "facts",
    [
        _facts(required_component_unavailable=True),
        _facts(adf_outcome="undetermined"),
        _facts(kpss_outcome="undetermined"),
    ],
)
def test_unavailable_or_undetermined_required_evidence_is_inconclusive(
    facts: TimeSeriesDiagnosticFacts,
) -> None:
    assessment = derive_assessment(facts)

    assert assessment.conclusion == "inconclusive"
    assert assessment.advisories == ()


def test_consider_differencing_is_the_only_advisory_for_its_exact_conditions() -> None:
    assessment = derive_assessment(
        _facts(adf_outcome="fail_to_reject", kpss_outcome="reject")
    )

    assert assessment.conclusion == "suitable_with_caveats"
    assert [advisory.to_dict() for advisory in assessment.advisories] == [
        {
            "code": "CONSIDER_DIFFERENCING",
            "effect": "advisory_only",
            "execution_available": False,
        }
    ]


@pytest.mark.parametrize("trend_evidence", ["present", "undetermined"])
def test_review_trend_handling_requires_completed_eligible_trend_evidence(
    trend_evidence: str,
) -> None:
    assessment = derive_assessment(
        _facts(
            trend_evidence=trend_evidence,
            trend_advisory_preconditions="true",
        )
    )

    assert [advisory.to_dict() for advisory in assessment.advisories] == [
        {
            "code": "REVIEW_TREND_HANDLING",
            "effect": "advisory_only",
            "execution_available": False,
        }
    ]


@pytest.mark.parametrize(
    "facts",
    [
        _facts(
            adf_outcome="reject",
            kpss_outcome="reject",
            trend_evidence="present",
            trend_advisory_preconditions="true",
        ),
        _facts(
            required_component_unavailable=True,
            trend_evidence="present",
            trend_advisory_preconditions="true",
        ),
        _facts(
            trend_evidence="present",
            trend_advisory_preconditions="unknown",
        ),
    ],
)
def test_conflict_unavailable_or_unknown_evidence_never_emits_an_advisory(
    facts: TimeSeriesDiagnosticFacts,
) -> None:
    assert derive_assessment(facts).advisories == ()


def test_normalized_facts_reject_unknown_declared_values_and_fields() -> None:
    payload = {
        "has_hard_input_violation": False,
        "required_component_unavailable": False,
        "adf_outcome": "reject",
        "kpss_outcome": "fail_to_reject",
        "trend_status": "completed",
        "trend_evidence": "absent",
        "trend_advisory_preconditions": "false",
    }

    with pytest.raises(ContractError, match="adf_outcome"):
        TimeSeriesDiagnosticFacts.from_dict({**payload, "adf_outcome": "exact"})
    with pytest.raises(ContractError, match="unknown time-series diagnostic facts field"):
        TimeSeriesDiagnosticFacts.from_dict({**payload, "unexpected": True})
