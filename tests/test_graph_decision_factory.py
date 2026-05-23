"""Unit tests for lineage decision factory stage metadata."""
from __future__ import annotations

from collections.abc import Callable

import pytest

from workbench.graph_decision_factory import (
    STAGE_BY_DECISION_ID,
    auto_coerce_to_numeric,
    categorical_auto_dummy,
    handle_missing_values,
    model_type_auto_select,
    ols_default_robust_se,
    variable_silently_dropped,
)
from workbench.graph_model import DecisionPoint, Stage


@pytest.mark.parametrize(
    ("factory", "expected_stage"),
    [
        (
            lambda: model_type_auto_select(
                selected="ols",
                y_unique=35,
                y_dtype="int64",
            ),
            Stage.MODEL,
        ),
        (
            lambda: categorical_auto_dummy(
                variable="region",
                n_unique=4,
                reference_level="north",
            ),
            Stage.TRANSFORM,
        ),
        (lambda: ols_default_robust_se(), Stage.MODEL),
        (
            lambda: auto_coerce_to_numeric(
                variable="rating",
                conversion_rate=0.95,
            ),
            Stage.TRANSFORM,
        ),
        (lambda: handle_missing_values(variables=["y", "x"]), Stage.CLEAN),
        (
            lambda: variable_silently_dropped(
                variable="x_zero",
                drop_reason="zero_variance",
            ),
            Stage.TRANSFORM,
        ),
    ],
)
def test_factory_decision_id_has_expected_stage(
    factory: Callable[[], DecisionPoint],
    expected_stage: Stage,
) -> None:
    decision_point: DecisionPoint = factory()

    assert STAGE_BY_DECISION_ID[decision_point.decision_id] == expected_stage
