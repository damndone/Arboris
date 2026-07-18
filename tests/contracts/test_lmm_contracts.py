from __future__ import annotations

import math

import pytest

from workbench.contracts.agent.repeated_measures import (
    LMM_BLOCKING_CODES,
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
    LMM_RECOVERY_PATCH,
    LMM_RECIPE_ID,
)
from workbench.contracts.common.envelope import ContractError, PacketEnvelope
from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_ESTIMATOR_VERSION,
    LMM_INFERENCE_METHOD,
    LMM_MISSING_POLICY,
    LMM_MODEL_TYPE,
    LMM_PRIMARY_RESULT_ID,
    LmmDiagnostic,
    LmmModelInput,
    build_lmm_result_identity,
)


def _lmm_input() -> dict[str, object]:
    return {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    }


def _lmm_identity() -> dict[str, object]:
    return {
        "dataset_fingerprint": "dataset-a",
        "analysis_unit": "participant_id",
        "outcome": "score",
        "fixed_effects": [
            "intercept",
            "group",
            "time",
            "group_time_interaction",
        ],
        "random_effects": ["random_intercept", "random_time_slope"],
        "group": "arm",
        "reference_group": "control",
        "fit_method": "reml",
        "missing_policy": LMM_MISSING_POLICY,
        "estimator_version": LMM_ESTIMATOR_VERSION,
        "contract_version": LMM_CONTRACT_VERSION,
    }


def test_packet_envelope_round_trips_and_rejects_unknown_fields() -> None:
    envelope = PacketEnvelope(
        contract="linear_mixed_effects.result",
        contract_version=LMM_CONTRACT_VERSION,
        producer_version="linear_mixed_effects@1.0",
        payload={"result_id": LMM_PRIMARY_RESULT_ID},
    )

    assert PacketEnvelope.from_dict(envelope.to_dict()) == envelope

    with pytest.raises(ContractError, match="unknown envelope field"):
        PacketEnvelope.from_dict({**envelope.to_dict(), "extra": True})


def test_packet_envelope_stores_a_finite_immutable_payload() -> None:
    source_payload: dict[str, object] = {
        "nested": {"estimate": 1.5},
        "labels": ["control", "treated"],
    }
    envelope = PacketEnvelope(
        contract="linear_mixed_effects.result",
        contract_version=LMM_CONTRACT_VERSION,
        producer_version="linear_mixed_effects@1.0",
        payload=source_payload,
    )
    source_payload["nested"] = {"estimate": 99.0}

    assert envelope.to_dict()["payload"] == {
        "nested": {"estimate": 1.5},
        "labels": ["control", "treated"],
    }
    with pytest.raises(TypeError):
        envelope.payload["another"] = "value"  # type: ignore[index]
    with pytest.raises(ContractError, match="finite"):
        PacketEnvelope(
            contract="linear_mixed_effects.result",
            contract_version=LMM_CONTRACT_VERSION,
            producer_version="linear_mixed_effects@1.0",
            payload={"estimate": math.nan},
        )


def test_lmm_input_allows_only_locked_semantics() -> None:
    value = LmmModelInput.from_dict(_lmm_input())

    assert value.fit_method == "reml"
    assert value.to_dict() == _lmm_input()

    with pytest.raises(ContractError, match="fit_method"):
        LmmModelInput.from_dict({**value.to_dict(), "fit_method": "bayes"})


def test_result_identity_changes_when_fit_method_changes() -> None:
    common = _lmm_identity()

    assert build_lmm_result_identity({**common, "fit_method": "reml"}) != (
        build_lmm_result_identity({**common, "fit_method": "ml"})
    )


def test_lmm_contract_constants_lock_the_initial_recipe() -> None:
    assert LMM_MODEL_TYPE == "linear_mixed_effects"
    assert LMM_CONTRACT_VERSION == "1.0"
    assert LMM_ESTIMATOR_VERSION == "statsmodels_mixedlm_v1"
    assert LMM_MISSING_POLICY == "complete_case_v1"
    assert LMM_PRIMARY_RESULT_ID == "group_time_interaction"
    assert LMM_INFERENCE_METHOD == "asymptotic_wald_z_v1"
    assert LMM_RECIPE_ID == "repeated_measures.linear_mixed_effects.v1"
    assert LMM_RECOVERY_ACTION_ID == "lmm.simplify_random_effects_v1"
    assert LMM_RECOVERY_OPERATION_ID == "model.rerun"
    assert LMM_RECOVERY_PATCH == {"model_options": {"random_slope": False}}
    assert LMM_BLOCKING_CODES == frozenset(
        {
            "LMM_SUBJECT_ID_MISSING",
            "LMM_TIME_NOT_NUMERIC",
            "LMM_GROUP_NOT_BINARY",
            "LMM_GROUP_VARIES_WITHIN_SUBJECT",
            "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
            "LMM_CONVERGENCE_FAILED",
        }
    )


def test_blocking_missing_subject_has_no_action_candidate() -> None:
    diagnostic = LmmDiagnostic(
        code="LMM_SUBJECT_ID_MISSING",
        severity="error",
        status="blocked",
        evidence={"column": "participant_id"},
        action_candidate=None,
    )

    assert diagnostic.to_dict()["action_candidate"] is None


def test_random_slope_candidate_is_exact_and_confirmation_bound() -> None:
    diagnostic = LmmDiagnostic(
        code="LMM_RANDOM_SLOPE_NEAR_ZERO",
        severity="warning",
        status="complete",
        evidence={"slope_variance": 0.0},
        action_candidate={
            "action_id": LMM_RECOVERY_ACTION_ID,
            "operation_id": LMM_RECOVERY_OPERATION_ID,
            "patch": LMM_RECOVERY_PATCH,
            "required_confirmation": True,
        },
    )

    assert diagnostic.to_dict()["action_candidate"] == {
        "action_id": "lmm.simplify_random_effects_v1",
        "operation_id": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "required_confirmation": True,
    }
