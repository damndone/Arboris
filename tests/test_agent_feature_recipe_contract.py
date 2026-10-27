"""Recipe-specific public schemas and admission preserve the requested method."""

from copy import deepcopy

from jsonschema import Draft202012Validator
import pandas as pd
import pytest

from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from workbench.agent.workflow_contract_parts.validation import _validate_step_spec
from workbench.contracts.common.errors import OperationValidationError
from workbench.predictive_research.contracts import FeatureRecipeV1
from workbench.predictive_research.feature_recipe import apply_feature_recipe


RECIPES = [
    ("interaction", ["a", "b"], {"left": "a", "right": "b"}, "left, right", "left, right"),
    ("log", ["a"], {"input": "a"}, "base, input", "input"),
    ("ratio", ["a", "b"], {"numerator": "a", "denominator": "b", "zero_policy": "fail_closed"},
     "denominator, numerator, zero_policy", "denominator, numerator, zero_policy"),
    ("recode", ["a"], {"input": "a", "mapping": {"1": 2}}, "default, input, mapping", "input, mapping"),
    ("derived_variable", ["a", "b"], {"operator": "subtract"}, "operator", "operator"),
]


def _spec(operation, inputs, parameters):
    return {"recipe_id": "requested_recipe", "recipe_operation_id": operation,
            "inputs": inputs, "output": "result", "parameters": parameters}


@pytest.mark.parametrize("operation,inputs,parameters,allowed,required", RECIPES)
def test_recipe_specific_public_schema_and_admission_accept_legal_parameters(
    operation, inputs, parameters, allowed, required,
):
    spec = _spec(operation, inputs, parameters)
    original = deepcopy(spec)
    schema = WORKFLOW_STEP_SPEC_CONTRACTS["data.feature_recipe"].to_schema()
    Draft202012Validator(schema).validate(spec)
    _validate_step_spec("data.feature_recipe", spec)
    assert spec == original


@pytest.mark.parametrize("operation,inputs,parameters,allowed,required", RECIPES)
def test_public_schema_binds_parameters_to_selected_recipe(
    operation, inputs, parameters, allowed, required,
):
    # Every added field belongs to another legal recipe, but not this one.
    other_field = "left" if operation != "interaction" else "operator"
    other_value = "a" if other_field == "left" else "subtract"
    spec = _spec(operation, inputs, {**parameters, other_field: other_value})
    original = deepcopy(spec)
    schema = WORKFLOW_STEP_SPEC_CONTRACTS["data.feature_recipe"].to_schema()
    assert not Draft202012Validator(schema).is_valid(spec)
    with pytest.raises(OperationValidationError):
        _validate_step_spec("data.feature_recipe", spec)
    assert spec == original


@pytest.mark.parametrize("operation,inputs,parameters,allowed,required", RECIPES)
def test_missing_parameters_feedback_lists_current_recipe_contract_once(
    operation, inputs, parameters, allowed, required,
):
    spec = _spec(operation, inputs, {})
    original = deepcopy(spec)
    with pytest.raises(OperationValidationError) as failure:
        _validate_step_spec("data.feature_recipe", spec)
    message = str(failure.value)
    assert operation in message
    assert f"Allowed parameters: {allowed}." in message
    assert f"Required parameters: {required}." in message
    assert spec == original
    # A single explicit correction can satisfy the published contract.
    corrected = {**spec, "parameters": deepcopy(parameters)}
    _validate_step_spec("data.feature_recipe", corrected)


def test_subtraction_admission_does_not_rewrite_or_execute_the_rejected_request(monkeypatch):
    import workbench.predictive_research.feature_recipe as producer

    def must_not_execute(*args, **kwargs):
        pytest.fail("rejected recipe must not reach the numerical producer")

    monkeypatch.setattr(producer, "apply_feature_recipe", must_not_execute)
    spec = _spec("derived_variable", ["b", "a"],
                 {"left": "b", "right": "a", "operator": "subtract"})
    original = deepcopy(spec)
    with pytest.raises(OperationValidationError) as failure:
        _validate_step_spec("data.feature_recipe", spec)
    assert "unsupported" in str(failure.value)
    assert "Allowed parameters: operator." in str(failure.value)
    assert "Required parameters: operator." in str(failure.value)
    assert spec == original


def test_legal_subtraction_keeps_input_order_and_native_result():
    spec = _spec("derived_variable", ["b", "a"], {"operator": "subtract"})
    original = deepcopy(spec)
    _validate_step_spec("data.feature_recipe", spec)
    frame = pd.DataFrame({"a": [10.0, 2.0], "b": [2.0, 9.0]})
    before = frame.copy()
    recipe = FeatureRecipeV1(
        recipe_id=spec["recipe_id"], operation_id=spec["recipe_operation_id"],
        operation_version=1, inputs=tuple(spec["inputs"]), outputs=(spec["output"],),
        output_types=("numeric",), parameters=spec["parameters"], fit_scope="stateless",
        source_artifact="test_source", lineage_parent="stage:source",
    )
    result = apply_feature_recipe(frame, recipe)
    assert result["result"].tolist() == [-8.0, 7.0]
    pd.testing.assert_frame_equal(frame, before)
    assert spec == original
