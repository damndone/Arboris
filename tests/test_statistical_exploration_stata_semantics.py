from __future__ import annotations

import pandas as pd
import pytest

from workbench.statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    StatisticalExplorationValidationError,
    execute_exploration,
)


def test_detail_uses_the_stata_summarize_detail_percentile_definition() -> None:
    frame = pd.DataFrame({"value": [1, 2, 3, 4]})

    result = execute_exploration(
        frame,
        ExplorationSpec(operation="summarize_detail", selected_columns=("value",)),
    )

    detail = result["variables"]["value"]
    assert detail["quantile_method"] == "stata_summarize_detail_v1"
    assert detail["percentiles"]["p25"] == pytest.approx(1.5)
    assert detail["percentiles"]["p75"] == pytest.approx(3.5)


def test_boolean_filters_require_typed_boolean_values() -> None:
    frame = pd.DataFrame({"flag": pd.Series([True, False, True], dtype="boolean")})

    with pytest.raises(StatisticalExplorationValidationError, match="boolean"):
        execute_exploration(
            frame,
            ExplorationSpec(
                operation="summarize",
                selected_columns=("flag",),
                filters=(FilterSpec(column="flag", operator="eq", value="true"),),
            ),
        )
