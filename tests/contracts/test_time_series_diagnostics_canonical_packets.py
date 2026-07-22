from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.time_series_diagnostics import (
    ASSESSMENT_PACKET_CONTRACT,
    FACTS_PACKET_CONTRACT,
    TimeSeriesDiagnosticAssessmentPacket,
    TimeSeriesDiagnosticFactsPacket,
    assessment_content_digest,
    assessment_content_projection,
    envelope_digest,
    facts_content_digest,
    facts_content_projection,
)


_DIGEST = "a" * 64


def _facts_packet(**overrides: object) -> dict[str, object]:
    packet: dict[str, object] = {
        "contract": FACTS_PACKET_CONTRACT,
        "contract_version": "1.0",
        "packet_id": "facts-packet-1",
        "producer_version": "time-series-c1@1",
        "policy_version": "policy-1",
        "run_id": "run-1",
        "execution_timestamp": "2026-07-20T12:00:00Z",
        "input_identity": {
            "dataset_artifact_id": "dataset-1",
            "row_scope_digest": _DIGEST,
            "selected_columns": ["time", "value"],
        },
        "configuration": {"alpha": 0.05, "lag_cap": 12},
        "numeric_runtime_manifest_digest": _DIGEST,
        "facts": {
            "adf": {"p_value": 0.1},
            "ordered_vector": [0.2, -0.0, 0.4],
        },
        "facts_content_digest": "0" * 64,
    }
    packet.update(overrides)
    packet["facts_content_digest"] = facts_content_digest(packet)
    return packet


def _advisory(
    code: str,
    *,
    version: str = "1.0",
    effects_summary: str = "review only",
) -> dict[str, object]:
    return {
        "advisory_code": code,
        "advisory_version": version,
        "evidence_fact_refs": ["facts.trend_evidence", "facts.adf.p_value"],
        "precondition_results": {
            "evidence_available": "true",
            "review_required": "true",
        },
        "source_facts_content_digest": _facts_packet()["facts_content_digest"],
        "decision_policy_version": "policy-1",
        "effects_summary": effects_summary,
        "incompatibility_codes": ["NO_FORECAST_ELIGIBILITY"],
        "input_identity": {"dataset_artifact_id": "dataset-1"},
        "effect": "advisory_only",
        "execution_available": False,
    }


def _assessment_packet(
    *, advisories: list[dict[str, object]] | None = None, **overrides: object
) -> dict[str, object]:
    facts = _facts_packet()
    packet: dict[str, object] = {
        "contract": ASSESSMENT_PACKET_CONTRACT,
        "contract_version": "1.0",
        "packet_id": "assessment-packet-1",
        "producer_version": "time-series-c1@1",
        "run_id": "run-1",
        "execution_timestamp": "2026-07-20T12:00:01Z",
        "facts_packet_id": facts["packet_id"],
        "facts_content_digest": facts["facts_content_digest"],
        "decision_policy_version": "policy-1",
        "assessment_scope": "first_slice_diagnostic_evidence",
        "conclusion": "suitable_with_caveats",
        "caveat_codes": ["NO_FORECAST_ELIGIBILITY", "RAW_LEVEL_CORRELATION_ONLY"],
        "caveat_fact_refs": ["facts.zeta", "facts.adf.p_value"],
        "advisories": advisories
        if advisories is not None
        else [_advisory("REVIEW_TREND_HANDLING"), _advisory("CONSIDER_DIFFERENCING")],
        "assessment_content_digest": "0" * 64,
    }
    packet.update(overrides)
    packet["assessment_content_digest"] = assessment_content_digest(packet)
    return packet


def test_advisory_reorder_is_digest_invariant_and_closed_sets_are_canonicalized() -> None:
    left = _assessment_packet(
        advisories=[_advisory("REVIEW_TREND_HANDLING"), _advisory("CONSIDER_DIFFERENCING")]
    )
    right = _assessment_packet(
        advisories=[_advisory("CONSIDER_DIFFERENCING"), _advisory("REVIEW_TREND_HANDLING")]
    )

    assert assessment_content_digest(left) == assessment_content_digest(right)
    assert assessment_content_projection(left)["caveat_codes"] == [
        "NO_FORECAST_ELIGIBILITY",
        "RAW_LEVEL_CORRELATION_ONLY",
    ]
    assert [
        advisory["advisory_code"] for advisory in assessment_content_projection(left)["advisories"]
    ] == ["CONSIDER_DIFFERENCING", "REVIEW_TREND_HANDLING"]


def test_content_projections_have_exact_contract_locked_field_sets() -> None:
    facts = _facts_packet()
    assessment = _assessment_packet()

    assert set(facts_content_projection(facts)) == {
        "contract",
        "contract_version",
        "producer_version",
        "policy_version",
        "input_identity",
        "configuration",
        "numeric_runtime_manifest_digest",
        "facts",
    }
    assert set(assessment_content_projection(assessment)) == {
        "facts_content_digest",
        "decision_policy_version",
        "assessment_scope",
        "conclusion",
        "caveat_codes",
        "caveat_fact_refs",
        "advisories",
    }


