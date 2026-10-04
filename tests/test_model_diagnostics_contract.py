from __future__ import annotations

import json

import pytest

from workbench.contracts.common.envelope import ContractError


def _design() -> tuple[tuple[float, ...], ...]:
    return (
        (1.0, -2.0, 0.5),
        (1.0, -1.0, 1.2),
        (1.0, 0.0, -0.4),
        (1.0, 1.0, 0.7),
        (1.0, 2.0, -1.1),
        (1.0, 3.0, 1.5),
    )


def _metadata() -> dict[str, object]:
    return {
        "model_type": "ols",
        "parameter_count": 3,
        "residual_df": 3,
        "residual_variance": 1.0,
        "covariance": "unadjusted",
        "parameter_names": ["const", "x1", "x2"],
    }


def _input(**overrides: object):
    from workbench.contracts.model.model_diagnostics import ModelDiagnosticsInput

    value: dict[str, object] = {
        "operation_id": "diagnostics.breusch_pagan",
        "response": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "design": _design(),
        "design_columns": ["const", "x1", "x2"],
        "residuals": [0.2, -0.1, 0.3, -0.4, 0.1, -0.2],
        "fitted_values": [0.8, 2.1, 2.7, 4.4, 4.9, 6.2],
        "intercept": True,
        "intercept_column": "const",
        "model_metadata": _metadata(),
        "time_order": None,
        "time_values": None,
        "lag": None,
        "reset_powers": None,
        "max_output_rows": None,
    }
    value.update(overrides)
    return ModelDiagnosticsInput.from_dict(value)


def test_model_diagnostics_contract_declares_closed_operations_and_round_trips_input():
    from workbench.contracts.model.model_diagnostics import (
        MODEL_DIAGNOSTICS_CONTRACT,
        MODEL_DIAGNOSTICS_CONTRACT_VERSION,
        MODEL_DIAGNOSTICS_OPERATION_IDS,
        ModelDiagnosticsInput,
        ModelDiagnosticsResultEnvelope,
    )

    assert MODEL_DIAGNOSTICS_OPERATION_IDS == frozenset(
        {
            "diagnostics.vif",
            "diagnostics.breusch_pagan",
            "diagnostics.white",
            "diagnostics.breusch_godfrey",
            "diagnostics.reset",
            "diagnostics.influence",
        }
    )
    request = _input()
    assert request.operation_id == "diagnostics.breusch_pagan"
    assert ModelDiagnosticsInput.from_dict(request.to_dict()) == request

    envelope = ModelDiagnosticsResultEnvelope(
        operation_id="diagnostics.vif",
        status="completed",
        reason_code="DIAGNOSTICS_COMPLETED",
        n_observations=6,
        design_columns=("const", "x1", "x2"),
        result={
            "intercept": {"included": True, "column": "const", "excluded_from_vif": True},
            "vif": {"x1": 1.1, "x2": 1.2},
            "condition": {
                "rank": 3,
                "columns": 3,
                "full_rank": True,
                "condition_number": 4.0,
            },
            "scope": {
                "estimand": "design-matrix collinearity evidence",
                "input_semantics": "finite numeric OLS design matrix with explicit intercept metadata",
                "assumptions": ["the supplied design matrix is the intended estimation design"],
                "limitations": ["VIF is not a model-validity decision"],
                "not_claimed": ["a p-value or VIF does not classify the model as valid or invalid"],
                "unsupported_extensions": ["survey and clustered covariance semantics are not included"],
            },
        },
    ).to_dict()
    assert envelope["contract"] == MODEL_DIAGNOSTICS_CONTRACT
    assert envelope["contract_version"] == MODEL_DIAGNOSTICS_CONTRACT_VERSION == "1.0"
    assert json.loads(json.dumps(envelope, allow_nan=False)) == envelope
    assert ModelDiagnosticsResultEnvelope.from_dict(envelope).to_dict() == envelope


@pytest.mark.parametrize(
    "mutation",
    [
        {"operation_id": "diagnostics.unknown"},
        {"design_columns": ["const", "x1"]},
        {"design": [[1.0, 2.0], [1.0]]},
        {"design": [[1.0, 2.0, float("nan")]] * 6},
        {"design_columns": ["const", "x1", "x1"]},
        {"intercept": True, "intercept_column": None},
        {"intercept": False, "intercept_column": "const"},
        {"model_metadata": {**_metadata(), "parameter_count": 2}},
        {"model_metadata": {**_metadata(), "residual_df": 0}},
        {"model_metadata": {**_metadata(), "covariance": "clustered"}},
    ],
)
def test_input_contract_rejects_ambiguous_or_mismatched_shapes(mutation: dict[str, object]):
    with pytest.raises(ContractError):
        _input(**mutation)


@pytest.mark.parametrize(
    ("operation_id", "overrides"),
    [
        ("diagnostics.breusch_godfrey", {"time_order": None, "lag": None}),
        ("diagnostics.reset", {"reset_powers": None}),
        ("diagnostics.influence", {"fitted_values": None}),
    ],
)
def test_operation_specific_inputs_are_explicit(operation_id: str, overrides: dict[str, object]):
    with pytest.raises(ContractError):
        _input(operation_id=operation_id, **overrides)


def test_completed_result_scope_cannot_claim_model_validity_or_hide_failure():
    from workbench.contracts.model.model_diagnostics import ModelDiagnosticsResultEnvelope

    base = {
        "contract": "model_diagnostics.result",
        "contract_version": "1.0",
        "operation_id": "diagnostics.vif",
        "status": "completed",
        "reason_code": "DIAGNOSTICS_COMPLETED",
        "n_observations": 6,
        "design_columns": ["const", "x1", "x2"],
        "result": {
            "intercept": {"included": True, "column": "const", "excluded_from_vif": True},
            "vif": {"x1": 1.1, "x2": 1.2},
            "condition": {"rank": 3, "columns": 3, "full_rank": True, "condition_number": 4.0},
            "scope": {
                "estimand": "design-matrix collinearity evidence",
                "input_semantics": "finite numeric OLS design matrix with explicit intercept metadata",
                "assumptions": ["the supplied design matrix is the intended estimation design"],
                "limitations": ["the result is diagnostic evidence only"],
                "not_claimed": ["a diagnostic does not classify the model as valid or invalid"],
                "unsupported_extensions": ["survey covariance is not included"],
            },
        },
    }
    forged = {**base, "result": {**base["result"], "model_valid": True}}
    with pytest.raises(ContractError):
        ModelDiagnosticsResultEnvelope.from_dict(forged)

    failed = {
        **base,
        "status": "failed",
        "reason_code": "DIAGNOSTICS_FAILED",
        "result": {"error_code": "DIAGNOSTICS_NUMERIC_FAILURE", "message": "failed"},
    }
    assert ModelDiagnosticsResultEnvelope.from_dict(failed).to_dict() == failed
