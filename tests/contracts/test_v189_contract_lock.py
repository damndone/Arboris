from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import get_type_hints

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
    DistributionRefV1,
    EvidenceEnvelopeV1,
    EvidenceReasonV1,
    IntervalV1,
    MultipleComparisonV1,
    NotApplicableV1,
    NumericFactV1,
    OracleCheckV1,
    SourceSelectorV1,
    ValidationSummaryV1,
    WeightBasisV1,
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
_EVIDENCE_FIXTURE_CANONICAL_SHA256 = (
    "4b26cf04a29fed51795a04aac8102bf3af55659efaa817829f897cb00c37de65"
)


class _DictSubclass(dict[str, object]):
    pass


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(text: str) -> dict[str, object]:
    value = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    if type(value) is not dict:
        raise ValueError("fixture root must be a JSON object")
    return value


def _fixture(name: str) -> dict[str, object]:
    return _load_json((_FIXTURE_ROOT / name).read_text(encoding="utf-8"))


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


def _reason(code: str) -> dict[str, object]:
    return {
        "code": code,
        "message": f"{code} reason.",
        "source_refs": [f"source:{code.lower()}"],
    }


def _empty_evidence() -> dict[str, object]:
    return {
        "numeric_facts": [],
        "figures": [],
        "validation_summary": {
            "levels_present": [],
            "minimum_required": "none",
            "requirement_status": "not_applicable",
        },
    }


