import math
import warnings

import pandas as pd
import pytest

from workbench.statistical_tests import run_statistical_tests


def test_correlation_reports_pearson_p_value():
    frame = pd.DataFrame({
        "y": [1, 2, 3, 4, 5, 6],
        "x": [2, 4, 6, 8, 10, 12],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "x"])

    row = results["correlations"]["results"][0]
    assert row["test_type"] == "pearson_correlation"
    assert row["variables"] == ["y", "x"]
    assert row["nobs"] == 6
    assert row["statistic"] > 0.99
    assert row["p_value"] < 0.001
    assert row["source_id"] == "statistical_tests.correlations.y.x"


def test_constant_correlation_is_typed_without_numeric_warning():
    frame = pd.DataFrame({
        "constant": [1, 1, 1, 1],
        "varying": [2, 3, 4, 5],
    })

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = run_statistical_tests(frame, analysis_columns=["constant", "varying"])

    assert caught == []
    pearson = results["correlations"]["results"][0]
    assert pearson["statistic"] is None
    assert pearson["warnings"] == ["CORRELATION_CONSTANT_INPUT"]


def test_t_test_reports_group_means_and_p_value():
    frame = pd.DataFrame({
        "y": [1.0, 1.2, 1.1, 5.0, 5.2, 5.1],
        "treatment": ["control", "control", "control", "treated", "treated", "treated"],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "treatment"])

    row = results["t_tests"]["results"][0]
    assert row["test_type"] == "welch_t_test"
    assert row["outcome"] == "y"
    assert row["group"] == "treatment"
    assert row["groups"] == ["control", "treated"]
    assert row["effect"]["mean_control"] == 1.1
    assert row["effect"]["mean_treated"] == 5.1
    assert row["effect"]["difference"] == pytest.approx(4.0)
    assert row["p_value"] < 0.01


def test_anova_reports_group_means_and_p_value():
    frame = pd.DataFrame({
        "y": [1, 2, 1, 5, 6, 5, 9, 10, 9],
        "region": ["north", "north", "north", "south", "south", "south", "west", "west", "west"],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "region"])

    row = results["anova"]["results"][0]
    assert row["test_type"] == "one_way_anova"
    assert row["outcome"] == "y"
    assert row["group"] == "region"
    assert row["groups"] == ["north", "south", "west"]
    assert row["effect"]["group_means"]["north"] == 4 / 3
    assert row["p_value"] < 0.01


def test_chi_square_reports_contingency_table_and_p_value():
    frame = pd.DataFrame({
        "treatment": ["control"] * 10 + ["treated"] * 10,
        "region": ["north"] * 8 + ["south"] * 2 + ["north"] * 2 + ["south"] * 8,
    })

    results = run_statistical_tests(frame, analysis_columns=["treatment", "region"])

    row = results["chi_square"]["results"][0]
    assert row["test_type"] == "chi_square"
    assert row["variables"] == ["treatment", "region"]
    assert row["degrees_of_freedom"] == 1
    assert row["effect"]["contingency_table"]["control"]["north"] == 8
    assert row["effect"]["contingency_table"]["treated"]["south"] == 8
    assert row["p_value"] < 0.05


def test_invalid_pairs_are_skipped_without_nan_output():
    frame = pd.DataFrame({
        "y": [1.0, None],
        "x": [2.0, None],
        "group": ["a", "a"],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "x", "group"])

    for family in results.values():
        assert family["schema_version"] == 1
        assert isinstance(family["results"], list)
        for row in family["results"]:
            for value in row.values():
                if isinstance(value, float):
                    assert math.isfinite(value), f"non-finite float found: {value}"


def test_zero_variance_welch_t_test_is_skipped():
    frame = pd.DataFrame({
        "y": [5.0, 5.0, 5.0, 1.0, 2.0, 3.0],
        "treatment": ["control", "control", "control", "treated", "treated", "treated"],
    })

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = run_statistical_tests(frame, analysis_columns=["y", "treatment"])

    assert caught == []
    assert results["t_tests"]["results"][0]["warnings"] == ["T_TEST_ZERO_VARIANCE"]
    bartlett = next(
        row for row in results["evidence"]["results"] if row["test_type"] == "bartlett"
    )
    assert bartlett["warnings"] == ["ZERO_VARIANCE_GROUP"]

    for row in results["t_tests"]["results"]:
        for value in row.values():
            if isinstance(value, float):
                assert math.isfinite(value), f"non-finite float found: {value}"
