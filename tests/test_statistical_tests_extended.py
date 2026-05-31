import pandas as pd
import pytest

from workbench.statistical_tests import run_statistical_tests


def test_rank_correlations_report_spearman_and_kendall_rows():
    frame = pd.DataFrame({
        "x": [1, 2, 3, 4, 5, 6, 7, 8],
        "y": [2, 1, 4, 3, 6, 5, 8, 7],
    })

    results = run_statistical_tests(frame, analysis_columns=["x", "y"])

    rows = results["rank_correlations"]["results"]
    by_type = {row["test_type"]: row for row in rows}
    assert set(by_type) == {"spearman_correlation", "kendall_correlation"}

    spearman = by_type["spearman_correlation"]
    assert spearman["variables"] == ["x", "y"]
    assert spearman["nobs"] == 8
    assert spearman["statistic"] == pytest.approx(0.9047619)
    assert spearman["effect"]["rho"] == pytest.approx(spearman["statistic"])

    kendall = by_type["kendall_correlation"]
    assert kendall["variables"] == ["x", "y"]
    assert kendall["nobs"] == 8
    assert kendall["statistic"] == pytest.approx(0.7142857)
    assert kendall["effect"]["tau"] == pytest.approx(kendall["statistic"])


def test_nonparametric_reports_mann_whitney_u_and_kruskal_wallis():
    frame = pd.DataFrame({
        "score": [1, 2, 1, 8, 9, 8, 15, 16, 15],
        "binary_group": ["control"] * 3 + ["treated"] * 6,
        "region": ["north"] * 3 + ["south"] * 3 + ["west"] * 3,
    })

    results = run_statistical_tests(
        frame,
        analysis_columns=["score", "binary_group", "region"],
    )

    rows = results["nonparametric"]["results"]
    mann_whitney = next(row for row in rows if row["test_type"] == "mann_whitney_u")
    kruskal = next(row for row in rows if row["test_type"] == "kruskal_wallis")

    assert mann_whitney["outcome"] == "score"
    assert mann_whitney["group"] == "binary_group"
    assert mann_whitney["groups"] == ["control", "treated"]
    assert mann_whitney["p_value"] < 0.05
    assert mann_whitney["effect"]["median_control"] == 1.0
    assert mann_whitney["effect"]["median_treated"] == 12.0

    assert kruskal["outcome"] == "score"
    assert kruskal["group"] == "region"
    assert kruskal["groups"] == ["north", "south", "west"]
    assert kruskal["p_value"] < 0.05
    assert kruskal["effect"]["group_medians"]["north"] == 1.0


def test_nonparametric_skips_groups_with_single_observation():
    frame = pd.DataFrame({
        "score": [1, 10, 11, 20, 21, 30, 31],
        "binary_group": ["control", "treated", "treated", "treated", "treated", "treated", "treated"],
        "region": ["north", "south", "south", "west", "west", "east", "east"],
    })

    results = run_statistical_tests(
        frame,
        analysis_columns=["score", "binary_group", "region"],
    )

    rows = results["nonparametric"]["results"]
    assert all(row["test_type"] != "mann_whitney_u" for row in rows)
    assert all(row["test_type"] != "kruskal_wallis" for row in rows)


def test_fisher_exact_reports_two_by_two_categorical_association():
    frame = pd.DataFrame({
        "treatment": ["control"] * 10 + ["treated"] * 10,
        "converted": ["no"] * 8 + ["yes"] * 2 + ["no"] * 2 + ["yes"] * 8,
    })

    results = run_statistical_tests(frame, analysis_columns=["treatment", "converted"])

    row = results["fisher_exact"]["results"][0]
    assert row["test_type"] == "fisher_exact"
    assert row["variables"] == ["treatment", "converted"]
    assert row["nobs"] == 20
    assert row["statistic"] == pytest.approx(16.0)
    assert row["effect"]["odds_ratio"] == pytest.approx(row["statistic"])
    assert row["effect"]["contingency_table"]["control"]["no"] == 8
    assert row["effect"]["contingency_table"]["treated"]["yes"] == 8
    assert row["p_value"] < 0.05


def test_multiple_testing_correction_metadata_is_added_to_p_value_rows():
    frame = pd.DataFrame({
        "x": [1, 2, 3, 4, 5, 6],
        "y": [2, 4, 6, 8, 10, 12],
        "group": ["a", "a", "a", "b", "b", "b"],
    })

    results = run_statistical_tests(frame, analysis_columns=["x", "y", "group"])

    rows_with_p_values = [
        row
        for family in results.values()
        for row in family["results"]
        if row.get("p_value") is not None
    ]
    assert rows_with_p_values
    for row in rows_with_p_values:
        assert row["correction_method"] == "fdr_bh"
        assert row["p_value_corrected"] is not None
        assert 0 <= row["p_value_corrected"] <= 1
