from pathlib import Path

import pandas as pd

from workbench.projects import create_project, create_run
from workbench.visualization import create_figures


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
