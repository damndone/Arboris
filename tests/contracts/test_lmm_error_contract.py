from __future__ import annotations

import math

import pytest

from workbench.contracts.agent.repeated_measures import (
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
    LMM_RECOVERY_PATCH,
)
from workbench.contracts.common.envelope import ContractError, PacketEnvelope
from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LmmDiagnostic,
    LmmModelInput,
    build_lmm_result_identity,
)


def _valid_input() -> dict[str, object]:
    return {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    }


def _valid_identity() -> dict[str, object]:
    return {
        "dataset_fingerprint": "dataset-a",
        "analysis_unit": "participant_id",
        "outcome": "score",
        "fixed_effects": ["intercept", "group", "time", "group_time_interaction"],
        "random_effects": ["random_intercept", "random_time_slope"],
        "group": "arm",
        "reference_group": "control",
        "fit_method": "reml",
        "missing_policy": "complete_case_v1",
        "estimator_version": "statsmodels_mixedlm_v1",
        "contract_version": LMM_CONTRACT_VERSION,
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"contract": "x"}, "missing envelope field"),
        ({"contract": "x", "contract_version": "1", "producer_version": "p", "payload": {}, "extra": 1}, "unknown envelope field"),
        ({1: "x"}, "keys must be strings"),
    ],
)
def test_packet_envelope_rejects_non_exact_wire_shape(
    value: object, message: str
) -> None:
    with pytest.raises(ContractError, match=message):
        PacketEnvelope.from_dict(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        {1: "not-a-string-key"},
        {"nested": {"estimate": math.inf}},
        {"items": {"not", "json"}},
    ],
)
def test_packet_envelope_rejects_non_json_payloads(payload: object) -> None:
    with pytest.raises(ContractError):
        PacketEnvelope(
            contract="linear_mixed_effects.result",
            contract_version=LMM_CONTRACT_VERSION,
            producer_version="linear_mixed_effects@1.0",
            payload=payload,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "value",
    [
        {"subject_id": "participant_id"},
        {**_valid_input(), "extra": "not allowed"},
        {**_valid_input(), "subject_id": ""},
        {**_valid_input(), "time": 7},
        {**_valid_input(), "fit_method": "bayes"},
        {**_valid_input(), "fit_method": True},
        {**_valid_input(), "random_slope": 1},
    ],
)
def test_lmm_input_rejects_every_unlocked_or_invalid_semantic(value: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        LmmModelInput.from_dict(value)


def test_lmm_identity_requires_exact_fields_and_json_safe_values() -> None:
    identity = _valid_identity()

    with pytest.raises(ContractError, match="missing LMM result identity field"):
        build_lmm_result_identity({key: value for key, value in identity.items() if key != "group"})
    with pytest.raises(ContractError, match="unknown LMM result identity field"):
        build_lmm_result_identity({**identity, "extra": True})
    with pytest.raises(ContractError, match="finite"):
        build_lmm_result_identity({**identity, "fixed_effects": [math.nan]})


def test_diagnostic_rejects_unsafe_or_automatic_action_candidate() -> None:
    valid_candidate = {
        "action_id": LMM_RECOVERY_ACTION_ID,
        "operation_id": LMM_RECOVERY_OPERATION_ID,
        "patch": LMM_RECOVERY_PATCH,
        "required_confirmation": True,
    }

    for candidate in (
        {**valid_candidate, "required_confirmation": False},
        {**valid_candidate, "operation_id": "dataset.replace"},
        {**valid_candidate, "patch": {"fit_method": "ml"}},
        {**valid_candidate, "extra": True},
    ):
        with pytest.raises(ContractError):
            LmmDiagnostic(
                code="LMM_RANDOM_SLOPE_NEAR_ZERO",
                severity="warning",
                status="complete",
                evidence={"slope_variance": 0.0},
                action_candidate=candidate,
            )


def test_blocking_diagnostic_cannot_expose_an_action_candidate() -> None:
    with pytest.raises(ContractError, match="blocking diagnostic"):
        LmmDiagnostic(
            code="LMM_SUBJECT_ID_MISSING",
            severity="error",
            status="blocked",
            evidence={"column": "participant_id"},
            action_candidate={
                "action_id": LMM_RECOVERY_ACTION_ID,
                "operation_id": LMM_RECOVERY_OPERATION_ID,
                "patch": LMM_RECOVERY_PATCH,
                "required_confirmation": True,
            },
        )
