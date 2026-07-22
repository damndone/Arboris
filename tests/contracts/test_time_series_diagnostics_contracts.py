from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.time_series_diagnostics import (
    ACF_METHODS,
    ADF_P_VALUE_STATUSES,
    AdfFact,
    AcfPolicy,
    KpssFact,
    KPSS_P_VALUE_STATUSES,
    LAG_ZERO_POLICIES,
    OperationExecutionEnvelope,
    PACF_METHODS,
    PacfPolicy,
    TimeSeriesDiagnosticProposal,
)


def _envelope(
    *,
    operation_status: str,
    reason_code: str = "ASSESSMENT_COMPLETED",
    facts_packet_ref: str | None = None,
    assessment_packet_ref: str | None = None,
) -> dict[str, object]:
    return {
        "operation_status": operation_status,
        "reason_code": reason_code,
        "facts_packet_ref": facts_packet_ref,
        "assessment_packet_ref": assessment_packet_ref,
    }


@pytest.mark.parametrize(
    ("operation_status", "reason_code", "facts_packet_ref", "assessment_packet_ref"),
    [
        ("completed", "ASSESSMENT_COMPLETED", "facts:fixture", "assessment:fixture"),
        ("completed", "HARD_DATA_INPUT", "facts:fixture", "assessment:fixture"),
        ("rejected", "USER_REJECTED", None, None),
        ("failed", "EXECUTOR_TIMEOUT", None, None),
        ("failed", "EXECUTOR_OOM", None, None),
        ("failed", "TERMINATED_EXECUTOR", None, None),
        ("failed", "CORRUPT_PACK_OUTPUT", None, None),
        ("cancelled", "USER_CANCELLED", None, None),
    ],
)
def test_execution_envelope_allows_only_legal_status_reference_combinations(
    operation_status: str,
    reason_code: str,
    facts_packet_ref: str | None,
    assessment_packet_ref: str | None,
) -> None:
    envelope = OperationExecutionEnvelope.from_dict(
        _envelope(
            operation_status=operation_status,
            reason_code=reason_code,
            facts_packet_ref=facts_packet_ref,
            assessment_packet_ref=assessment_packet_ref,
        )
    )

    assert envelope.operation_status == operation_status
    assert envelope.to_dict() == _envelope(
        operation_status=operation_status,
        reason_code=reason_code,
        facts_packet_ref=facts_packet_ref,
        assessment_packet_ref=assessment_packet_ref,
    )


@pytest.mark.parametrize(
    ("operation_status", "reason_code"),
    [
        ("rejected", "USER_REJECTED"),
        ("failed", "EXECUTOR_TIMEOUT"),
        ("cancelled", "USER_CANCELLED"),
    ],
)
def test_non_completed_execution_envelope_rejects_packet_references(
    operation_status: str,
    reason_code: str,
) -> None:
    with pytest.raises(ContractError, match="packet refs require completed"):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status=operation_status,
                reason_code=reason_code,
                facts_packet_ref="facts:forbidden",
                assessment_packet_ref="assessment:forbidden",
            )
        )


@pytest.mark.parametrize(
    ("facts_packet_ref", "assessment_packet_ref"),
    [(None, "assessment:fixture"), ("facts:fixture", None), (None, None)],
)
def test_completed_execution_envelope_requires_both_packet_references(
    facts_packet_ref: str | None,
    assessment_packet_ref: str | None,
) -> None:
    with pytest.raises(ContractError, match="completed requires both packet refs"):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status="completed",
                facts_packet_ref=facts_packet_ref,
                assessment_packet_ref=assessment_packet_ref,
            )
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"unknown": True}, "unknown operation execution envelope field"),
        ({"operation_status": "queued"}, "operation_status"),
        ({"reason_code": "UNDECLARED_REASON"}, "reason_code"),
    ],
)
def test_execution_envelope_rejects_unknown_fields_statuses_and_reasons(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ContractError, match=message):
        OperationExecutionEnvelope.from_dict(
            {
                **_envelope(
                    operation_status="completed",
                    facts_packet_ref="facts:fixture",
                    assessment_packet_ref="assessment:fixture",
                ),
                **override,
            }
        )


