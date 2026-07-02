from pathlib import Path

import numpy as np
import pandas as pd

from workbench.projects import create_project, create_run
from workbench.visualization import create_figures


def _run(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    return create_run(project.root, mode="auto")


def test_create_figures_writes_eda_plots(tmp_path: Path):
    # v1.6.6 V: histogram / KDE / boxplot are emitted from numeric columns
    # even without a model, so any run shows distribution plots in the Table.
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {"wage": rng.normal(20, 5, 60), "education": rng.normal(12, 3, 60)}
    )
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["wage", "education"], time_column=None
    )
    for key in ("histograms", "kde_plots", "boxplots"):
        assert key in figures, f"missing {key}: {sorted(figures)}"
        assert (run.root / figures[key]).exists()


def test_create_figures_scatter_uses_outcome_vs_regressors(tmp_path: Path):
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {"wage": rng.normal(20, 5, 40), "education": rng.normal(12, 3, 40)}
    )
    run = _run(tmp_path)
    figures = create_figures(
        frame,
        run.root,
        numeric_columns=["wage", "education"],
        time_column=None,
        outcome_column="wage",
    )
    assert "scatter_plots" in figures
    assert (run.root / figures["scatter_plots"]).exists()


def test_create_figures_kde_skips_constant_column_without_crashing(tmp_path: Path):
    # A zero-variance column would blow up gaussian_kde; it must be skipped
    # gracefully while the varying column still produces a KDE.
    frame = pd.DataFrame({"const": [5.0] * 30, "varies": list(range(30))})
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["const", "varies"], time_column=None
    )
    assert "kde_plots" in figures
    assert (run.root / figures["kde_plots"]).exists()
    # histogram + boxplot still cover all columns
    assert "histograms" in figures


def test_create_figures_single_column_has_no_scatter(tmp_path: Path):
    frame = pd.DataFrame({"only": list(range(20))})
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["only"], time_column=None
    )
    assert "histograms" in figures
    assert "scatter_plots" not in figures  # needs >= 2 numeric columns


def test_create_figures_writes_png_artifacts(tmp_path: Path):
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2, 4, 6, 8]})
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    figures = create_figures(frame, run.root, numeric_columns=["x", "y"], time_column=None)
    assert "correlation_heatmap" in figures
    assert (run.root / figures["correlation_heatmap"]).exists()


def test_create_figures_writes_model_diagnostics(tmp_path: Path):
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2.1, 3.9, 6.2, 7.8]})
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    model_result = {
        "model_id": "ols_1",
        "fitted_values": [2.0, 4.0, 6.0, 8.0],
        "residuals": [0.1, -0.1, 0.2, -0.2],
        "coefficients": {
            "Intercept": {"estimate": 0.0, "std_error": 0.1},
            "x": {"estimate": 2.0, "std_error": 0.2},
        },
    }

    figures = create_figures(
        frame,
        run.root,
        numeric_columns=["x", "y"],
        time_column=None,
        model_results=[("ols_1", model_result)],
    )

    assert {"residuals_fitted", "qq_residuals", "coef_plot"}.issubset(figures)
    assert (run.root / figures["residuals_fitted"]).exists()
    assert (run.root / figures["qq_residuals"]).exists()
    assert (run.root / figures["coef_plot"]).exists()


def test_create_figures_uses_model_preview_diagnostics(tmp_path: Path):
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2.1, 3.9, 6.2, 7.8]})
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    model_result = {
        "model_id": "ols_1",
        "fitted_values_preview": [2.0, 4.0, 6.0, 8.0],
        "residuals_preview": [0.1, -0.1, 0.2, -0.2],
        "coefficients": {
            "x": {"estimate": 2.0, "std_error": 0.2},
        },
    }

    figures = create_figures(
        frame,
        run.root,
        numeric_columns=["x", "y"],
        time_column=None,
        model_results=[("ols_1", model_result)],
    )

    assert {"residuals_fitted", "qq_residuals", "coef_plot"}.issubset(figures)
    assert (run.root / figures["residuals_fitted"]).exists()
    assert (run.root / figures["qq_residuals"]).exists()
