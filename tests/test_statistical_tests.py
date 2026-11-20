import math
import warnings

import pandas as pd
import pytest

from workbench.statistical_tests import run_named_statistical_test, run_statistical_tests


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


def test_default_correlations_prepare_each_numeric_pair_once(monkeypatch):
    from workbench import statistical_test_pairs

    frame = pd.DataFrame({"x": [1.0, 2.0, None, 3.0, 5.0], "y": [4.0, 1.0, 2.0, 8.0, 3.0]})
    original = statistical_test_pairs._pairwise
    calls = []

    def counted(frame, columns):
        calls.append(tuple(columns))
        return original(frame, columns)

    monkeypatch.setattr(statistical_test_pairs, "_pairwise", counted)
    results = run_statistical_tests(frame, analysis_columns=["x", "y"])
    assert [row["nobs"] for row in results["correlations"]["results"]] == [4]
    assert [row["nobs"] for row in results["rank_correlations"]["results"]] == [4, 4]
    assert calls == [("x", "y")]


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


def test_default_contingency_tests_prepare_each_pair_once(monkeypatch):
    from workbench import statistical_test_pairs

    frame = pd.DataFrame({
        "group": pd.Categorical(["b", "a", "b", "a", "b", "a", "c", None, None, None],
                                categories=["b", "a", "c", "unused"], ordered=True),
        "response": pd.array(["yes", "yes", "no", "no", "yes", "no", None, "no", None, None], dtype="string"),
        "region": ["east", "north", "south", "north", "south", "east", "west", "west", "north", "east"],
        "sparse": [None] * 7 + ["x", "y", "x"],
    }, index=[4, 8, 1, 7, 2, 5, 3, 0, 9, 6])
    pairwise, crosstab = statistical_test_pairs._pairwise, pd.crosstab
    pairwise_calls, table_calls = [], []

    def prepare(data, columns):
        pairwise_calls.append(tuple(columns))
        return pairwise(data, columns)

    def tabulate(left, right):
        table_calls.append((left.name, right.name))
        return crosstab(left, right)

    with monkeypatch.context() as patch:
        patch.setattr(statistical_test_pairs, "_pairwise", prepare)
        patch.setattr(pd, "crosstab", tabulate)
        results = run_statistical_tests(frame, analysis_columns=list(frame.columns))

    chi_square = results["chi_square"]["results"]
    fisher = results["fisher_exact"]["results"]
    assert [row["variables"] for row in chi_square] == [
        ["group", "response"], ["group", "region"], ["response", "region"], ["region", "sparse"],
    ]
    assert [row["variables"] for row in fisher] == [["group", "response"]]
    for family in ("chi_square", "fisher_exact"):
        named = run_named_statistical_test(frame, family=family, analysis_columns=list(frame.columns))
        for automatic_row, named_row in zip(results[family]["results"], named["results"], strict=True):
            assert automatic_row["statistic"].hex() == named_row["statistic"].hex()
            assert automatic_row["p_value"].hex() == named_row["p_value"].hex()
            assert automatic_row["effect"] == named_row["effect"]
    for row in (chi_square[0], fisher[0]):
        assert row["nobs"] == 6
        assert list(row["effect"]["contingency_table"].items()) == [
            ("b", {"no": 1, "yes": 2}), ("a", {"no": 2, "yes": 1}),
        ]
    assert pairwise_calls == [
        ("group", "response"), ("group", "region"), ("group", "sparse"),
        ("response", "region"), ("response", "sparse"), ("region", "sparse"),
    ]
    assert table_calls == [tuple(row["variables"]) for row in chi_square]


def test_contingency_scan_preserves_pandas_duplicate_index_error():
    frame = pd.DataFrame({"group": ["a", "b", "a", "b"], "response": ["x", "y", "y", "x"]},
                         index=[0, 0, 1, 2])

    with pytest.raises(ValueError, match="cannot reindex on an axis with duplicate labels"):
        run_statistical_tests(frame, analysis_columns=list(frame.columns))


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
