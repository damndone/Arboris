from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.common.contract_ref import (
    CONTRACT_DIGEST_MISMATCH,
    CONTRACT_DUPLICATE,
    CONTRACT_MAJOR_INCOMPATIBLE,
    CONTRACT_REF_INVALID,
    CONTRACT_UNRESOLVED,
    CONTRACT_VERSION_INVALID,
    ContractRefError,
    ContractRefResolverV1,
    ContractRefV1,
    canonical_contract_digest,
    parse_semantic_version,
)
from workbench.contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    EvaluationDesignV1,
    ExecutionStatusV1,
    InferenceBasisV1,
    NumericalMethodV1,
    TransactionStatusV1,
    ValidationLevelV1,
    ValidationRequirementStatusV1,
    validation_level_rank,
)
from workbench.contracts.evidence.envelope import (
    DenominatorV1,
    EvidenceEnvelopeV1,
    EvidenceReasonV1,
    NotApplicableV1,
    NumericFactV1,
    ValidationSummaryV1,
)
from workbench.contracts.evidence.persistence import (
    EVIDENCE_IDEMPOTENCY_CONFLICT,
    EVIDENCE_IDEMPOTENCY_KEY_MISMATCH,
    EvidenceCommitBindingV1,
    EvidenceCommitRequestV1,
    EvidencePersistenceContractError,
    FailureReceiptV1,
    resolve_idempotent_retry,
)


