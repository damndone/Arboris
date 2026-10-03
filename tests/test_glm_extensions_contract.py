from __future__ import annotations

from dataclasses import replace
import json

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.glm_extensions import (
    GLM_EXTENSION_CONTRACT,
    GLM_EXTENSION_CONTRACT_VERSION,
    GLM_EXTENSION_OPERATION_IDS,
    GLM_EXTENSION_REASON_CODES,
    GLMExtensionRequest,
    GLMExtensionResultEnvelope,
)


def _request_dict(operation_id: str = "glm.zero_inflated_poisson") -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "predictor_columns": ["x"],
        "zero_predictor_columns": None,
        "positive_predictor_columns": None,
        "precision_predictor_columns": None,
        "matrix_semantics": "rows_are_observations_columns_are_predictors_v1",
        "response_semantics": "nonnegative_integer_count_v1",
        "zero_process_semantics": "mixture_structural_zero_v1",
        "count_link": "log",
        "zero_link": "logit",
        "positive_count_link": "not_applicable",
        "mean_link": "not_applicable",
        "precision_link": "not_applicable",
        "intercept": True,
        "missing_policy": "reject_nonfinite_v1",
        "offset_policy": "none_v1",
        "optimizer": "bfgs",
        "maxiter": 300,
        "tolerance": 1e-8,
        "max_abs_linear_predictor": 30.0,
    }


def test_operation_set_is_closed_and_does_not_redeclare_negative_binomial():
    assert GLM_EXTENSION_OPERATION_IDS == {
        "glm.zero_inflated_poisson",
        "glm.zero_inflated_negative_binomial",
        "glm.hurdle_poisson",
        "glm.hurdle_negative_binomial",
        "glm.beta",
    }
    assert "glm.negative_binomial" not in GLM_EXTENSION_OPERATION_IDS
    assert "negative_binomial" not in GLM_EXTENSION_OPERATION_IDS


def test_request_is_typed_closed_and_round_trips_without_defaults():
    value = _request_dict()
    request = GLMExtensionRequest.from_dict(value)

    assert request.to_dict() == value
    assert GLMExtensionRequest.from_dict(request.to_dict()) == request

    with pytest.raises(ContractError, match="unknown glm extension request field"):
        GLMExtensionRequest.from_dict({**value, "auto_select": True})

    with pytest.raises(ContractError, match="missing_policy"):
        GLMExtensionRequest.from_dict({**value, "missing_policy": "drop_any"})

    with pytest.raises(ContractError, match="zero_process_semantics"):
        GLMExtensionRequest.from_dict(
            {**value, "zero_process_semantics": "auto_by_zero_rate"}
        )

    with pytest.raises(ContractError, match="intercept"):
        GLMExtensionRequest.from_dict({**value, "intercept": "auto"})


def test_request_rejects_inconsistent_beta_and_hurdle_policies():
    beta = _request_dict("glm.beta")
    beta.update(
        {
            "response_semantics": "strict_unit_interval_v1",
            "zero_process_semantics": "not_applicable_v1",
            "count_link": "not_applicable",
            "zero_link": "not_applicable",
            "positive_count_link": "not_applicable",
            "mean_link": "logit",
            "precision_link": "log",
        }
    )
    assert GLMExtensionRequest.from_dict(beta).response_semantics == "strict_unit_interval_v1"

    hurdle = _request_dict("glm.hurdle_poisson")
    hurdle.update(
        {
            "response_semantics": "nonnegative_integer_count_v1",
            "zero_process_semantics": "separate_zero_gate_truncated_count_v1",
            "count_link": "not_applicable",
            "zero_link": "logit",
            "positive_count_link": "log",
        }
    )
    assert GLMExtensionRequest.from_dict(hurdle).positive_count_link == "log"

    with pytest.raises(ContractError, match="precision_predictor_columns"):
        GLMExtensionRequest.from_dict(
            {**beta, "precision_predictor_columns": ["precision_x"]}
        )


def _completed_result() -> dict[str, object]:
    scope = {
        "estimand": "count-process coefficients and zero probability",
        "input_semantics": "rows are observations and columns are predictors",
        "assumptions": ["finite numeric matrix"],
        "limitations": ["no automatic model selection"],
        "not_claimed": ["not a causal effect"],
        "unsupported_extensions": ["formula strings"],
    }
    return {
        "status": "completed",
        "reason_code": "ANALYSIS_COMPLETED",
        "model_family": "zero_inflated_poisson",
        "n_observations": 20,
        "predictor_columns": ["x"],
        "policy": _request_dict(),
        "fit": {"converged": True, "optimizer": "bfgs"},
        "coefficient_estimands": {"count": {}, "zero": {}},
        "mean_estimands": {"conditional_count_mean": {}},
        "zero_probability_estimands": {"observed_zero_probability": {}},
        "scope": scope,
        "diagnostics": {"covariance_finite": True},
    }


def test_result_envelope_is_json_safe_and_keeps_estimands_separate():
    envelope = GLMExtensionResultEnvelope(
        operation_id="glm.zero_inflated_poisson",
        result=_completed_result(),
    )
    value = envelope.to_dict()

    assert value["contract"] == GLM_EXTENSION_CONTRACT
    assert value["contract_version"] == GLM_EXTENSION_CONTRACT_VERSION
    assert set(value["result"]) >= {
        "coefficient_estimands",
        "mean_estimands",
        "zero_probability_estimands",
        "scope",
    }
    assert GLMExtensionResultEnvelope.from_dict(value).to_dict() == value
    json.dumps(value)


@pytest.mark.parametrize("status", ["rejected", "failed"])
def test_result_envelope_accepts_stable_non_success_status_and_reason(status: str):
    result = _completed_result()
    result["status"] = status
    result["reason_code"] = (
        "GLM_EXTENSION_REJECTED" if status == "rejected" else "GLM_EXTENSION_FAILED"
    )

    envelope = GLMExtensionResultEnvelope(
        operation_id="glm.zero_inflated_poisson", result=result
    )
    assert envelope.to_dict()["result"]["reason_code"] in GLM_EXTENSION_REASON_CODES


def test_completed_reason_cannot_be_used_for_rejected_result():
    result = _completed_result()
    result["status"] = "rejected"
    with pytest.raises(ContractError, match="reason_code must match status"):
        GLMExtensionResultEnvelope(
            operation_id="glm.zero_inflated_poisson", result=result
        )
