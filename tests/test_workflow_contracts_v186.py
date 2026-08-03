from __future__ import annotations

from workbench.agent.workflow_contracts import ModelFamilyContract, validate_model_genesis_spec
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