def test_execution_envelope_rejects_fixture_identity_as_a_public_reason() -> None:
    with pytest.raises(ContractError, match="reason_code"):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status="completed",
                reason_code="FIXTURE_STATE",
                facts_packet_ref="facts:fixture",
                assessment_packet_ref="assessment:fixture",
            )
        )


@pytest.mark.parametrize(
    ("operation_status", "reason_code", "facts_packet_ref", "assessment_packet_ref"),
    [
        ("completed", "EXECUTOR_TIMEOUT", "facts:fixture", "assessment:fixture"),
        ("failed", "HARD_DATA_INPUT", None, None),
    ],
)
def test_execution_envelope_rejects_reason_codes_for_another_terminal_status(
    operation_status: str,
    reason_code: str,
    facts_packet_ref: str | None,
    assessment_packet_ref: str | None,
) -> None:
    with pytest.raises(
        ContractError, match="reason_code is not allowed for operation_status"
    ):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status=operation_status,
                reason_code=reason_code,
                facts_packet_ref=facts_packet_ref,
                assessment_packet_ref=assessment_packet_ref,
            )
        )


def _proposal(
    *,
    grid_regularity: str = "exact_regular",
    grid_basis: str = "contiguous_integer_step",
    semantic_frequency_source: str = "none",
    usable_observation_count: object = 24,
    seasonal_candidate_period: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "grid_regularity": grid_regularity,
        "grid_basis": grid_basis,
        "semantic_frequency_source": semantic_frequency_source,
        "usable_observation_count": usable_observation_count,
        "seasonal_candidate_period": seasonal_candidate_period,
    }


def test_regular_grid_without_semantic_frequency_accepts_lag_step_candidate() -> None:
    proposal = TimeSeriesDiagnosticProposal.from_dict(
        _proposal(
            seasonal_candidate_period={
                "value": 12,
                "unit": "lag_steps",
                "source": "user_confirmed",
            }
        )
    )

    candidate = proposal.seasonal_candidate_period
    assert candidate is not None
    assert candidate["unit"] == "lag_steps"


@pytest.mark.parametrize("source", ["user_confirmed", "artifact_metadata"])
def test_candidate_period_accepts_each_declared_provenance_source(source: str) -> None:
    proposal = TimeSeriesDiagnosticProposal.from_dict(
        _proposal(
            seasonal_candidate_period={
                "value": 12,
                "unit": "lag_steps",
                "source": source,
            }
        )
    )

    candidate = proposal.seasonal_candidate_period
    assert candidate is not None
    assert candidate["source"] == source


def test_candidate_period_source_none_is_explicitly_accepted_as_no_provenance() -> None:
    proposal = TimeSeriesDiagnosticProposal.from_dict(
        _proposal(
            seasonal_candidate_period={
                "value": 12,
                "unit": "lag_steps",
                "source": "none",
            }
        )
    )

    candidate = proposal.seasonal_candidate_period
    assert candidate is not None
    assert candidate["source"] == "none"


def test_proposal_freezes_candidate_input_and_thaws_independent_output() -> None:
    candidate_input = {
        "value": 12,
        "unit": "lag_steps",
        "source": "user_confirmed",
    }
    proposal = TimeSeriesDiagnosticProposal.from_dict(
        _proposal(seasonal_candidate_period=candidate_input)
    )

    stored_candidate = proposal.seasonal_candidate_period
    assert stored_candidate is not None
    assert isinstance(stored_candidate, MappingProxyType)

    candidate_input["value"] = 6
    candidate_input["source"] = "artifact_metadata"
    assert stored_candidate["value"] == 12
    assert stored_candidate["source"] == "user_confirmed"

    output = proposal.to_dict()
    output_candidate = output["seasonal_candidate_period"]
    assert isinstance(output_candidate, dict)
    output_candidate["value"] = 3
    assert stored_candidate["value"] == 12


