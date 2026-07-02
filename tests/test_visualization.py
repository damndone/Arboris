from pathlib import Path

import numpy as np
import pandas as pd

from workbench.projects import create_project, create_run
from workbench.visualization import (
    create_figures,
    _classify_columns,
    _modeled_columns,
)


def _run(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    return create_run(project.root, mode="auto")


# ── role-awareness (v1.6.6 V) ───────────────────────────────────────────


def test_modeled_columns_excludes_ids_and_exposure(tmp_path: Path):
    # Only outcome ∪ regressors are modelled; firm_id / unused columns and the
    # exposure offset are excluded — so IDs never get distribution plots.
    frame = pd.DataFrame(
        {"wage": [1.0], "education": [1.0], "exper": [1.0], "firm_id": [1], "unused": [1]}
    )
    modeled = _modeled_columns(
        frame, "wage", ["education", "exper"], "exper", ["wage", "education", "exper", "firm_id", "unused"]
    )
    assert modeled == ["wage", "education"]  # firm_id/unused dropped, exposure(exper) dropped


def test_classify_columns_splits_continuous_categorical_and_drops_constant(tmp_path: Path):
    frame = pd.DataFrame(
        {
            "cont": list(range(30)),            # many distinct → continuous
            "cat": [0, 1] * 15,                 # 2 distinct → categorical
            "const": [7.0] * 30,                # constant → dropped
        }
    )
    continuous, categorical = _classify_columns(frame, ["cont", "cat", "const"], cat_max_levels=10)
    assert continuous == ["cont"]
    assert categorical == ["cat"]


def test_id_column_is_not_plotted(tmp_path: Path):
    # firm_id present in the frame but not in outcome/regressors → excluded.
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "wage": rng.normal(20, 5, 60),
            "education": rng.normal(12, 3, 60),
            "firm_id": list(range(100, 160)),
        }
    )
    run = _run(tmp_path)
    figures = create_figures(
        frame,
        run.root,
        numeric_columns=["wage", "education", "firm_id"],
        time_column=None,
        outcome_column="wage",
        regressors=["education"],
    )
    # base distribution plots exist (for wage/education only)
    for key in ("histograms", "kde_plots", "boxplots", "scatter_plots"):
        assert key in figures, f"missing {key}: {sorted(figures)}"


def test_categorical_regressor_gets_counts_and_group_boxplots_not_kde(tmp_path: Path):
    rng = np.random.default_rng(2)
    frame = pd.DataFrame(
        {"wage": rng.normal(20, 5, 60), "region": (["A", "B", "C"] * 20)}
    )
    run = _run(tmp_path)
    figures = create_figures(
        frame,
        run.root,
        numeric_columns=["wage"],
        time_column=None,
        outcome_column="wage",
        regressors=["region"],
    )
    assert "category_counts" in figures      # region → bar counts
    assert "group_boxplots" in figures       # wage grouped by region
    # region is categorical → not a scatter target
    assert "scatter_plots" not in figures


def test_kde_skips_constant_column_without_crashing(tmp_path: Path):
    frame = pd.DataFrame({"y": list(range(30)), "const": [5.0] * 30})
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["y", "const"], time_column=None,
        outcome_column="y", regressors=["const"],
    )
    # const is dropped by classification, y is continuous → KDE for y
    assert "kde_plots" in figures
    assert (run.root / figures["kde_plots"]).exists()


# ── model-type-specific (v1.6.6 V) ──────────────────────────────────────


def test_binary_model_emits_pred_prob_by_class(tmp_path: Path):
    frame = pd.DataFrame({"y": [0, 1] * 30, "x": list(range(60))})
    run = _run(tmp_path)
    model_result = {
        "model_id": "logit_1",
        "model_type": "logit",
        "fitted_values": [0.2, 0.8] * 30,  # predicted probabilities
        "coefficients": {"x": {"estimate": 0.5, "std_error": 0.1}},
    }
    figures = create_figures(
        frame, run.root, numeric_columns=["y", "x"], time_column=None,
        outcome_column="y", regressors=["x"], model_type="logit",
        model_results=[("logit_1", model_result)],
    )
    assert "pred_prob_by_class" in figures
    assert (run.root / figures["pred_prob_by_class"]).exists()


def test_auto_model_type_falls_back_to_fitted_type_for_binary(tmp_path: Path):
    # model_type="auto" must not hide the real family — pred_prob should still
    # fire from the fitted model_result's model_type.
    frame = pd.DataFrame({"y": [0, 1] * 30, "x": list(range(60))})
    run = _run(tmp_path)
    model_result = {
        "model_id": "logit_1",
        "model_type": "logit",
        "fitted_values": [0.3, 0.7] * 30,
        "coefficients": {"x": {"estimate": 0.5, "std_error": 0.1}},
    }
    figures = create_figures(
        frame, run.root, numeric_columns=["y", "x"], time_column=None,
        outcome_column="y", regressors=["x"], model_type="auto",
        model_results=[("logit_1", model_result)],
    )
    assert "pred_prob_by_class" in figures


def test_count_model_emits_outcome_counts(tmp_path: Path):
    frame = pd.DataFrame({"events": [0, 1, 2, 3, 1, 0] * 10, "x": list(range(60))})
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["events", "x"], time_column=None,
        outcome_column="events", regressors=["x"], model_type="poisson",
    )
    assert "outcome_counts" in figures


def test_panel_model_emits_entity_trends(tmp_path: Path):
    frame = pd.DataFrame(
        {
            "firm": [1, 1, 1, 2, 2, 2, 3, 3, 3],
            "year": [2000, 2001, 2002] * 3,
            "y": [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 0.5, 1.5, 2.5],
        }
    )
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["y"], time_column="year",
        outcome_column="y", regressors=[], model_type="panel_ols",
        entity_column="firm",
    )
    assert "entity_trends" in figures


def test_iv_model_emits_first_stage(tmp_path: Path):
    rng = np.random.default_rng(3)
    z = rng.normal(0, 1, 60)
    frame = pd.DataFrame({"y": rng.normal(0, 1, 60), "endog": z + rng.normal(0, 0.5, 60), "z": z})
    run = _run(tmp_path)
    figures = create_figures(
        frame, run.root, numeric_columns=["y", "endog", "z"], time_column=None,
        outcome_column="y", regressors=["endog"], model_type="iv",
        iv_endog=["endog"], iv_instruments=["z"],
    )
    assert "iv_first_stage" in figures


def test_did_event_study_plot(tmp_path: Path):
    run = _run(tmp_path)
    event_study = {
        "event_time": [-2, -1, 0, 1, 2],
        "coef": [0.0, 0.0, 0.5, 0.8, 1.0],
        "se": [0.1, 0.1, 0.1, 0.1, 0.1],
    }
    frame = pd.DataFrame({"y": list(range(20)), "treat": [0, 1] * 10})
    figures = create_figures(
        frame, run.root, numeric_columns=["y"], time_column=None,
        outcome_column="y", regressors=["treat"], model_type="did",
        did_event_study=event_study,
    )
    assert "event_study" in figures
    assert (run.root / figures["event_study"]).exists()


def test_create_figures_writes_png_artifacts(tmp_path: Path):
    # Continuous-scale data (>cat_max_levels distinct) so x/y classify as
    # continuous and produce a correlation heatmap.
    frame = pd.DataFrame({"x": list(range(20)), "y": [2 * i for i in range(20)]})
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