def _commit_pair(
    *,
    invalidation_refs: tuple[str, ...] = (),
    idempotency_key: str = "evidence-commit-1",
) -> tuple[EvidenceCommitRequestV1, EvidenceCommitBindingV1]:
    request = EvidenceCommitRequestV1(
        artifact_admission_ref="admission-1",
        projector_ref=_ref(kind="projector", logical_id="evidence.ols"),
        envelope_digest="a" * 64,
        idempotency_key=idempotency_key,
        supersedes_ref=NotApplicableV1("initial commit"),
        invalidation_refs=invalidation_refs,
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
    return request, binding


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


def test_duplicate_oracle_check_ids_are_rejected_before_validation_resolution() -> None:
    fact = _fixture("evidence_envelope.json")["numeric_facts"][0]  # type: ignore[index]
    duplicated = {
        **fact,
        "oracle_checks": [fact["oracle_checks"][0], fact["oracle_checks"][0]],
    }

    with pytest.raises(ContractError):
        NumericFactV1.from_dict(duplicated)


def test_duplicate_numeric_fact_ids_are_rejected_before_figure_resolution() -> None:
    payload = _fixture("evidence_envelope.json")
    facts = payload["numeric_facts"]
    duplicated = {**payload, "numeric_facts": [*facts, facts[0]]}

    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(duplicated)


def test_public_wire_decoders_require_exact_builtin_dicts() -> None:
    payload = _fixture("evidence_envelope.json")
    fact = payload["numeric_facts"][0]  # type: ignore[index]
    request = EvidenceCommitRequestV1(
        artifact_admission_ref="admission-1",
        projector_ref=_ref(kind="projector", logical_id="evidence.ols"),
        envelope_digest="a" * 64,
        idempotency_key="commit-1",
        supersedes_ref=NotApplicableV1("initial commit"),
        invalidation_refs=(),
    )
    binding = EvidenceCommitBindingV1(
        commit_id="binding-1",
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
    decoder_payloads = (
        (NotApplicableV1.from_dict, {"status": "not_applicable", "reason": "unused"}),
        (EvidenceReasonV1.from_dict, _reason("WIRE")),
        (DenominatorV1.from_dict, fact["denominator"]),
        (WeightBasisV1.from_dict, fact["weight"]),
        (IntervalV1.from_dict, fact["confidence_interval"]),
        (DistributionRefV1.from_dict, fact["reference_distribution"]),
        (MultipleComparisonV1.from_dict, fact["multiple_comparison"]),
        (SourceSelectorV1.from_dict, fact["source_selector"]),
        (OracleCheckV1.from_dict, fact["oracle_checks"][0]),
        (NumericFactV1.from_dict, fact),
        (ValidationSummaryV1.from_dict, payload["validation_summary"]),
        (EvidenceEnvelopeV1.from_dict, payload),
        (EvidenceCommitRequestV1.from_dict, request.to_dict()),
        (
            FailureReceiptV1.from_dict,
            {
                "code": "FAILED",
                "message": "Commit failed.",
                "retryable": True,
                "evidence_refs": ["failure-1"],
            },
        ),
        (EvidenceCommitBindingV1.from_dict, binding.to_dict()),
    )

    for decoder, wire_payload in decoder_payloads:
        with pytest.raises(ContractError):
            decoder(_DictSubclass(wire_payload))

    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(
            {**payload, "method": _DictSubclass(payload["method"])}
        )
    with pytest.raises(ContractError):
        EvidenceCommitRequestV1.from_dict(
            {**request.to_dict(), "projector_ref": _DictSubclass(request.projector_ref.to_dict())}
        )
    with pytest.raises(ContractError):
        EvidenceCommitBindingV1.from_dict(
            {
                **binding.to_dict(),
                "failure_receipt": _DictSubclass(binding.failure_receipt.to_dict()),
            }
        )


def test_nested_frozen_json_rejects_nfc_equivalent_duplicate_keys() -> None:
    payload = _fixture("evidence_envelope.json")
    payload["method"] = {
        "nested": {
            "é": "precomposed",
            "e\u0301": "decomposed",
        }
    }

    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(payload)


def test_malformed_numeric_and_oracle_values_have_stable_contract_errors() -> None:
    fact = _fixture("evidence_envelope.json")["numeric_facts"][0]  # type: ignore[index]
    largest_portable_integer = 9_007_199_254_740_991
    portable = NumericFactV1.from_dict({**fact, "value": largest_portable_integer})
    assert portable.value == largest_portable_integer
    assert f'"value":{largest_portable_integer}' in canonical_json_v1(
        portable.to_dict()
    )

    for malformed in (True, [], {}, {"unhashable"}):
        with pytest.raises(ContractError):
            NumericFactV1.from_dict({**fact, "value": malformed})

    malformed_oracle = {
        **fact["oracle_checks"][0],
        "status": ["pass"],
    }
    with pytest.raises(ContractError):
        OracleCheckV1.from_dict(malformed_oracle)

    for degrees_of_freedom in (0.0, -1.0):
        with pytest.raises(ContractError):
            DistributionRefV1.from_dict(
                {
                    **fact["reference_distribution"],
                    "degrees_of_freedom": degrees_of_freedom,
                }
            )


def test_nonportable_evidence_integers_fail_before_canonical_serialization() -> None:
    fact = _fixture("evidence_envelope.json")["numeric_facts"][0]  # type: ignore[index]
    largest_portable_integer = 9_007_199_254_740_991

    for nonportable in (
        largest_portable_integer + 1,
        -(largest_portable_integer + 1),
        10**10_000,
    ):
        with pytest.raises(ContractError):
            NumericFactV1.from_dict({**fact, "value": nonportable})
        with pytest.raises(ContractError):
            DenominatorV1.from_dict(
                {"kind": "rows", "value": nonportable, "unit": "row"}
            )

    denominator = DenominatorV1.from_dict(
        {"kind": "rows", "value": largest_portable_integer, "unit": "row"}
    )
    assert denominator.value == largest_portable_integer


def test_frozen_json_mappings_translate_cycles_and_nonportable_ints() -> None:
    payload = _fixture("evidence_envelope.json")
    cyclic: dict[str, object] = {}
    cyclic["nested"] = {"cycle": cyclic}

    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict({**payload, "method": cyclic})
    for nonportable in (9_007_199_254_740_992, 10**10_000):
        with pytest.raises(ContractError):
            EvidenceEnvelopeV1.from_dict(
                {**payload, "method": {"nested": {"value": nonportable}}}
            )


def test_task2_from_dict_annotations_match_exact_builtin_dict_boundary() -> None:
    record_types = (
        NotApplicableV1,
        EvidenceReasonV1,
        DenominatorV1,
        WeightBasisV1,
        IntervalV1,
        DistributionRefV1,
        MultipleComparisonV1,
        SourceSelectorV1,
        OracleCheckV1,
        NumericFactV1,
        ValidationSummaryV1,
        EvidenceEnvelopeV1,
        EvidenceCommitRequestV1,
        FailureReceiptV1,
        EvidenceCommitBindingV1,
    )

    for record_type in record_types:
        assert get_type_hints(record_type.from_dict)["value"] == dict[str, object]


@pytest.mark.parametrize(
    "updates",
    [
        {"execution_reasons": [_reason("UNEXPECTED")]},
        {
            "execution_status": "partial",
            "completeness_status": "degraded",
            "degradation_reasons": [_reason("DEGRADED")],
        },
        {
            "execution_status": "partial",
            "execution_reasons": [_reason("PARTIAL")],
        },
        {
            "execution_status": "blocked",
            "completeness_status": "insufficient",
            "execution_reasons": [_reason("BLOCKED")],
            "degradation_reasons": [_reason("INSUFFICIENT")],
            **_empty_evidence(),
        },
        {
            "execution_status": "failed",
            "completeness_status": "insufficient",
            "execution_reasons": [_reason("FAILED")],
            "degradation_reasons": [_reason("INSUFFICIENT")],
            **_empty_evidence(),
        },
        {
            "execution_status": "blocked",
            "availability": "not_available",
            "completeness_status": "degraded",
            "execution_reasons": [_reason("BLOCKED")],
            "availability_reasons": [_reason("NOT_AVAILABLE")],
            "degradation_reasons": [_reason("DEGRADED")],
            **_empty_evidence(),
        },
        {
            "execution_status": "failed",
            "availability": "not_applicable",
            "completeness_status": "degraded",
            "execution_reasons": [_reason("FAILED")],
            "availability_reasons": [_reason("NOT_APPLICABLE")],
            "degradation_reasons": [_reason("DEGRADED")],
            **_empty_evidence(),
        },
        {
            "availability": "not_available",
            "availability_reasons": [_reason("NOT_AVAILABLE")],
            "completeness_status": "insufficient",
            "degradation_reasons": [_reason("INSUFFICIENT")],
            "figures": [],
        },
        {
            "availability": "not_applicable",
            "availability_reasons": [_reason("NOT_APPLICABLE")],
            "completeness_status": "insufficient",
            "degradation_reasons": [_reason("INSUFFICIENT")],
            "numeric_facts": [],
            "validation_summary": {
                "levels_present": [],
                "minimum_required": "none",
                "requirement_status": "not_applicable",
            },
        },
        {
            "availability": "not_available",
            "availability_reasons": [_reason("NOT_AVAILABLE")],
            **_empty_evidence(),
        },
    ],
    ids=[
        "completed-forbids-execution-reasons",
        "partial-requires-execution-reason",
        "partial-cannot-be-complete",
        "blocked-cannot-be-available",
        "failed-cannot-be-available",
        "blocked-requires-insufficient-or-not-applicable",
        "failed-requires-insufficient-or-not-applicable",
        "not-available-forbids-numeric-facts",
        "not-applicable-forbids-figures",
        "complete-requires-available",
    ],
)
def test_evidence_envelope_rejects_contradictory_state_matrix(
    updates: dict[str, object],
) -> None:
    payload = {**_fixture("evidence_envelope.json"), **updates}

    with pytest.raises(ContractError):
        EvidenceEnvelopeV1.from_dict(payload)


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {
            "completeness_status": "degraded",
            "degradation_reasons": [_reason("DEGRADED")],
        },
        {
            "execution_status": "partial",
            "completeness_status": "degraded",
            "execution_reasons": [_reason("PARTIAL")],
            "degradation_reasons": [_reason("DEGRADED")],
        },
        {
            "execution_status": "blocked",
            "availability": "not_available",
            "completeness_status": "insufficient",
            "execution_reasons": [_reason("BLOCKED")],
            "availability_reasons": [_reason("NOT_AVAILABLE")],
            "degradation_reasons": [_reason("INSUFFICIENT")],
            **_empty_evidence(),
        },
        {
            "execution_status": "failed",
            "availability": "not_applicable",
            "completeness_status": "not_applicable",
            "execution_reasons": [_reason("FAILED")],
            "availability_reasons": [_reason("NOT_APPLICABLE")],
            "degradation_reasons": [_reason("NOT_APPLICABLE")],
            **_empty_evidence(),
        },
        {
            "execution_status": "partial",
            "availability": "not_available",
            "completeness_status": "insufficient",
            "execution_reasons": [_reason("PARTIAL")],
            "availability_reasons": [_reason("NOT_AVAILABLE")],
            "degradation_reasons": [_reason("INSUFFICIENT")],
            **_empty_evidence(),
        },
    ],
    ids=[
        "completed-available-complete",
        "completed-available-degraded",
        "partial-available-degraded",
        "blocked-not-available-insufficient",
        "failed-not-applicable",
        "partial-not-available-insufficient",
    ],
)
def test_evidence_envelope_accepts_valid_orthogonal_state_matrix(
    updates: dict[str, object],
) -> None:
    envelope = EvidenceEnvelopeV1.from_dict(
        {**_fixture("evidence_envelope.json"), **updates}
    )

    assert envelope.execution_status.value == updates.get(
        "execution_status", "completed"
    )
    assert envelope.availability.value == updates.get("availability", "available")
    assert envelope.completeness_status.value == updates.get(
        "completeness_status", "complete"
    )


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
    fixture_text = fixture_path.read_text(encoding="utf-8")
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

    canonical_bytes = canonical_json_v1(envelope.to_dict()).encode("utf-8")
    assert canonical_bytes == canonical_json_v1(_load_json(fixture_text)).encode(
        "utf-8"
    )
    assert (
        hashlib.sha256(canonical_bytes).hexdigest()
        == _EVIDENCE_FIXTURE_CANONICAL_SHA256
    )
    assert EvidenceEnvelopeV1.from_dict(envelope.to_dict()) == envelope
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _load_json('{"nested":{"duplicate":1,"duplicate":2}}')
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


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("artifact_admission_ref", "admission-2"),
        (
            "projector_ref",
            _ref(
                kind="projector",
                logical_id="evidence.ols",
                semantic_version="1.1",
            ),
        ),
        ("envelope_digest", "b" * 64),
        ("idempotency_key", "evidence-commit-2"),
        ("supersedes_ref", "commit-0"),
        ("invalidation_refs", ("invalidation-1",)),
        ("request_digest", "0" * 64),
    ],
)
def test_evidence_binding_rejects_each_request_bound_field_mutation(
    field_name: str,
    replacement: object,
) -> None:
    _, binding = _commit_pair()

    with pytest.raises(ContractError):
        EvidenceCommitBindingV1(
            **{
                **binding.__dict__,
                field_name: replacement,
            }
        )


