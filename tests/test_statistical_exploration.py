from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    StatisticalExplorationValidationError,
    execute_exploration,
    exploration_fingerprint,
)


FIXTURE = Path(__file__).parent / "fixtures" / "statistical_exploration" / "class3.csv"


def _frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURE)


def test_filter_spec_accepts_typed_scalar_and_list_values() -> None:
    assert FilterSpec(column="year", operator="eq", value=1998).to_dict() == {
        "column": "year",
        "operator": "eq",
        "value": 1998,
    }
    assert FilterSpec(column="year", operator="in", value=[1998, 2002]).to_dict() == {
        "column": "year",
        "operator": "in",
        "value": [1998, 2002],
    }


def test_filter_spec_rejects_unknown_operator_and_empty_column() -> None:
    with pytest.raises(StatisticalExplorationValidationError, match="operator"):
        FilterSpec(column="year", operator="between", value=[1998, 2002])

    with pytest.raises(StatisticalExplorationValidationError, match="column"):
        FilterSpec(column="", operator="eq", value=1998)


def test_exploration_spec_preserves_filter_order_and_validates_selected_columns() -> None:
    spec = ExplorationSpec(
        operation="summarize",
        selected_columns=("bdsnew", "pfl"),
        filters=(
            FilterSpec(column="year", operator="eq", value=1998),
            FilterSpec(column="middle", operator="eq", value=1),
        ),
    )

    assert spec.to_dict() == {
        "schema_version": "statistical-exploration.v1",
        "operation": "summarize",
        "selected_columns": ["bdsnew", "pfl"],
        "filters": [
            {"column": "year", "operator": "eq", "value": 1998},
            {"column": "middle", "operator": "eq", "value": 1},
        ],
        "options": {},
        "derived_definitions": [],
    }


def test_exploration_fingerprint_is_stable_for_mapping_insertion_order() -> None:
    first = ExplorationSpec(
        operation="corr",
        selected_columns=("pblack", "pfl"),
        options={"missing_policy": "listwise", "confidence_level": 0.95},
    )
    second = ExplorationSpec(
        operation="corr",
        selected_columns=("pblack", "pfl"),
        options={"confidence_level": 0.95, "missing_policy": "listwise"},
    )

    assert exploration_fingerprint("sha256:source", first) == exploration_fingerprint(
        "sha256:source", second
    )


def test_exploration_spec_rejects_unknown_operation() -> None:
    with pytest.raises(StatisticalExplorationValidationError, match="operation"):
        ExplorationSpec(operation="regress", selected_columns=("pfl",))


def test_summarize_applies_multiple_filters_as_an_and_predicate() -> None:
    result = execute_exploration(
        _frame(),
        ExplorationSpec(
            operation="summarize",
            selected_columns=("bdsnew", "pfl"),
            filters=(
                FilterSpec(column="year", operator="eq", value=1998),
                FilterSpec(column="middle", operator="eq", value=0),
            ),
        ),
    )

    assert result["filtered_row_count"] == 2
    assert result["missing_policy"] == "variablewise"
    assert result["variables"]["bdsnew"] == {
        "obs": 2,
        "mean": 316045.0,
        "std_dev": pytest.approx(430060.0 / 2**0.5),
        "min": 101015.0,
        "max": 531075.0,
    }


def test_summarize_grouped_by_year_preserves_requested_year_order() -> None:
    result = execute_exploration(
        _frame(),
        ExplorationSpec(
            operation="summarize",
            selected_columns=("bdsnew",),
            options={"group_by": "year", "group_values": [2016, 1998, 2006]},
        ),
    )

    assert [group["value"] for group in result["groups"]] == [2016, 1998, 2006]
    assert [group["filtered_row_count"] for group in result["groups"]] == [1, 3, 2]
    assert result["groups"][1]["variables"]["bdsnew"]["obs"] == 3


def test_summarize_detail_returns_stata_style_percentiles() -> None:
    result = execute_exploration(
        _frame(),
        ExplorationSpec(operation="summarize_detail", selected_columns=("totreg",)),
    )

    detail = result["variables"]["totreg"]
    assert detail["obs"] == 12
    assert detail["percentiles"]["p25"] == pytest.approx(142.5)
    assert detail["percentiles"]["p50"] == pytest.approx(275.0)
    assert detail["percentiles"]["p75"] == pytest.approx(675.0)


def test_misstable_reports_missing_and_nonmissing_counts() -> None:
    result = execute_exploration(
        _frame(),
        ExplorationSpec(operation="misstable", selected_columns=("pfl", "pblack")),
    )

    assert result["filtered_row_count"] == 12
    assert result["variables"] == {
        "pfl": {"missing": 1, "nonmissing": 11},
        "pblack": {"missing": 1, "nonmissing": 11},
    }


def test_corr_uses_pooled_listwise_complete_rows_and_reports_n() -> None:
    result = execute_exploration(
        _frame(),
        ExplorationSpec(
            operation="corr",
            selected_columns=("pblack", "pfl", "totreg"),
            options={"missing_policy": "listwise"},
        ),
    )

    assert result["missing_policy"] == "listwise"
    assert result["correlation_n"] == 10
    assert result["variables"] == ["pblack", "pfl", "totreg"]
    assert result["matrix"][0][0] == pytest.approx(1.0)
    assert result["matrix"][0][1] == pytest.approx(
        _frame().dropna(subset=["pblack", "pfl", "totreg"])[["pblack", "pfl"]]
        .corr()
        .iloc[0, 1]
    )