_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "contracts" / "v189"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((_FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _ref(
    *,
    kind: str = "result",
    logical_id: str = "model.ols",
    semantic_version: str = "1.0",
    payload: object | None = None,
) -> ContractRefV1:
    contract_payload = (
        {"kind": kind, "logical_id": logical_id, "version": semantic_version}
        if payload is None
        else payload
    )
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version=semantic_version,
        contract_digest=canonical_contract_digest(contract_payload),
    )


def test_contract_ref_requires_kind_id_semver_and_digest() -> None:
    ref = _ref()

    assert [field.name for field in fields(ref)] == [
        "kind",
        "logical_id",
        "semantic_version",
        "contract_digest",
    ]
    assert ContractRefV1.from_dict(ref.to_dict()) == ref
    with pytest.raises(FrozenInstanceError):
        ref.kind = "changed"  # type: ignore[misc]

    valid = ref.to_dict()
    for field_name in valid:
        missing = dict(valid)
        missing.pop(field_name)
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1.from_dict(missing)
        assert exc_info.value.code == CONTRACT_REF_INVALID

    with pytest.raises(ContractRefError) as exc_info:
        ContractRefV1.from_dict({**valid, "unknown": "rejected"})
    assert exc_info.value.code == CONTRACT_REF_INVALID

    for field_name, invalid_value in (
        ("kind", " result"),
        ("kind", "result\x00"),
        ("logical_id", ""),
        ("logical_id", 7),
    ):
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1.from_dict({**valid, field_name: invalid_value})
        assert exc_info.value.code == CONTRACT_REF_INVALID


def test_contract_ref_rejects_non_semver_and_non_sha256_digest() -> None:
    assert parse_semantic_version("1.0") == (1, 0)
    digest = canonical_contract_digest({"b": 2, "a": 1})
    assert digest == canonical_contract_digest({"a": 1, "b": 2})
    assert len(digest) == 64
    assert digest == digest.lower()

    for invalid_version in (
        "v1.0",
        "1",
        "1.0.0",
        "1.0-rc1",
        "01.0",
        "1.00",
        " 1.0",
        "1.0 ",
        1.0,
    ):
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1(
                kind="result",
                logical_id="model.ols",
                semantic_version=invalid_version,  # type: ignore[arg-type]
                contract_digest=digest,
            )
        assert exc_info.value.code == CONTRACT_VERSION_INVALID

    for invalid_digest in ("sha256:" + digest, digest.upper(), "0" * 63, 123):
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1(
                kind="result",
                logical_id="model.ols",
                semantic_version="1.0",
                contract_digest=invalid_digest,  # type: ignore[arg-type]
            )
        assert exc_info.value.code == CONTRACT_REF_INVALID


def test_semantic_version_components_are_bounded() -> None:
    max_component = 2_147_483_647
    assert parse_semantic_version(f"{max_component}.{max_component}") == (
        max_component,
        max_component,
    )

    for invalid_version in (
        f"{'9' * 5_000}.0",
        f"0.{'9' * 5_000}",
        f"{max_component + 1}.0",
        f"0.{max_component + 1}",
    ):
        with pytest.raises(ContractRefError) as exc_info:
            parse_semantic_version(invalid_version)
        assert exc_info.value.code == CONTRACT_VERSION_INVALID


def test_evidence_status_axes_are_independent() -> None:
    assert [status.value for status in ExecutionStatusV1] == [
        "completed",
        "partial",
        "blocked",
        "failed",
    ]
    assert [status.value for status in AvailabilityStatusV1] == [
        "available",
        "not_available",
        "not_applicable",
    ]
    assert [status.value for status in CompletenessStatusV1] == [
        "complete",
        "degraded",
        "insufficient",
        "not_applicable",
    ]
    assert [status.value for status in NumericalMethodV1] == [
        "closed_form",
        "deterministic_numeric",
        "simulation",
        "approximate_algorithm",
    ]
    assert [status.value for status in InferenceBasisV1] == [
        "exact_distribution",
        "asymptotic",
        "bootstrap",
        "descriptive",
        "not_applicable",
    ]
    assert [status.value for status in EvaluationDesignV1] == [
        "in_sample",
        "holdout",
        "cross_validation",
        "nested_cross_validation",
        "cross_fitting",
        "bootstrap",
        "not_applicable",
    ]
    assert [status.value for status in ValidationLevelV1] == [
        "none",
        "same_library_regression",
        "known_answer",
        "independent_implementation",
        "reference_software",
    ]
    assert [status.value for status in ValidationRequirementStatusV1] == [
        "met",
        "not_met",
        "not_applicable",
    ]
    assert [status.value for status in TransactionStatusV1] == [
        "committed",
        "failed",
        "invalidated",
    ]
    assert validation_level_rank(ValidationLevelV1.NONE) == 0
    assert validation_level_rank(ValidationLevelV1.REFERENCE_SOFTWARE) == 4


def test_same_library_regression_cannot_claim_independent_validation() -> None:
    fact = _fixture("evidence_envelope.json")["numeric_facts"][0]  # type: ignore[index]
    forged = {**fact, "validation_level": "independent_implementation"}

    with pytest.raises(ContractError):
        NumericFactV1.from_dict(forged)

    failed_check = {
        **fact,
        "oracle_checks": [{**fact["oracle_checks"][0], "status": "fail"}],
        "validation_level": "none",
    }
    assert NumericFactV1.from_dict(failed_check).validation_level is ValidationLevelV1.NONE
    with pytest.raises(ContractError):
        NumericFactV1.from_dict(
            {**failed_check, "validation_level": "same_library_regression"}
        )


def test_numeric_fact_requires_denominator_scale_inference_and_source() -> None:
    fact = _fixture("evidence_envelope.json")["numeric_facts"][0]  # type: ignore[index]

    for field_name in (
        "denominator",
        "scale",
        "reference_distribution",
        "source_selector",
    ):
        missing = dict(fact)
        missing.pop(field_name)
        with pytest.raises(ContractError):
            NumericFactV1.from_dict(missing)

    with pytest.raises(ContractError):
        NumericFactV1.from_dict({**fact, "value": float("nan")})
    with pytest.raises(ContractError):
        NumericFactV1.from_dict({**fact, "scale": ""})
    with pytest.raises(ContractError):
        DenominatorV1.from_dict({"kind": "rows", "value": 0, "unit": "row"})


def test_unavailable_and_not_applicable_require_explicit_reasons() -> None:
    valid = _fixture("evidence_envelope.json")

    for availability in ("not_available", "not_applicable"):
        with pytest.raises(ContractError):
            EvidenceEnvelopeV1.from_dict(
                {**valid, "availability": availability, "availability_reasons": []}
            )

    blocked = {
        **valid,
        "execution_status": "blocked",
        "availability": "not_available",
        "execution_reasons": [],
        "availability_reasons": [
            {"code": "BLOCKED", "message": "Policy blocked execution.", "source_refs": ["policy-1"]}
        ],
    }
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(blocked)

    completed_with_block_reason = {
        **valid,
        "execution_status": "completed",
        "execution_reasons": [
            {"code": "BLOCKED", "message": "Policy blocked execution.", "source_refs": ["policy-1"]}
        ],
    }
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(completed_with_block_reason)

    for reason in ("", " leading", "trailing "):
        with pytest.raises(ContractError):
            NotApplicableV1(reason=reason)


def test_degraded_is_completeness_not_execution_or_availability() -> None:
    valid = _fixture("evidence_envelope.json")
    degradation_reason = EvidenceReasonV1(
        code="MISSING_DIAGNOSTIC",
        message="One optional diagnostic is unavailable.",
        source_refs=("diagnostic-1",),
    ).to_dict()
    degraded = EvidenceEnvelopeV1.from_dict(
        {
            **valid,
            "completeness_status": "degraded",
            "degradation_reasons": [degradation_reason],
        }
    )

    assert degraded.execution_status is ExecutionStatusV1.COMPLETED
    assert degraded.availability is AvailabilityStatusV1.AVAILABLE
    assert degraded.completeness_status is CompletenessStatusV1.DEGRADED

    for field_name in ("execution_status", "availability"):
        with pytest.raises(ContractError):
            EvidenceEnvelopeV1.from_dict({**valid, field_name: "degraded"})


def test_fact_validation_does_not_promote_the_whole_envelope() -> None:
    fixture_path = _FIXTURE_ROOT / "evidence_envelope.json"
    payload = _fixture("evidence_envelope.json")
    envelope = EvidenceEnvelopeV1.from_dict(payload)

    assert [fact.validation_level for fact in envelope.numeric_facts] == [
        ValidationLevelV1.SAME_LIBRARY_REGRESSION,
        ValidationLevelV1.INDEPENDENT_IMPLEMENTATION,
    ]
    assert envelope.validation_summary == ValidationSummaryV1.from_facts(
        envelope.numeric_facts,
        ValidationLevelV1.SAME_LIBRARY_REGRESSION,
    )
    assert ValidationSummaryV1.from_facts(
        envelope.numeric_facts,
        ValidationLevelV1.INDEPENDENT_IMPLEMENTATION,
    ).requirement_status is ValidationRequirementStatusV1.NOT_MET

    promoted = {
        **payload,
        "validation_summary": {
            "levels_present": ["independent_implementation"],
            "minimum_required": "independent_implementation",
            "requirement_status": "met",
        },
    }
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(promoted)

    assert canonical_json_v1(envelope.to_dict()) == canonical_json_v1(
        json.loads(fixture_path.read_text(encoding="utf-8"))
    )
    assert EvidenceEnvelopeV1.from_dict(envelope.to_dict()) == envelope
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict({**payload, "unknown": "rejected"})
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(_fixture("evidence_corrupt.json"))
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(
            {**payload, "figures": [{"figure_id": "missing-source"}]}
        )
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(
            {**payload, "warnings": [{"code": "MISSING_MESSAGE"}]}
        )
    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(
            {**payload, "family_evidence": {"execution_status": "completed"}}
        )


def test_evidence_commit_binds_artifact_projector_and_envelope_digests() -> None:
    envelope = EvidenceEnvelopeV1.from_dict(_fixture("evidence_envelope.json"))
    request = EvidenceCommitRequestV1(
        artifact_admission_ref="admission-1",
        projector_ref=_ref(
            kind="projector",
            logical_id="evidence.ols",
            semantic_version="1.0",
        ),
        envelope_digest=sha256_canonical(envelope.to_dict()),
        idempotency_key="evidence-commit-1",
        supersedes_ref=NotApplicableV1("initial evidence commit"),
        invalidation_refs=(),
    )
    binding = EvidenceCommitBindingV1(
        commit_id="commit-1",
        request_digest=request.request_digest,
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=request.projector_ref,
        envelope_digest=request.envelope_digest,
        idempotency_key=request.idempotency_key,
        transaction_status=TransactionStatusV1.COMMITTED,
        supersedes_ref=request.supersedes_ref,
        invalidation_refs=request.invalidation_refs,
        failure_receipt=NotApplicableV1("commit succeeded"),
    )

    assert EvidenceCommitRequestV1.from_dict(request.to_dict()) == request
    assert EvidenceCommitBindingV1.from_dict(binding.to_dict()) == binding
    assert resolve_idempotent_retry(binding, request) is binding

    changed_envelope = EvidenceCommitRequestV1.from_dict(
        {**request.to_dict(), "envelope_digest": "f" * 64}
    )
    with pytest.raises(EvidencePersistenceContractError) as exc_info:
        resolve_idempotent_retry(binding, changed_envelope)
    assert exc_info.value.code == EVIDENCE_IDEMPOTENCY_CONFLICT

    changed_projector = EvidenceCommitRequestV1(
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=_ref(
            kind="projector",
            logical_id="evidence.ols",
            semantic_version="1.1",
        ),
        envelope_digest=request.envelope_digest,
        idempotency_key=request.idempotency_key,
        supersedes_ref=request.supersedes_ref,
        invalidation_refs=request.invalidation_refs,
    )
    with pytest.raises(EvidencePersistenceContractError) as exc_info:
        resolve_idempotent_retry(binding, changed_projector)
    assert exc_info.value.code == EVIDENCE_IDEMPOTENCY_CONFLICT

    different_key = EvidenceCommitRequestV1(
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=request.projector_ref,
        envelope_digest=request.envelope_digest,
        idempotency_key="evidence-commit-2",
        supersedes_ref=request.supersedes_ref,
        invalidation_refs=request.invalidation_refs,
    )
    with pytest.raises(EvidencePersistenceContractError) as exc_info:
        resolve_idempotent_retry(binding, different_key)
    assert exc_info.value.code == EVIDENCE_IDEMPOTENCY_KEY_MISMATCH

    with pytest.raises(ContractError):
        EvidenceCommitBindingV1(
            **{
                **binding.__dict__,
                "request_digest": "0" * 64,
            }
        )
    with pytest.raises(ContractError):
        EvidenceCommitBindingV1(
            **{
                **binding.__dict__,
                "transaction_status": TransactionStatusV1.FAILED,
            }
        )
    with pytest.raises(ContractError):
        EvidenceCommitBindingV1(
            **{
                **binding.__dict__,
                "transaction_status": TransactionStatusV1.INVALIDATED,
            }
        )

    failed_binding = EvidenceCommitBindingV1(
        **{
            **binding.__dict__,
            "transaction_status": TransactionStatusV1.FAILED,
            "failure_receipt": FailureReceiptV1(
                code="PERSISTENCE_FAILED",
                message="The immutable commit failed.",
                retryable=True,
                evidence_refs=("failure-1",),
            ),
        }
    )
    assert EvidenceCommitBindingV1.from_dict(failed_binding.to_dict()) == failed_binding

    invalidated_request = EvidenceCommitRequestV1(
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=request.projector_ref,
        envelope_digest=request.envelope_digest,
        idempotency_key="evidence-invalidation-1",
        supersedes_ref="commit-1",
        invalidation_refs=("artifact-invalidated-1",),
    )
    invalidated_binding = EvidenceCommitBindingV1(
        commit_id="commit-2",
        request_digest=invalidated_request.request_digest,
        artifact_admission_ref=invalidated_request.artifact_admission_ref,
        projector_ref=invalidated_request.projector_ref,
        envelope_digest=invalidated_request.envelope_digest,
        idempotency_key=invalidated_request.idempotency_key,
        transaction_status=TransactionStatusV1.INVALIDATED,
        supersedes_ref=invalidated_request.supersedes_ref,
        invalidation_refs=invalidated_request.invalidation_refs,
        failure_receipt=NotApplicableV1("invalidation is not a commit failure"),
    )
    assert EvidenceCommitBindingV1.from_dict(invalidated_binding.to_dict()) == invalidated_binding


def test_resolver_rejects_duplicate_and_unresolved_refs() -> None:
    available = _ref()

    with pytest.raises(ContractRefError) as exc_info:
        ContractRefResolverV1((available, available))
    assert exc_info.value.code == CONTRACT_DUPLICATE

    resolver = ContractRefResolverV1((available,))
    assert resolver.resolve(available) == available

    for unresolved in (
        _ref(logical_id="model.logit"),
        _ref(semantic_version="1.1"),
    ):
        with pytest.raises(ContractRefError) as exc_info:
            resolver.resolve(unresolved)
        assert exc_info.value.code == CONTRACT_UNRESOLVED

    wrong_digest = _ref(payload={"different": True})
    with pytest.raises(ContractRefError) as exc_info:
        resolver.resolve(wrong_digest)
    assert exc_info.value.code == CONTRACT_DIGEST_MISMATCH


def test_major_version_mismatch_is_not_silently_coerced() -> None:
    resolver = ContractRefResolverV1((_ref(semantic_version="1.0"),))

    with pytest.raises(ContractRefError) as exc_info:
        resolver.resolve(_ref(semantic_version="2.0"))

    assert exc_info.value.code == CONTRACT_MAJOR_INCOMPATIBLE
