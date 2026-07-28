from __future__ import annotations


def test_evidence_assessment_keeps_validity_separate_from_admission():
    from workbench.capability_factory.evidence_assessment import (
        EvidenceAssessment,
        EvidenceValidityStore,
    )

    assessment = EvidenceAssessment(
        assessment_id="assessment.alpha",
        bundle_ref="a" * 64,
        protocol_ref="b" * 64,
        attempt_ledger_ref="c" * 64,
        tier="E1",
        status="passed",
        evidence_refs=("d" * 64,),
        producer_ref="e" * 64,
    )
    assert assessment.experimental is True
    assert assessment.source_eligible is False
    store = EvidenceValidityStore()
    record = store.append(
        assessment=assessment,
        status="valid",
        reason="protocol_completed",
        authority_ref="f" * 64,
    )
    assert record.status == "valid"
    assert store.latest(assessment.content_digest) == record


def test_invalid_assessment_cannot_be_restored_in_place():
    import pytest
    from workbench.capability_factory.evidence_assessment import EvidenceAssessment, EvidenceAssessmentError, EvidenceValidityStore

    assessment = EvidenceAssessment(
        assessment_id="assessment.beta",
        bundle_ref="a" * 64,
        protocol_ref="b" * 64,
        attempt_ledger_ref="c" * 64,
        tier="E2",
        status="passed",
        evidence_refs=("d" * 64,),
        producer_ref="e" * 64,
    )
    store = EvidenceValidityStore()
    store.append(assessment=assessment, status="invalid", reason="oracle_withdrawn", authority_ref="f" * 64)
    with pytest.raises(EvidenceAssessmentError, match="terminal"):
        store.append(assessment=assessment, status="valid", reason="restore", authority_ref="g" * 64)
