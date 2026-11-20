"""v1.8.9 step 7 (D2) — categorical variables in descriptive statistics."""

import numpy as np
import pandas as pd
import pytest

from workbench.statistical_exploration import (
    ExplorationSpec,
    StatisticalExplorationValidationError,
    execute_exploration,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wage": [10.0, 12.0, 14.0, np.nan, 20.0],
            "region": ["north", "south", "north", None, "west"],
            "union": [1, 0, 1, 1, 0],
        }
    )


def test_summarize_skips_text_columns_and_names_them() -> None:
    result = execute_exploration(_frame(), ExplorationSpec(operation="summarize", selected_columns=("wage", "region", "union")))
    assert set(result["variables"]) == {"wage", "union"}
    assert result["variables"]["wage"]["obs"] == 4
    assert result["non_numeric_columns"] == ["region"]


def test_summarize_with_only_text_columns_points_to_tabulate() -> None:
    with pytest.raises(StatisticalExplorationValidationError, match="use tabulate"):
        execute_exploration(_frame(), ExplorationSpec(operation="summarize", selected_columns=("region",)))


def test_tabulate_counts_values_and_missing() -> None:
    result = execute_exploration(_frame(), ExplorationSpec(operation="tabulate", selected_columns=("region", "union")))
    assert result["variables"]["region"] == {"obs": 5, "valid": 4, "missing": 1, "distinct": 3, "truncated": False}
    region = [row for row in result["rows"] if row["variable"] == "region"]
    assert region[0] == {"variable": "region", "value": "north", "count": 2, "percent": 40.0, "valid_percent": 50.0}
    assert region[-1]["value"] is None and region[-1]["count"] == 1
    union = {row["value"]: row["count"] for row in result["rows"] if row["variable"] == "union"}
    assert union == {1: 3, 0: 2}
    assert sum(row["percent"] for row in region) == pytest.approx(100.0)


def test_summarize_all_columns_by_default_no_longer_fails_on_text() -> None:
    """The live baseline D2 case: 'describe every variable' on mixed data."""

    result = execute_exploration(_frame(), ExplorationSpec(operation="summarize", selected_columns=()))
    assert "region" in result["non_numeric_columns"]


def test_explicit_frequency_counts_match_expanded_data_without_expansion():
    compressed = pd.DataFrame({'category': ['a', 'b', None, 'c'], 'count': [8, 2, 3, 0]})
    spec = ExplorationSpec(operation='tabulate', selected_columns=('category',),
                           options={'frequency_weight': 'count'})
    weighted = execute_exploration(compressed, spec)
    expanded = compressed.loc[compressed.index.repeat(compressed['count'])]
    unweighted = execute_exploration(expanded, ExplorationSpec(operation='tabulate', selected_columns=('category',)))
    assert weighted['rows'] == unweighted['rows']
    assert weighted['variables'] == unweighted['variables']
    assert weighted['frequency_weight'] == 'count'
    assert weighted['source_row_count'] == 4 and weighted['weighted_count'] == 13
    assert execute_exploration(compressed, ExplorationSpec(operation='tabulate', selected_columns=('category',)))['rows'][0]['count'] == 1


@pytest.mark.parametrize('counts', [[1, -1], [1, .5], [1, None], [0, 0], [1, float('inf')], [2**53, 1]])
def test_invalid_frequencies_are_errors_not_row_counts(counts):
    frame = pd.DataFrame({'value': ['a', 'b'], 'count': counts})
    with pytest.raises(StatisticalExplorationValidationError, match='frequency'):
        execute_exploration(frame, ExplorationSpec(operation='tabulate', selected_columns=('value',),
                                                  options={'frequency_weight': 'count'}))


def test_frequency_request_cannot_be_silently_ignored_by_another_operation():
    with pytest.raises(StatisticalExplorationValidationError, match='frequency'):
        ExplorationSpec(operation='corr', selected_columns=('x', 'y'), options={'frequency_weight': 'count'})


def test_frequency_filters_and_duplicate_index_do_not_change_the_counting_unit():
    from workbench.statistical_exploration import FilterSpec
    frame = pd.DataFrame({'bin': ['b', 'a', 'b'], 'count': [4, 5, 1]}, index=[0, 0, 1])
    spec = ExplorationSpec(operation='tabulate', selected_columns=('bin',),
                           filters=(FilterSpec('bin', 'eq', 'b'),), options={'frequency_weight': 'count'})
    result = execute_exploration(frame, spec)
    assert result['weighted_count'] == 5 and result['filtered_row_count'] == 2
    assert result['rows'][0]['count'] == 5 and result['rows'][0]['percent'] == 100
