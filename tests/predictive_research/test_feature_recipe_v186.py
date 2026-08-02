from __future__ import annotations

import pandas as pd
import pytest

from workbench.predictive_research.contracts import ContractError, FeatureRecipeV1
from workbench.predictive_research.feature_recipe import apply_feature_recipe


def recipe(operation_id: str, *, inputs: tuple[str, ...], outputs: tuple[str, ...], parameters: dict[str, object]) -> FeatureRecipeV1:
    return FeatureRecipeV1(
        recipe_id=f"{operation_id}-1",
        operation_id=operation_id,
        operation_version=1,
        inputs=inputs,
        outputs=outputs,
        output_types=tuple("float" for _ in outputs),
        parameters=parameters,
        fit_scope="stateless",
        source_artifact="sha256:" + "a" * 64,
    )


def test_typed_recipe_executes_interaction_log_and_ratio_without_code() -> None:
    frame = pd.DataFrame({"x": [2.0, 4.0], "z": [3.0, 5.0], "den": [2.0, 4.0]})

    interaction = apply_feature_recipe(
        frame,
        recipe("interaction", inputs=("x", "z"), outputs=("xz",), parameters={"left": "x", "right": "z"}),
    )
    logged = apply_feature_recipe(
        frame,
        recipe("log", inputs=("x",), outputs=("log_x",), parameters={"input": "x", "base": "e"}),
    )
    ratio = apply_feature_recipe(
        frame,
        recipe("ratio", inputs=("x", "den"), outputs=("x_over_den",), parameters={"numerator": "x", "denominator": "den", "zero_policy": "fail_closed"}),
    )

    assert interaction["xz"].tolist() == [6.0, 20.0]
    assert logged["log_x"].round(6).tolist() == [0.693147, 1.386294]
    assert ratio["x_over_den"].tolist() == [1.0, 1.0]
    assert "xz" not in frame.columns


def test_recipe_recode_is_explicit_and_zero_ratio_fails_closed() -> None:
    frame = pd.DataFrame({"code": ["a", "b"], "x": [1.0, 2.0], "den": [0.0, 2.0]})
    recoded = apply_feature_recipe(
        frame,
        recipe("recode", inputs=("code",), outputs=("code_num",), parameters={"input": "code", "mapping": {"a": 1.0, "b": 2.0}, "default": None}),
    )
    assert recoded["code_num"].tolist() == [1.0, 2.0]

    with pytest.raises(ContractError) as error:
        apply_feature_recipe(
            frame,
            recipe("ratio", inputs=("x", "den"), outputs=("ratio",), parameters={"numerator": "x", "denominator": "den", "zero_policy": "fail_closed"}),
        )
    assert error.value.code == "PREDICTION_FEATURE_RECIPE_ZERO_DENOMINATOR"
