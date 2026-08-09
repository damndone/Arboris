from __future__ import annotations

import json
import math
from math import sqrt
import shutil
import subprocess

import pandas as pd
import pytest
from scipy import stats


def _assert_no_missingness_mechanism_claim(value):
    """Missingness evidence must not silently classify MCAR/MAR/MNAR."""
    if isinstance(value, dict):
        for key, nested in value.items():
            assert key.lower() not in {"mcar", "mar", "mnar"}
            _assert_no_missingness_mechanism_claim(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_no_missingness_mechanism_claim(nested)
    elif isinstance(value, str):
        assert value.lower() not in {"mcar", "mar", "mnar"}


def _model_result(
    estimate: float = 1.0,
    *,
    std_error: float = 0.2,
    coefficient: str = "Intercept",
    **coefficient_fields,
):
    fields = {"estimate": estimate, "std_error": std_error}
    fields.update(coefficient_fields)
    return {"coefficients": {coefficient: fields}}


def test_missingness_diagnostic_reports_exact_rates_rows_and_sorted_joint_patterns():
    try:
        from workbench.engine.packs.missing_data.diagnostics import diagnose_missingness
    except ModuleNotFoundError:
        pytest.fail(
            "Wished-for API is not implemented: "
            "workbench.engine.packs.missing_data.diagnostics.diagnose_missingness"
        )
    except ImportError:
        pytest.fail(
            "Wished-for API is not importable: "
            "workbench.engine.packs.missing_data.diagnostics.diagnose_missingness"
        )

    frame = pd.DataFrame(
        {
            "b": [1.0, None, None, 4.0],
            "a": [None, 2.0, None, 4.0],
            "c": [0.0, 0.0, 3.0, None],
        }
    )

    profile = diagnose_missingness(frame)

    assert profile["n_rows"] == 4
    assert profile["columns"] == [
        {"column": "a", "missing_count": 2, "missing_rate": pytest.approx(0.5)},
        {"column": "b", "missing_count": 2, "missing_rate": pytest.approx(0.5)},
        {"column": "c", "missing_count": 1, "missing_rate": pytest.approx(0.25)},
    ]
    assert profile["joint_patterns"] == [
        {"pattern": "001", "count": 1},
        {"pattern": "010", "count": 1},
        {"pattern": "100", "count": 1},
        {"pattern": "110", "count": 1},
    ]
    assert profile["inference_claims"] == []
    _assert_no_missingness_mechanism_claim(profile)
    assert json.dumps(profile, sort_keys=True)


def test_missingness_diagnostic_is_invariant_to_input_column_order():
    from workbench.engine.packs.missing_data.diagnostics import diagnose_missingness

    frame = pd.DataFrame(
        {
            "b": [1.0, None, None, 4.0],
            "a": [None, 2.0, None, 4.0],
            "c": [0.0, 0.0, 3.0, None],
        }
    )

    assert diagnose_missingness(frame) == diagnose_missingness(frame[["c", "a", "b"]])


def test_rubin_pool_exposes_variance_components_for_fixed_model_results():
    model_results = [
        {"coefficients": {"Intercept": {"estimate": 1.0, "std_error": 0.2}}},
        {"coefficients": {"Intercept": {"estimate": 1.8, "std_error": 0.2}}},
    ]

    try:
        from workbench.engine.packs.missing_data.rubin import rubin_pool
    except ModuleNotFoundError:
        pytest.fail(
            "Wished-for API is not implemented: "
            "workbench.engine.packs.missing_data.rubin.rubin_pool"
        )
    except ImportError:
        pytest.fail(
            "Wished-for API is not importable: "
            "workbench.engine.packs.missing_data.rubin.rubin_pool"
        )

    pooled = rubin_pool(model_results)
    intercept = pooled["coefficients"]["Intercept"]

    # Wished-for Rubin output: Qbar/Ubar/B/T plus a two-sided 95% Rubin-t CI.
    # With r=((1+1/m)*B/U), Rubin's df is (m-1)*(1+1/r)^2 = 169/144 here.
    expected_df = (2 - 1) * (1 + 0.04 / ((1 + 1 / 2) * 0.32)) ** 2
    expected_standard_error = sqrt(0.52)
    critical_value = stats.t.ppf(0.975, expected_df)
    expected_interval = [
        1.4 - critical_value * expected_standard_error,
        1.4 + critical_value * expected_standard_error,
    ]

    assert intercept["estimate"] == pytest.approx(1.4)
    assert intercept["within_variance"] == pytest.approx(0.04)
    assert intercept["between_variance"] == pytest.approx(0.32)
    assert intercept["total_variance"] == pytest.approx(0.52)
    assert intercept["standard_error"] == pytest.approx(expected_standard_error)
    assert intercept["degrees_of_freedom"] == pytest.approx(169 / 144)
    assert intercept["confidence_level"] == pytest.approx(0.95)
    assert intercept["confidence_interval_method"] == "rubin_t"
    assert intercept["confidence_interval"] == pytest.approx(expected_interval)
    expected_t_statistic = 1.4 / expected_standard_error
    expected_p_value = 2 * stats.t.sf(abs(expected_t_statistic), expected_df)
    assert intercept["fraction_missing_information"] == pytest.approx(12 / 13)
    assert intercept["t_statistic"] == pytest.approx(expected_t_statistic)
    assert intercept["p_value"] == pytest.approx(expected_p_value)


@pytest.mark.parametrize(
    ("model_results", "reason"),
    [
        (
            [_model_result(coefficient="Intercept"), _model_result(coefficient="x")],
            "coefficient",
        ),
        (
            [_model_result(estimate=math.nan), _model_result()],
            "finite",
        ),
        (
            [
                _model_result(variance=math.nan),
                _model_result(variance=0.04),
            ],
            "finite",
        ),
        (
            [
                _model_result(variance=-0.01),
                _model_result(variance=0.04),
            ],
            "variance",
        ),
    ],
)
def test_rubin_pool_rejects_misaligned_or_invalid_estimates_and_variances(
    model_results, reason
):
    from workbench.engine.packs.missing_data.rubin import rubin_pool

    with pytest.raises(ValueError, match=reason):
        rubin_pool(model_results)


def test_rubin_pool_rejects_single_imputation_for_pooled_inference():
    from workbench.engine.packs.missing_data.rubin import rubin_pool

    with pytest.raises(ValueError, match=r"m|imputation|at least 2"):
        rubin_pool([_model_result()])


def test_rubin_pool_rejects_zero_or_nonfinite_rubin_degrees_of_freedom():
    from workbench.engine.packs.missing_data.rubin import rubin_pool

    same_estimate = [_model_result(estimate=1.0), _model_result(estimate=1.0)]

    with pytest.raises(ValueError, match=r"degrees|df|finite"):
        rubin_pool(same_estimate)

    invalid_df = [
        _model_result(estimate=1.0, degrees_of_freedom=0.0),
        _model_result(estimate=1.8, degrees_of_freedom=10.0),
    ]
    with pytest.raises(ValueError, match=r"degrees|df|finite"):
        rubin_pool(invalid_df)


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is not installed")
def test_rubin_pool_matches_base_r_t_oracle():
    from workbench.engine.packs.missing_data.rubin import rubin_pool

    pooled = rubin_pool(
        [
            {"coefficients": {"Intercept": {"estimate": 1.0, "std_error": 0.2}}},
            {"coefficients": {"Intercept": {"estimate": 1.8, "std_error": 0.2}}},
        ]
    )
    r_script = (
        "m <- 2; q <- c(1, 1.8); u <- c(0.04, 0.04); "
        "qbar <- mean(q); ubar <- mean(u); b <- sum((q-qbar)^2)/(m-1); "
        "tvar <- ubar + (1+1/m)*b; r <- (1+1/m)*b/ubar; "
        "df <- (m-1)*(1+1/r)^2; se <- sqrt(tvar); "
        "crit <- qt(0.975, df); p <- 2*pt(-abs(qbar/se), df); "
        "cat(sprintf('%.17g %.17g %.17g %.17g %.17g %.17g', "
        "qbar, ubar, b, tvar, df, p))"
    )
    completed = subprocess.run(
        ["Rscript", "--vanilla", "-e", r_script],
        check=True,
        capture_output=True,
        text=True,
    )
    qbar, ubar, between, total, degrees, p_value = map(
        float, completed.stdout.split()
    )
    intercept = pooled["coefficients"]["Intercept"]
    assert intercept["estimate"] == pytest.approx(qbar)
    assert intercept["within_variance"] == pytest.approx(ubar)
    assert intercept["between_variance"] == pytest.approx(between)
    assert intercept["total_variance"] == pytest.approx(total)
    assert intercept["degrees_of_freedom"] == pytest.approx(degrees)
    assert intercept["p_value"] == pytest.approx(p_value)
