from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from workbench.capability_factory.contracts import (
    CandidateSet,
    CapabilityRequirementRevision,
    ImplementationCandidate,
    ImplementationRevision,
    ResolutionPolicySnapshot,
    SemanticProfile,
)


def _resolver():
    try:
        return importlib.import_module("workbench.capability_factory.resolver")
    except ModuleNotFoundError as error:
        pytest.fail(f"CF1 resolver module is not implemented: {error}")


def _requirement(*, consumer: str = "report_projection"):
    profile = SemanticProfile(
        profile_id="profile.alpha",
        revision=1,
        input_kinds=("scalar",),
        operations=("fit", "summarize"),
        output_facets=("estimate",),
        assumptions=("finite_inputs",),
        consumers={
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    return CapabilityRequirementRevision(
        requirement_id="requirement.alpha",
        revision=1,
        semantic_profile=profile,
        requested_operations=("fit",),
        requested_consumers=(consumer,),
        input_schema={"value": "scalar"},
    )


def _implementation(identifier: str, tier: str, *, report: str | None = "report.v1"):
    requirement = _requirement()
    return ImplementationRevision(
        implementation_id=identifier,
        revision=1,
        profile_id="profile.alpha",
        profile_revision=1,
        profile_digest=requirement.semantic_profile.content_digest,
        input_schema_digest=requirement.input_schema_digest,
        source_kind=tier,
        trust_tier=tier,
        operations=("fit",),
        consumer_support={
            "report_projection": report,
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref=(identifier.encode().hex() * 64)[:64],
    )


def _candidate(identifier: str, tier: str, *, ref: str = "a" * 64, report: str | None = "report.v1"):
    return ImplementationCandidate(
        candidate_id=identifier,
        implementation=_implementation(identifier, tier, report=report),
        feasible=True,
        available=True,
        validity_refs={"implementation": ref, "host_containment": "b" * 64},
    )


def _policy(comparison_protocol_ref: str | None = None):
    return ResolutionPolicySnapshot(
        policy_id="policy.alpha",
        revision=1,
        trust_order=(
            "native_pack",
            "registered_third_party",
            "generated_adapter",
            "authored_implementation",
        ),
        required_validity_domains=("implementation", "host_containment"),
        comparison_protocol_ref=comparison_protocol_ref,
    )


def _current():
    freshness = importlib.import_module("workbench.capability_factory.freshness")
    return freshness.ValidityCursorSnapshot(
        cursors={
            "implementation": freshness.ValidityCursor(
                domain="implementation", sequence=1, state_digest="a" * 64,
                authority_ref="c" * 64,
                valid_until=datetime(2026, 7, 27, tzinfo=timezone.utc),
            ),
            "host_containment": freshness.ValidityCursor(
                domain="host_containment", sequence=1, state_digest="b" * 64,
                authority_ref="d" * 64,
                valid_until=datetime(2026, 7, 27, tzinfo=timezone.utc),
            ),
        },
        observed_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )


def test_fixed_trust_order_selects_native_only_after_feasibility_and_freshness():
    resolver = _resolver()
    requirement = _requirement()
    candidates = CandidateSet(
        requirement_digest=requirement.content_digest,
        candidates=(
            _candidate("third", "registered_third_party"),
            _candidate("native", "native_pack"),
        ),
    )

    result = resolver.CapabilityResolver().resolve(
        requirement=requirement,
        policy=_policy(),
        candidate_set=candidates,
        current_validity=_current(),
    )

    assert result.decision.outcome == "selected"
    assert result.decision.selected_candidate_id == "native"
    assert result.binding is not None
    assert result.binding.implementation_ref == _implementation("native", "native_pack").content_digest


def test_same_trust_candidates_do_not_invent_a_winner_without_comparison_protocol():
    resolver = _resolver()
    requirement = _requirement()
    candidates = CandidateSet(
        requirement_digest=requirement.content_digest,
        candidates=(_candidate("left", "native_pack"), _candidate("right", "native_pack")),
    )

    result = resolver.CapabilityResolver().resolve(
        requirement=requirement,
        policy=_policy(),
        candidate_set=candidates,
        current_validity=_current(),
    )

    assert result.decision.outcome == "no_dominant_choice"
    assert result.binding is None


def test_profile_revision_and_exact_consumer_projection_are_hard_requirements():
    resolver = _resolver()
    requirement = _requirement()
    old_profile = _implementation("old", "native_pack")
    mismatched_consumer = _implementation("consumer-mismatch", "native_pack", report="report.v2")
    stale_profile = ImplementationRevision(
        implementation_id="profile-revision-mismatch",
        revision=1,
        profile_id="profile.alpha",
        profile_revision=2,
        profile_digest=requirement.semantic_profile.content_digest,
        input_schema_digest=requirement.input_schema_digest,
        source_kind="native_pack",
        trust_tier="native_pack",
        operations=("fit",),
        consumer_support={
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="d" * 64,
    )
    candidates = CandidateSet(
        requirement.content_digest,
        (
            ImplementationCandidate("old", old_profile, True, True, {"implementation": "a" * 64, "host_containment": "b" * 64}),
            ImplementationCandidate("consumer-mismatch", mismatched_consumer, True, True, {"implementation": "a" * 64, "host_containment": "b" * 64}),
            ImplementationCandidate("profile-revision-mismatch", stale_profile, True, True, {"implementation": "a" * 64, "host_containment": "b" * 64}),
        ),
    )

    result = resolver.CapabilityResolver().resolve(
        requirement=requirement,
        policy=_policy(),
        candidate_set=candidates,
        current_validity=_current(),
    )

    assert result.decision.outcome == "selected"
    assert result.decision.selected_candidate_id == "old"


@pytest.mark.parametrize(
    ("relation_outcome", "expected"),
    [
        ("left_dominates", "selected"),
        ("tie", "tied"),
        ("incomparable", "incomparable"),
    ],
)
def test_comparison_protocol_is_required_for_same_tier_selection(relation_outcome, expected):
    resolver = _resolver()
    policy_module = importlib.import_module("workbench.capability_factory.policy")
    requirement = _requirement()
    left = _candidate("left", "native_pack")
    right = _candidate("right", "native_pack")
    protocol = policy_module.ComparisonProtocolSnapshot(
        protocol_id="comparison.alpha",
        revision=1,
        relations=(
            policy_module.ComparisonRelation(
                left_candidate_id="left",
                right_candidate_id="right",
                outcome=relation_outcome,
            ),
        ),
    )
    policy = _policy(protocol.content_digest)
    result = resolver.CapabilityResolver().resolve(
        requirement=requirement,
        policy=policy,
        candidate_set=CandidateSet(requirement.content_digest, (left, right)),
        current_validity=_current(),
        comparison_protocol=protocol,
    )

    assert result.decision.outcome == expected
    if expected == "selected":
        assert result.decision.selected_candidate_id == "left"
