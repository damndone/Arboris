from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import statsmodels.regression.quantile_regression as quantile_regression

from workbench.artifacts import read_json
from workbench.engine.packs.v186_model_families.runtime import (
    _paired_bootstrap_p_value,
    fit_quantile,
)
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _direct_quantile_context(*, bootstrap_reps: int) -> SimpleNamespace:
    frame = pd.DataFrame(
        {
            "y": np.arange(24, dtype=float),
            "x": np.arange(24, dtype=float),
        }
    )
    return SimpleNamespace(
        data=SimpleNamespace(frame=frame),
        artifacts={
            "_normalized_y": "y",
            "_normalized_x": ["x"],
            "_model_options": {
                "quantiles": [0.25, 0.5, 0.75],
                "bootstrap_reps": bootstrap_reps,
                "random_state": 19,
            },
        },
    )


class _FakeQuantileFit:
    def __init__(self, params: list[float], columns: pd.Index[str]) -> None:
        self.params = pd.Series(params, index=columns, dtype=float)
        self.bse = pd.Series([0.1] * len(params), index=columns, dtype=float)
        self.pvalues = pd.Series([0.5] * len(params), index=columns, dtype=float)

    def conf_int(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                0: self.params - 0.1,
                1: self.params + 0.1,
            }
        )


def test_cross_quantile_comparison_is_unavailable_without_joint_uncertainty(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "y": [float(i) + float(i % 4) * 0.3 for i in range(48)],
            "x": [float(i) for i in range(48)],
        }
    )
    source = tmp_path / "quantile.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "quantile-correctness")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="quantile_regression",
        model_options={"quantiles": [0.25, 0.5, 0.75], "bootstrap_reps": 0, "random_state": 7},
    )
    assert outcome["status"] == "completed", outcome

    result = read_json(project.root / "runs" / outcome["run_id"] / "model_results" / "quantile_regression_1.json")
    comparisons = result["cross_quantile_comparisons"]
    assert comparisons
    assert all(row["std_error"] is None for row in comparisons)
    assert all(row["p_value"] is None for row in comparisons)
    comparison_uncertainty = result["bootstrap"]["comparison_uncertainty"]
    assert comparison_uncertainty["method"] == "unavailable"
    assert comparison_uncertainty["status"] == "unavailable"
    assert comparison_uncertainty["reason"] == "BOOTSTRAP_NOT_REQUESTED"


def test_cross_quantile_comparison_uses_paired_bootstrap_uncertainty(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "y": [float(i) + float(i % 4) * 0.3 for i in range(48)],
            "x": [float(i) for i in range(48)],
        }
    )
    source = tmp_path / "quantile-bootstrap.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "quantile-bootstrap-correctness")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="quantile_regression",
        model_options={"quantiles": [0.25, 0.5, 0.75], "bootstrap_reps": 8, "random_state": 7},
    )
    assert outcome["status"] == "completed", outcome

    result = read_json(project.root / "runs" / outcome["run_id"] / "model_results" / "quantile_regression_1.json")
    comparisons = result["cross_quantile_comparisons"]
    comparison_uncertainty = result["bootstrap"].get("comparison_uncertainty", {})
    assert comparison_uncertainty.get("method") == "paired_bootstrap"
    assert comparison_uncertainty.get("status") == "available"
    assert comparison_uncertainty.get("p_value_status") == "approximate"
    assert comparison_uncertainty.get("p_value_contract") == "null_centered_bootstrap_sign_tail"
    assert comparison_uncertainty.get("p_value_method") == (
        "paired_bootstrap_null_centered_two_sided_sign_tail"
    )
    assert all(row["std_error"] is not None for row in comparisons)
    assert all(row["p_value"] is not None for row in comparisons)


def test_paired_bootstrap_p_value_uses_the_observed_difference_for_null_centering() -> None:
    assert _paired_bootstrap_p_value(
        [0.2, 0.4, 0.5, 0.1], observed_difference=0.2
    ) == pytest.approx(0.8)


def test_quantile_output_is_deterministic_for_a_fixed_random_state() -> None:
    _, first, _ = fit_quantile(_direct_quantile_context(bootstrap_reps=4), None)
    _, second, _ = fit_quantile(_direct_quantile_context(bootstrap_reps=4), None)

    assert first == second