@pytest.mark.parametrize(
    "invalid_digest",
    ["f" * 63, "F" * 64, "sha256:" + "f" * 64, "not-a-digest"],
)
def test_persistence_records_reject_malformed_digests(invalid_digest: str) -> None:
    request, binding = _commit_pair()

    with pytest.raises(ContractError):
        EvidenceCommitRequestV1.from_dict(
            {**request.to_dict(), "envelope_digest": invalid_digest}
        )
    with pytest.raises(ContractError):
        EvidenceCommitBindingV1.from_dict(
            {**binding.to_dict(), "request_digest": invalid_digest}
        )
    with pytest.raises(ContractError):
        EvidenceCommitBindingV1.from_dict(
            {**binding.to_dict(), "envelope_digest": invalid_digest}
        )


def test_transaction_status_and_failure_receipt_matrix_is_strict() -> None:
    _, binding = _commit_pair()
    failure = FailureReceiptV1(
        code="PERSISTENCE_FAILED",
        message="The immutable commit failed.",
        retryable=True,
        evidence_refs=("failure-1",),
    )
    _, invalidation_binding = _commit_pair(
        invalidation_refs=("invalidation-1",),
        idempotency_key="evidence-invalidation-1",
    )

    invalid_variants = (
        {**binding.__dict__, "failure_receipt": failure},
        {
            **binding.__dict__,
            "transaction_status": TransactionStatusV1.FAILED,
        },
        {
            **binding.__dict__,
            "transaction_status": TransactionStatusV1.INVALIDATED,
        },
        {
            **invalidation_binding.__dict__,
            "transaction_status": TransactionStatusV1.INVALIDATED,
            "failure_receipt": failure,
        },
    )
    for variant in invalid_variants:
        with pytest.raises(ContractError):
            EvidenceCommitBindingV1(**variant)

    failed = EvidenceCommitBindingV1(
        **{
            **binding.__dict__,
            "transaction_status": TransactionStatusV1.FAILED,
            "failure_receipt": failure,
        }
    )
    invalidated = EvidenceCommitBindingV1(
        **{
            **invalidation_binding.__dict__,
            "transaction_status": TransactionStatusV1.INVALIDATED,
        }
    )
    assert failed.transaction_status is TransactionStatusV1.FAILED
    assert invalidated.transaction_status is TransactionStatusV1.INVALIDATED


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
