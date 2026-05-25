"""Unit tests for lineage decision factory stage metadata."""
from __future__ import annotations

import inspect
import typing
from collections.abc import Callable

import pytest

import workbench.graph_decision_factory as factory_module
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


def test_stage_by_decision_id_covers_every_factory() -> None:
    """REV-2 #2: if a new factory is added without updating STAGE_BY_DECISION_ID,
    the per-factory parametrized test still passes (it only checks known names).
    Catch drift by counting public factories that return DecisionPoint and
    asserting the count matches the table size.
    """
    type_hints_cache: dict[str, dict[str, typing.Any]] = {}

    def returns_decision_point(fn: Callable[..., object]) -> bool:
        if fn.__name__.startswith("_"):
            return False
        try:
            hints = type_hints_cache.setdefault(
                fn.__name__, typing.get_type_hints(fn)
            )
        except Exception:
            return False
        return hints.get("return") is DecisionPoint

    public_factories = [
        fn for _, fn in inspect.getmembers(factory_module, inspect.isfunction)
        if returns_decision_point(fn)
    ]

    assert len(public_factories) == len(STAGE_BY_DECISION_ID), (
        f"STAGE_BY_DECISION_ID has {len(STAGE_BY_DECISION_ID)} entries but "
        f"{len(public_factories)} public DecisionPoint factories exist "
        f"({sorted(fn.__name__ for fn in public_factories)}). "
        f"A new factory was likely added without registering its stage."
    )
