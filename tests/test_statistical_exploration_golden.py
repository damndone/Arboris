from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.statistical_exploration import ExplorationSpec, FilterSpec, execute_exploration


ROOT = Path(__file__).parent / "fixtures" / "statistical_exploration"


def test_the_panel_fixture_matches_the_stable_exploration_golden() -> None:
    frame = pd.read_csv(ROOT / "school_panel.csv")
    expected = json.loads((ROOT / "expected.json").read_text(encoding="utf-8"))

    summary = execute_exploration(
        frame,
        ExplorationSpec(
            operation="summarize",
            selected_columns=("bdsnew",),
            filters=(FilterSpec(column="year", operator="eq", value=1998),),
        ),
    )
    detail = execute_exploration(
        frame,
        ExplorationSpec(operation="summarize_detail", selected_columns=("totreg",)),
    )
    corr = execute_exploration(
        frame,
        ExplorationSpec(
            operation="corr",
            selected_columns=("pblack", "pfl", "totreg"),
            options={"missing_policy": "listwise"},
        ),
    )

    assert summary["filtered_row_count"] == expected["summarize_1998"]["row_count"]
    assert summary["variables"]["bdsnew"]["mean"] == pytest.approx(
        expected["summarize_1998"]["bdsnew_mean"]
    )
    assert detail["variables"]["totreg"]["percentiles"] == pytest.approx(
        expected["detail_totreg_percentiles"]
    )
    assert corr["correlation_n"] == expected["corr"]["n"]
    for actual_row, expected_row in zip(corr["matrix"], expected["corr"]["matrix"]):
        assert actual_row == pytest.approx(expected_row)