def test_advisory_content_change_changes_assessment_digest() -> None:
    original = _assessment_packet()
    changed_advisory = _advisory(
        "CONSIDER_DIFFERENCING", effects_summary="review and document"
    )
    changed = _assessment_packet(
        advisories=[changed_advisory, _advisory("REVIEW_TREND_HANDLING")]
    )

    assert assessment_content_digest(original) != assessment_content_digest(changed)


def test_assessment_digest_excludes_packet_run_timestamp_and_digest_identity_fields() -> None:
    packet = _assessment_packet()
    baseline = assessment_content_digest(packet)

    for field, value in {
        "packet_id": "assessment-packet-2",
        "run_id": "run-2",
        "execution_timestamp": "2026-07-20T13:00:00Z",
        "facts_packet_id": "facts-packet-2",
        "assessment_content_digest": "f" * 64,
    }.items():
        mutated = {**packet, field: value}
        assert assessment_content_digest(mutated) == baseline, field


def test_facts_digest_excludes_packet_run_timestamp_and_digest_identity_fields() -> None:
    packet = _facts_packet()
    baseline = facts_content_digest(packet)

    for field, value in {
        "packet_id": "facts-packet-2",
        "run_id": "run-2",
        "execution_timestamp": "2026-07-20T13:00:00Z",
        "facts_content_digest": "f" * 64,
    }.items():
        mutated = {**packet, field: value}
        assert facts_content_digest(mutated) == baseline, field


def test_envelope_forged_self_digest_is_ignored_but_reason_change_changes_digest() -> None:
    envelope = {
        "operation_status": "completed",
        "reason_code": "ASSESSMENT_COMPLETED",
        "facts_packet_ref": "facts-packet-1",
        "assessment_packet_ref": "assessment-packet-1",
        "envelope_digest": "0" * 64,
    }

    assert envelope_digest(envelope) == envelope_digest(
        {**envelope, "envelope_digest": "forged"}
    )
    for field, value in {
        "operation_status": "failed",
        "reason_code": "HARD_DATA_INPUT",
        "facts_packet_ref": "facts-packet-2",
        "assessment_packet_ref": "assessment-packet-2",
    }.items():
        assert envelope_digest(envelope) != envelope_digest({**envelope, field: value}), field