@pytest.mark.parametrize("missing_field", ["value", "unit", "source"])
def test_candidate_period_rejects_missing_fields(missing_field: str) -> None:
    candidate_period = {
        "value": 12,
        "unit": "lag_steps",
        "source": "user_confirmed",
    }
    del candidate_period[missing_field]

    with pytest.raises(ContractError, match="missing seasonal candidate period field"):
        TimeSeriesDiagnosticProposal.from_dict(
            _proposal(seasonal_candidate_period=candidate_period)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("grid_regularity", "guessed_regular"),
        ("grid_basis", "inferred_frequency"),
        ("semantic_frequency_source", "heuristic"),
    ],
)
def test_time_semantics_reject_unknown_closed_enum_values(
    field: str, value: str
) -> None:
    with pytest.raises(ContractError, match=field):
        TimeSeriesDiagnosticProposal.from_dict({**_proposal(), field: value})


@pytest.mark.parametrize(
    "candidate_period",
    [
        {"value": True, "unit": "lag_steps", "source": "user_confirmed"},
        {"value": False, "unit": "lag_steps", "source": "user_confirmed"},
        {"value": 1, "unit": "lag_steps", "source": "user_confirmed"},
        {"value": 24, "unit": "lag_steps", "source": "user_confirmed"},
        {"value": 2.0, "unit": "lag_steps", "source": "user_confirmed"},
        {"value": 12, "unit": "calendar_months", "source": "user_confirmed"},
        {"value": 12, "unit": "lag_steps", "source": "guessed"},
    ],
)
def test_time_semantics_reject_malformed_candidate_period(
    candidate_period: dict[str, object],
) -> None:
    with pytest.raises(ContractError, match="seasonal_candidate_period"):
        TimeSeriesDiagnosticProposal.from_dict(
            _proposal(seasonal_candidate_period=candidate_period)
        )


def test_time_semantics_reject_unknown_proposal_fields() -> None:
    with pytest.raises(ContractError, match="unknown time-series diagnostic proposal field"):
        TimeSeriesDiagnosticProposal.from_dict({**_proposal(), "unexpected": True})


@pytest.mark.parametrize("usable_observation_count", [True, False, 24.0, 0, -1])
def test_time_semantics_rejects_invalid_usable_observation_count_types_and_bounds(
    usable_observation_count: object,
) -> None:
    with pytest.raises(ContractError, match="usable_observation_count"):
        TimeSeriesDiagnosticProposal.from_dict(
            _proposal(usable_observation_count=usable_observation_count)
        )


def _adf_fact(*, p_value_status: str = "approximate") -> dict[str, object]:
    return {"p_value_status": p_value_status}


def _kpss_fact(*, p_value_status: str = "lower_bound") -> dict[str, object]:
    return {"p_value_status": p_value_status}


@pytest.mark.parametrize("p_value_status", ["approximate", "unavailable"])
def test_adf_contract_accepts_only_declared_non_exact_p_value_status(
    p_value_status: str,
) -> None:
    assert AdfFact.from_dict(_adf_fact(p_value_status=p_value_status)).p_value_status == (
        p_value_status
    )


@pytest.mark.parametrize(
    "p_value_status", ["exact", "lower_bound", "upper_bound", "unknown"]
)
def test_adf_contract_rejects_exact_and_unknown_p_value_status(
    p_value_status: str,
) -> None:
    with pytest.raises(ContractError, match="ADF p_value_status"):
        AdfFact.from_dict(_adf_fact(p_value_status=p_value_status))


@pytest.mark.parametrize(
    "p_value_status",
    ["approximate", "lower_bound", "upper_bound", "unavailable"],
)
def test_kpss_contract_accepts_only_declared_p_value_status(
    p_value_status: str,
) -> None:
    assert KpssFact.from_dict(_kpss_fact(p_value_status=p_value_status)).p_value_status == (
        p_value_status
    )


@pytest.mark.parametrize("p_value_status", ["exact", "unknown"])
def test_kpss_contract_rejects_exact_and_unknown_p_value_status(
    p_value_status: str,
) -> None:
    with pytest.raises(ContractError, match="KPSS p_value_status"):
        KpssFact.from_dict(_kpss_fact(p_value_status=p_value_status))


ContractParser = Callable[[Mapping[str, object]], object]