def test_cross_quantile_comparison_is_degraded_when_paired_bootstrap_is_insufficient(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "y": [float(i) + float(i % 4) * 0.3 for i in range(48)],
            "x": [float(i) for i in range(48)],
        }
    )
    source = tmp_path / "quantile-insufficient.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "quantile-insufficient-correctness")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="quantile_regression",
        model_options={"quantiles": [0.25, 0.5, 0.75], "bootstrap_reps": 1, "random_state": 7},
    )
    assert outcome["status"] == "completed", outcome

    result = read_json(project.root / "runs" / outcome["run_id"] / "model_results" / "quantile_regression_1.json")
    comparison_uncertainty = result["bootstrap"]["comparison_uncertainty"]
    assert comparison_uncertainty["method"] == "paired_bootstrap"
    assert comparison_uncertainty["status"] == "degraded"
    assert comparison_uncertainty["reason"] == "INSUFFICIENT_PAIRED_BOOTSTRAP_FITS"
    assert all(row["std_error"] is None for row in result["cross_quantile_comparisons"])
    assert all(row["p_value"] is None for row in result["cross_quantile_comparisons"])


def test_bootstrap_reuses_identical_indices_for_all_quantiles_and_counts_pairs(monkeypatch) -> None:
    fit_calls: list[tuple[float, tuple[float, ...]]] = []

    class SpyQuantReg:
        def __init__(self, endog, exog) -> None:
            self.endog = np.asarray(endog, dtype=float)
            self.exog = exog

        def fit(self, *, q: float) -> _FakeQuantileFit:
            fit_calls.append((float(q), tuple(self.endog.tolist())))
            return _FakeQuantileFit([1.0, float(q)], self.exog.columns)

    monkeypatch.setattr(quantile_regression, "QuantReg", SpyQuantReg)
    _, result, _ = fit_quantile(_direct_quantile_context(bootstrap_reps=4), None)

    bootstrap_calls = fit_calls[3:]
    assert len(bootstrap_calls) == 4 * 3
    for start in range(0, len(bootstrap_calls), 3):
        assert [bootstrap_calls[start + offset][0] for offset in range(3)] == [0.25, 0.5, 0.75]
        resampled_indices = [bootstrap_calls[start + offset][1] for offset in range(3)]
        assert resampled_indices[0] == resampled_indices[1] == resampled_indices[2]
    assert result["bootstrap"]["comparison_uncertainty"]["paired_successful_repetitions"] == 4


def test_nonfinite_bootstrap_params_are_not_counted_and_intervals_are_none(monkeypatch) -> None:
    fit_calls: list[tuple[float, tuple[float, ...]]] = []

    class NonFiniteQuantReg:
        def __init__(self, endog, exog) -> None:
            self.endog = np.asarray(endog, dtype=float)
            self.exog = exog

        def fit(self, *, q: float) -> _FakeQuantileFit:
            fit_number = len(fit_calls)
            fit_calls.append((float(q), tuple(self.endog.tolist())))
            params = [np.nan, float(q)] if fit_number == 4 else [1.0, float(q)]
            return _FakeQuantileFit(params, self.exog.columns)

    monkeypatch.setattr(quantile_regression, "QuantReg", NonFiniteQuantReg)
    _, result, _ = fit_quantile(_direct_quantile_context(bootstrap_reps=1), None)

    bootstrap = result["bootstrap"]
    assert bootstrap["successful_repetitions"]["0.5"] == 0
    assert bootstrap["intervals"]["0.5"] == {"const": [None, None], "x": [None, None]}
    assert bootstrap["comparison_uncertainty"]["paired_successful_repetitions"] == 0
    assert bootstrap["comparison_uncertainty"]["reason"] == "NONFINITE_PAIRED_BOOTSTRAP_FIT"


def test_overflowed_paired_difference_degrades_without_numeric_uncertainty(monkeypatch) -> None:
    fit_calls = 0

    class OverflowQuantReg:
        def __init__(self, endog, exog) -> None:
            self.endog = np.asarray(endog, dtype=float)
            self.exog = exog

        def fit(self, *, q: float) -> _FakeQuantileFit:
            nonlocal fit_calls
            fit_calls += 1
            coefficient = float(q) if fit_calls <= 3 else {
                0.25: -1e308,
                0.5: 1e308,
                0.75: 1e308,
            }[float(q)]
            return _FakeQuantileFit([0.0, coefficient], self.exog.columns)

    monkeypatch.setattr(quantile_regression, "QuantReg", OverflowQuantReg)
    _, result, _ = fit_quantile(_direct_quantile_context(bootstrap_reps=2), None)

    uncertainty = result["bootstrap"]["comparison_uncertainty"]
    assert uncertainty["status"] == "degraded"
    assert uncertainty["reason"] == "NONFINITE_PAIRED_BOOTSTRAP_DIFFERENCE"
    assert all(row["std_error"] is None for row in result["cross_quantile_comparisons"])
    assert all(row["p_value"] is None for row in result["cross_quantile_comparisons"])
