from __future__ import annotations

from workbench.agent.workflow_contracts import (
    MODEL_FAMILY_CONTRACTS,
    ModelFamilyContract,
    validate_model_genesis_spec,
    validate_workflow_steps,
)
import pytest


def _ols_spec(**overrides: object) -> dict[str, object]:
    return {
        "model_family": "ols",
        "branches": [{"branch_id": "main", "outcome": "y", "predictors": ["x"]}],
        **overrides,
    }


def test_model_family_contract_declares_weight_and_split_admission() -> None:
    contract = ModelFamilyContract(
        family="test_family_v186",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=lambda spec, branch, predictors, covariance: {},
        expected_artifacts=("model_result",),
        result_shape="coefficient_intervals",
        allows_weights=("frequency",),
        supported_split_kinds=("iid", "grouped"),
    )

    assert contract.allows_weights == ("frequency",)
    assert contract.supported_split_kinds == ("iid", "grouped")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("weight_kind", "frequency", "does not accept weight_kind"),
        ("split_kind", "grouped", "does not accept split_kind"),
    ],
)
def test_model_family_rejects_undeclared_crosscut_capabilities(
    field: str, value: str, message: str
) -> None:
    from workbench.agent.workflow_contracts import OperationValidationError, validate_model_genesis_spec

    with pytest.raises(OperationValidationError, match=message):
        validate_model_genesis_spec(_ols_spec(model_family="logit", **{field: value}))


def test_ols_contract_accepts_declared_weight_and_grouped_split() -> None:
    assert validate_model_genesis_spec(
        _ols_spec(weight_kind="frequency", split_kind="grouped")
    ).family == "ols"


def _v186_model_spec(model_family: str, model_options: dict[str, object]) -> dict[str, object]:
    return {
        "model_family": model_family,
        "model_options": model_options,
        "branches": [{"branch_id": "main", "outcome": "y", "predictors": ["x"]}],
    }


@pytest.mark.parametrize(
    ("model_family", "model_options", "expected_options"),
    [
        ("ordinal_logit", {"optimizer": "bfgs"}, {"optimizer": "bfgs"}),
        ("multinomial_logit", {"base_category": "control"}, {"base_category": "control"}),
        ("survival_cox", {"event_column": "event", "ties": "efron"}, {"event_column": "event", "ties": "efron"}),
        ("quantile_regression", {"quantiles": [0.25, 0.5]}, {"quantiles": [0.25, 0.5]}),
    ],
)
def test_v186_model_family_contracts_admit_only_declared_options_and_build_params(
    model_family: str,
    model_options: dict[str, object],
    expected_options: dict[str, object],
) -> None:
    contract = validate_model_genesis_spec(_v186_model_spec(model_family, model_options))

    assert contract is MODEL_FAMILY_CONTRACTS[model_family]
    model_params = contract.build_model_params(
        _v186_model_spec(model_family, model_options),
        {"outcome": "y"},
        ["x"],
        "robust",
    )
    assert model_params == {
        "model_type": model_family,
        "y": "y",
        "x": ["x"],
        "model_options": expected_options,
    }


@pytest.mark.parametrize(
    ("model_family", "unsupported"),
    [
        ("ordinal_logit", "base_category"),
        ("multinomial_logit", "optimizer"),
        ("survival_cox", "quantiles"),
        ("quantile_regression", "event_column"),
    ],
)
def test_v186_model_family_rejects_options_owned_by_another_family(
    model_family: str, unsupported: str
) -> None:
    from workbench.agent.workflow_contracts import OperationValidationError

    with pytest.raises(OperationValidationError, match="model_options.*does not accept"):
        validate_model_genesis_spec(
            _v186_model_spec(model_family, {unsupported: "not-admitted"})
        )


def test_model_genesis_workflow_schema_admits_declared_model_options() -> None:
    steps = validate_workflow_steps(
        [
            {
                "step_id": "fit-main",
                "operation_id": "model.genesis",
                "spec": _v186_model_spec(
                    "survival_cox", {"event_column": "event"}
                ),
            }
        ]
    )

    assert steps[0]["spec"]["model_options"] == {"event_column": "event"}
