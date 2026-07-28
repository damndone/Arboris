from __future__ import annotations

import pytest


def _case(*, visibility: str = "author_visible"):
    from workbench.capability_factory.validation_contract import ValidationCase

    return ValidationCase(
        case_id="case.generic.1",
        fixture_ref="a" * 64,
        fixture_visibility=visibility,
    )


def test_author_self_evidence_is_experimental_and_never_source_eligible():
    from workbench.capability_factory.validation_contract import (
        ValidationEvidence,
    )

    evidence = ValidationEvidence(
        evidence_id="evidence.author.1",
        case_ref=_case().content_digest,
        tier="E1",
        status="passed",
        observed_ref="b" * 64,
    )

    assert evidence.experimental is True
    assert evidence.source_eligible is False
    assert evidence.oracle_ref is None


def test_independent_evidence_requires_oracle_and_can_be_source_eligible():
    from workbench.capability_factory.validation_contract import (
        ValidationEvidence,
        ValidationContractError,
    )

    with pytest.raises(ValidationContractError, match="independent oracle"):
        ValidationEvidence(
            evidence_id="evidence.missing-oracle",
            case_ref=_case().content_digest,
            tier="E2",
            status="passed",
            observed_ref="b" * 64,
        )

    evidence = ValidationEvidence(
        evidence_id="evidence.independent.1",
        case_ref=_case().content_digest,
        tier="E2",
        status="passed",
        observed_ref="b" * 64,
        oracle_ref="c" * 64,
        oracle_kind="independent_implementation",
    )
    assert evidence.experimental is False
    assert evidence.source_eligible is True


def test_holdout_evidence_is_required_for_the_highest_evidence_tier():
    from workbench.capability_factory.validation_contract import (
        ValidationEvidence,
        ValidationContractError,
    )

    with pytest.raises(ValidationContractError, match="holdout"):
        ValidationEvidence(
            evidence_id="evidence.not-holdout",
            case_ref=_case().content_digest,
            tier="E3",
            status="passed",
            observed_ref="b" * 64,
            oracle_ref="c" * 64,
            oracle_kind="trusted_fixture",
        )

    evidence = ValidationEvidence(
        evidence_id="evidence.holdout",
        case_ref=_case(visibility="service_holdout").content_digest,
        tier="E3",
        status="passed",
        observed_ref="b" * 64,
        oracle_ref="c" * 64,
        oracle_kind="trusted_fixture",
        fixture_visibility="service_holdout",
    )
    assert evidence.source_eligible is True


def test_validation_bundle_appends_bounded_evidence_without_replacing_history():
    from workbench.capability_factory.validation_contract import (
        ValidationBundle,
        ValidationEvidence,
    )

    case = _case()
    bundle = ValidationBundle(
        bundle_id="bundle.generic",
        revision=1,
        adapter_ref="d" * 64,
        cases=(case,),
    )
    evidence = ValidationEvidence(
        evidence_id="evidence.bundle.1",
        case_ref=case.content_digest,
        tier="E1",
        status="passed",
        observed_ref="b" * 64,
    )
    next_bundle = bundle.append_evidence(evidence)

    assert bundle.revision == 1
    assert bundle.evidence == ()
    assert next_bundle.revision == 2
    assert next_bundle.evidence == (evidence,)
    assert next_bundle.content_digest != bundle.content_digest


def test_validation_evidence_cannot_bind_to_an_unknown_case():
    from workbench.capability_factory.validation_contract import (
        ValidationBundle,
        ValidationContractError,
        ValidationEvidence,
    )

    bundle = ValidationBundle(
        bundle_id="bundle.generic",
        revision=1,
        adapter_ref="d" * 64,
        cases=(_case(),),
    )
    evidence = ValidationEvidence(
        evidence_id="evidence.unknown-case",
        case_ref="e" * 64,
        tier="E1",
        status="passed",
        observed_ref="b" * 64,
    )
    with pytest.raises(ValidationContractError, match="case"):
        bundle.append_evidence(evidence)


def test_validation_case_rejects_an_unregistered_check_kind():
    from workbench.capability_factory.validation_contract import ValidationCase, ValidationContractError

    with pytest.raises(ValidationContractError, match="check kind"):
        ValidationCase(
            case_id="case.unknown-check",
            fixture_ref="a" * 64,
            check_kind="not-a-registered-check",
        )