def test_mutated_facts_digest_breaks_assessment_validation() -> None:
    facts = _facts_packet()
    assessment = _assessment_packet()
    mutated_facts = deepcopy(facts)
    mutated_facts["facts"] = {"adf": {"p_value": 0.2}, "ordered_vector": [0.2, -0.0, 0.4]}
    mutated_facts["facts_content_digest"] = facts_content_digest(mutated_facts)
    TimeSeriesDiagnosticFactsPacket.from_dict(mutated_facts)

    with pytest.raises(ContractError, match="facts_content_digest"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(
            assessment, facts_packet=mutated_facts
        )


def test_assessment_packet_requires_bound_facts_packet() -> None:
    with pytest.raises(ContractError, match="requires a bound Facts packet"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(_assessment_packet())


def test_public_assessment_constructor_cannot_bypass_facts_binding() -> None:
    with pytest.raises(TypeError, match="facts_packet"):
        TimeSeriesDiagnosticAssessmentPacket(**_assessment_packet())


@pytest.mark.parametrize("field", ["caveat_fact_refs", "advisory_evidence_fact_refs"])
def test_malformed_caveat_and_evidence_fact_refs_fail_closed(field: str) -> None:
    packet = _assessment_packet()
    if field == "caveat_fact_refs":
        packet["caveat_fact_refs"] = ["facts..malformed"]
    else:
        advisories = list(packet["advisories"])
        advisories[0] = {**advisories[0], "evidence_fact_refs": ["facts..malformed"]}
        packet["advisories"] = advisories

    with pytest.raises(ContractError, match="malformed fact reference"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(
            packet, facts_packet=_facts_packet()
        )


def test_facts_packet_rejects_missing_fields() -> None:
    packet = _facts_packet()
    del packet["configuration"]

    with pytest.raises(ContractError, match="missing"):
        TimeSeriesDiagnosticFactsPacket.from_dict(packet)


def test_assessment_packet_rejects_unknown_fields() -> None:
    packet = _assessment_packet()
    packet["unexpected"] = True

    with pytest.raises(ContractError, match="unknown"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(
            packet, facts_packet=_facts_packet()
        )


@pytest.mark.parametrize("result", [{"nested": "true"}, 1])
def test_advisory_precondition_results_reject_nested_or_non_string_values(
    result: object,
) -> None:
    packet = _assessment_packet()
    advisories = list(packet["advisories"])
    advisories[0] = {
        **advisories[0],
        "precondition_results": {"review_required": result},
    }
    packet["advisories"] = advisories

    with pytest.raises(ContractError, match="precondition_results"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(
            packet, facts_packet=_facts_packet()
        )


def test_packets_reject_nonfinite_values_and_malformed_digest_references() -> None:
    nonfinite = _facts_packet()
    nonfinite["facts"] = {"adf": {"p_value": float("nan")}}
    with pytest.raises(ContractError, match="finite"):
        TimeSeriesDiagnosticFactsPacket.from_dict(nonfinite)

    with pytest.raises(ContractError, match="digest"):
        TimeSeriesDiagnosticFactsPacket.from_dict(
            _facts_packet(numeric_runtime_manifest_digest="not-a-digest")
        )

    with pytest.raises(ContractError, match="digest"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(
            _assessment_packet(facts_content_digest="not-a-digest"),
            facts_packet=_facts_packet(),
        )


def test_packet_parsing_wraps_canonical_json_errors_as_contract_errors() -> None:
    facts = _facts_packet()
    facts["facts"] = {"label": "\ud800"}
    with pytest.raises(ContractError, match="canonical JSON"):
        TimeSeriesDiagnosticFactsPacket.from_dict(facts)

    assessment = _assessment_packet()
    advisories = list(assessment["advisories"])
    advisories[0] = {**advisories[0], "effects_summary": "\ud800"}
    assessment["advisories"] = advisories
    with pytest.raises(ContractError, match="canonical JSON"):
        TimeSeriesDiagnosticAssessmentPacket.from_dict(
            assessment, facts_packet=_facts_packet()
        )


def test_public_digest_helpers_wrap_canonical_json_errors_as_contract_errors() -> None:
    facts = _facts_packet()
    facts["facts"] = {"label": "\ud800"}
    with pytest.raises(ContractError, match="canonical JSON"):
        facts_content_digest(facts)

    assessment = _assessment_packet()
    advisories = list(assessment["advisories"])
    advisories[0] = {**advisories[0], "effects_summary": "\ud800"}
    assessment["advisories"] = advisories
    with pytest.raises(ContractError, match="canonical JSON"):
        assessment_content_digest(assessment)


def test_parsed_packet_nested_mappings_are_immutable() -> None:
    facts = TimeSeriesDiagnosticFactsPacket.from_dict(_facts_packet())
    assessment = TimeSeriesDiagnosticAssessmentPacket.from_dict(
        _assessment_packet(), facts_packet=facts
    )

    assert isinstance(facts.facts, MappingProxyType)
    assert isinstance(facts.facts["adf"], MappingProxyType)
    assert isinstance(assessment.advisories[0], MappingProxyType)
    assert isinstance(assessment.advisories[0]["precondition_results"], MappingProxyType)

    facts_adf = facts.facts["adf"]
    assert isinstance(facts_adf, MappingProxyType)
    with pytest.raises(TypeError):
        facts_adf["p_value"] = 0.9
    assessment_preconditions = assessment.advisories[0]["precondition_results"]
    assert isinstance(assessment_preconditions, MappingProxyType)
    with pytest.raises(TypeError):
        assessment_preconditions["review_required"] = "false"


def test_to_dict_returns_deep_copies_without_polluting_parsed_packets() -> None:
    facts = TimeSeriesDiagnosticFactsPacket.from_dict(_facts_packet())
    facts_wire = facts.to_dict()
    assert isinstance(facts_wire["facts"], dict)
    assert isinstance(facts_wire["facts"]["adf"], dict)
    facts_wire["facts"]["adf"]["p_value"] = 0.9
    assert facts.facts["adf"]["p_value"] == 0.1

    assessment = TimeSeriesDiagnosticAssessmentPacket.from_dict(
        _assessment_packet(), facts_packet=facts
    )
    assessment_wire = assessment.to_dict()
    assert isinstance(assessment_wire["advisories"], list)
    assert isinstance(assessment_wire["advisories"][0], dict)
    assert isinstance(assessment_wire["advisories"][0]["precondition_results"], dict)
    assessment_wire["advisories"][0]["precondition_results"]["review_required"] = "false"
    assert (
        assessment.advisories[0]["precondition_results"]["review_required"]
        == "true"
    )


def test_packet_parsing_does_not_mutate_input_mappings() -> None:
    facts = _facts_packet()
    assessment = _assessment_packet()
    facts_before = deepcopy(facts)
    assessment_before = deepcopy(assessment)

    TimeSeriesDiagnosticFactsPacket.from_dict(facts)
    TimeSeriesDiagnosticAssessmentPacket.from_dict(
        assessment, facts_packet=_facts_packet()
    )

    assert facts == facts_before
    assert assessment == assessment_before
