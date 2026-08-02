"""Deterministic execution of the small v1.8.6 FeatureRecipe registry."""

from __future__ import annotations

import math

import pandas as pd

from .contracts import ContractError, FeatureRecipeV1


def _require_column(frame: pd.DataFrame, column: str) -> None:
    if column not in frame.columns:
        raise ContractError("PREDICTION_FEATURE_RECIPE_INPUT_MISSING", column)


def apply_feature_recipe(frame: pd.DataFrame, recipe: FeatureRecipeV1) -> pd.DataFrame:
    recipe.validate()
    result = frame.copy()
    for column in recipe.inputs:
        _require_column(result, column)
    for column in recipe.outputs:
        if column in result.columns:
            raise ContractError("PREDICTION_FEATURE_RECIPE_OUTPUT_COLLISION", column)
    if len(recipe.outputs) != 1:
        raise ContractError("PREDICTION_FEATURE_RECIPE_SHAPE_INVALID", "phase-one operations produce one output")
    output = recipe.outputs[0]
    parameters = dict(recipe.parameters)

    if recipe.operation_id == "interaction":
        left = str(parameters.get("left", ""))
        right = str(parameters.get("right", ""))
        _require_column(result, left)
        _require_column(result, right)
        result[output] = pd.to_numeric(result[left], errors="coerce") * pd.to_numeric(result[right], errors="coerce")
    elif recipe.operation_id == "log":
        source = str(parameters.get("input", ""))
        _require_column(result, source)
        values = pd.to_numeric(result[source], errors="coerce")
        if values.isna().any() or (values <= 0).any():
            raise ContractError("PREDICTION_FEATURE_RECIPE_DOMAIN_INVALID", "log requires finite positive input")
        base = parameters.get("base", "e")
        if base != "e":
            try:
                base_value = float(base)
            except (TypeError, ValueError) as error:
                raise ContractError("PREDICTION_FEATURE_RECIPE_PARAMETERS_INVALID", "log base must be e or numeric") from error
            if not math.isfinite(base_value) or base_value <= 0 or base_value == 1:
                raise ContractError("PREDICTION_FEATURE_RECIPE_PARAMETERS_INVALID", "log base must be positive and not one")
            result[output] = values.map(lambda value: math.log(float(value), base_value))
        else:
            result[output] = values.map(lambda value: math.log(float(value)))
    elif recipe.operation_id == "ratio":
        numerator = str(parameters.get("numerator", ""))
        denominator = str(parameters.get("denominator", ""))
        _require_column(result, numerator)
        _require_column(result, denominator)
        denominator_values = pd.to_numeric(result[denominator], errors="coerce")
        if parameters.get("zero_policy") != "fail_closed":
            raise ContractError("PREDICTION_FEATURE_RECIPE_PARAMETERS_INVALID", "ratio must declare zero_policy")
        if denominator_values.isna().any() or (denominator_values == 0).any():
            raise ContractError("PREDICTION_FEATURE_RECIPE_ZERO_DENOMINATOR", "ratio denominator contains zero or missing values")
        result[output] = pd.to_numeric(result[numerator], errors="coerce") / denominator_values
    elif recipe.operation_id == "recode":
        source = str(parameters.get("input", ""))
        _require_column(result, source)
        mapping = parameters.get("mapping")
        if not isinstance(mapping, dict):
            raise ContractError("PREDICTION_FEATURE_RECIPE_PARAMETERS_INVALID", "recode mapping must be an object")
        recoded = result[source].map(mapping)
        if recoded.isna().any():
            if "default" not in parameters or parameters["default"] is None:
                raise ContractError("PREDICTION_FEATURE_RECIPE_UNMAPPED_VALUE", "recode has an unmapped value")
            recoded = recoded.fillna(parameters["default"])
        result[output] = recoded
    elif recipe.operation_id == "derived_variable":
        operator = parameters.get("operator")
        if len(recipe.inputs) != 2 or operator not in {"add", "subtract", "multiply"}:
            raise ContractError("PREDICTION_FEATURE_RECIPE_PARAMETERS_INVALID", "derived_variable requires two inputs and a registered operator")
        left = pd.to_numeric(result[recipe.inputs[0]], errors="coerce")
        right = pd.to_numeric(result[recipe.inputs[1]], errors="coerce")
        if operator == "add":
            result[output] = left + right
        elif operator == "subtract":
            result[output] = left - right
        else:
            result[output] = left * right
    else:
        raise ContractError("PREDICTION_FEATURE_RECIPE_UNKNOWN_OPERATION", recipe.operation_id)
    return result
