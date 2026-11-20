"""Deterministic execution of the small v1.8.6 FeatureRecipe registry."""

from __future__ import annotations

import math
import numbers

import numpy as np
import pandas as pd

from .contracts import ContractError, FeatureRecipeV1


def _require_column(frame: pd.DataFrame, column: str) -> None:
    if column not in frame.columns:
        raise ContractError("PREDICTION_FEATURE_RECIPE_INPUT_MISSING", column)


def _in_mapping(value: object, mapping: dict) -> bool:
    try:
        return value in mapping
    except TypeError:
        return False


def _json_keys(value: object) -> list[str]:
    """The keys a JSON object can use for one numeric value: 12 is "12", 12.0 is "12" or "12.0"."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real):
        return []
    if isinstance(value, numbers.Integral):
        return [str(int(value))]
    number = float(value)
    if not math.isfinite(number):
        return []
    return [str(int(number)), repr(number)] if number.is_integer() else [repr(number)]


def _string_key_lookup(values: pd.Series, mapping: dict) -> dict:
    """Map numeric values that a JSON mapping could only name by their string form.

    QRData 355 (6af0a0da round): {"12": 1, ...} on the int64 column educ matched nothing,
    the default filled every row, and OLS on the constant column reported 0.00.
    """
    lookup = {}
    for value in pd.unique(values.dropna()):
        if _in_mapping(value, mapping):
            continue
        keys = [key for key in _json_keys(value) if key in mapping]
        if len({repr(mapping[key]) for key in keys}) > 1:
            raise ContractError(
                "PREDICTION_FEATURE_RECIPE_PARAMETERS_INVALID",
                f"recode mapping names one value twice with different results: {', '.join(keys)}")
        if keys:
            lookup[value] = mapping[keys[0]]
    return lookup


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
        extra = _string_key_lookup(result[source], mapping)
        recoded = result[source].map({**extra, **mapping} if extra else mapping)
        present = result[source].dropna()
        if len(present) and not any(_in_mapping(value, mapping) or value in extra for value in pd.unique(present)):
            sample = ", ".join(repr(_json_keys(value)[0] if _json_keys(value) else str(value)) for value in pd.unique(present)[:5])
            raise ContractError(
                "PREDICTION_FEATURE_RECIPE_MAPPING_UNMATCHED",
                f"recode mapping matched no value of {source}; its keys are values of {source}, e.g. {sample}")
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