@pytest.mark.parametrize(
    ("factory", "payload", "message"),
    [
        (AdfFact.from_dict, _adf_fact(), "unknown ADF fact field"),
        (KpssFact.from_dict, _kpss_fact(), "unknown KPSS fact field"),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "unknown PACF policy field",
        ),
    ],
)
def test_d04_contracts_reject_unknown_fields(
    factory: ContractParser, payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ContractError, match=message):
        factory({**payload, "unexpected": True})


@pytest.mark.parametrize(
    ("factory", "payload", "field", "value", "message"),
    [
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "method",
            "unknown",
            "ACF method",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "lag_zero",
            "excluded",
            "ACF lag_zero",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            True,
            "confidence_level",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            math.nan,
            "confidence_level",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            math.inf,
            "confidence_level",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            1,
            "confidence_level",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            0.0,
            "confidence_level",
        ),
        (
            AcfPolicy.from_dict,
            {"method": "standard", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            1.0,
            "confidence_level",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "method",
            "unknown",
            "PACF method",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "lag_zero",
            "excluded",
            "PACF lag_zero",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            False,
            "confidence_level",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            math.nan,
            "confidence_level",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            -math.inf,
            "confidence_level",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            "0.95",
            "confidence_level",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            0.0,
            "confidence_level",
        ),
        (
            PacfPolicy.from_dict,
            {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95},
            "confidence_level",
            1.0,
            "confidence_level",
        ),
    ],
)
def test_d04_policies_reject_invalid_method_lag_zero_and_confidence_values(
    factory: ContractParser,
    payload: dict[str, object],
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ContractError, match=message):
        factory({**payload, field: value})


def test_d04_policy_manifest_has_exact_statistical_contract_values() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/superpowers/contracts/time-series-diagnostics/v1/policy-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["alpha"] == 0.05
    assert manifest["adf"] == {
        "regression": "c",
        "p_value_statuses": ["approximate", "unavailable"],
    }
    assert manifest["kpss"] == {
        "null": "level_stationarity",
        "p_value_statuses": [
            "approximate",
            "lower_bound",
            "upper_bound",
            "unavailable",
        ],
    }
    assert manifest["acf"] == {
        "method": "standard",
        "lag_zero": "included",
        "confidence_level": 0.95,
    }
    assert manifest["pacf"] == {
        "method": "ywm",
        "lag_zero": "included",
        "confidence_level": 0.95,
    }
    assert set(manifest["adf"]["p_value_statuses"]) == set(ADF_P_VALUE_STATUSES)
    assert set(manifest["kpss"]["p_value_statuses"]) == set(KPSS_P_VALUE_STATUSES)
    assert ACF_METHODS == {manifest["acf"]["method"]}
    assert PACF_METHODS == {manifest["pacf"]["method"]}
    assert LAG_ZERO_POLICIES == {
        manifest["acf"]["lag_zero"],
        manifest["pacf"]["lag_zero"],
    }
    assert manifest["acf"]["confidence_level"] == 0.95
    assert manifest["pacf"]["confidence_level"] == 0.95
    mandatory_caveats = {
        "RAW_LEVEL_CORRELATION_ONLY",
        "NO_MODEL_ORDER_INFERENCE",
        "LEVEL_STATIONARITY_ONLY",
        "NO_FORECAST_ELIGIBILITY",
        "NO_MODEL_SELECTION",
        "STRUCTURAL_BREAKS_NOT_ASSESSED",
    }
    assert set(manifest["mandatory_caveat_codes"]) == mandatory_caveats
    assert len(manifest["mandatory_caveat_codes"]) == len(mandatory_caveats)


def test_statistical_mechanics_rejects_unknown_fields_and_keeps_lag_zero_policy() -> None:
    acf = AcfPolicy.from_dict(
        {"method": "standard", "lag_zero": "included", "confidence_level": 0.95}
    )
    pacf = PacfPolicy.from_dict(
        {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95}
    )

    assert acf.lag_zero == "included"
    assert pacf.method == "ywm"
    with pytest.raises(ContractError, match="unknown ACF policy field"):
        AcfPolicy.from_dict(
            {
                "method": "standard",
                "lag_zero": "included",
                "confidence_level": 0.95,
                "unexpected": True,
            }
        )
