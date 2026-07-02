from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from .artifacts import register_artifact

# Cap how many columns a grid figure shows, so a wide dataset can't produce a
# gigantic unreadable (and slow) figure. The first N numeric columns are used.
_MAX_GRID_COLUMNS = 12


def create_figures(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    numeric_columns: list[str],
    time_column: str | None,
    model_results: list[tuple[str, dict]] | None = None,
    outcome_column: str | None = None,
) -> dict[str, str]:
    figures_dir = run_root / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, str] = {}

    available_numeric = [column for column in numeric_columns if column in frame.columns]

    # ── EDA distribution plots (v1.6.6 V) ───────────────────────────────
    # These come straight off the numeric columns, so EVERY run — model or
    # not — shows distribution/relationship figures in the Table view. They
    # register as ordinary `figure` artifacts, so the Table's generic figure
    # gallery picks them up automatically (and will pick up any future plot
    # types added here, no frontend change needed).
    _create_eda_figures(
        frame,
        figures_dir,
        run_root,
        available_numeric,
        outcome_column,
        figures,
    )
    if len(available_numeric) >= 2:
        path = figures_dir / "correlation_heatmap.png"
        correlation = frame[available_numeric].corr(numeric_only=True)
        fig, ax = plt.subplots()
        image = ax.imshow(correlation, cmap="coolwarm", vmin=-1, vmax=1)
        ax.set_xticks(range(len(correlation.columns)), correlation.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(correlation.index)), correlation.index)
        fig.colorbar(image, ax=ax)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        record = register_artifact(run_root, "correlation_heatmap", path, "figure", "visualization", [])
        figures["correlation_heatmap"] = record.path

    if time_column is not None and time_column in frame.columns and available_numeric:
        path = figures_dir / "time_trend.png"
        plot_frame = frame.sort_values(time_column)
        fig, ax = plt.subplots()
        for column in available_numeric:
            ax.plot(plot_frame[time_column], plot_frame[column], label=column)
        ax.set_xlabel(time_column)
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        record = register_artifact(run_root, "time_trend", path, "figure", "visualization", [])
        figures["time_trend"] = record.path

    model_result = _first_model_result(model_results or [])
    if model_result is not None:
        residuals = _model_numeric_list(model_result, "residuals_preview", "residuals")
        fitted = _model_numeric_list(model_result, "fitted_values_preview", "fitted_values")
        if residuals and fitted and len(residuals) == len(fitted):
            path = figures_dir / "residuals_fitted.png"
            fig, ax = plt.subplots()
            ax.scatter(fitted, residuals, alpha=0.75)
            ax.axhline(0, color="#8a94a6", linewidth=1)
            ax.set_xlabel("Fitted values")
            ax.set_ylabel("Residuals")
            fig.tight_layout()
            fig.savefig(path)
            plt.close(fig)
            record = register_artifact(
                run_root, "residuals_fitted", path, "figure", "visualization", []
            )
            figures["residuals_fitted"] = record.path

            path = figures_dir / "qq_residuals.png"
            fig, ax = plt.subplots()
            stats.probplot(residuals, dist="norm", plot=ax)
            ax.set_title("Residual Q-Q plot")
            fig.tight_layout()
            fig.savefig(path)
            plt.close(fig)
            record = register_artifact(
                run_root, "qq_residuals", path, "figure", "visualization", []
            )
            figures["qq_residuals"] = record.path

        coefficient_rows = _coefficient_rows(model_result)
        if coefficient_rows:
            labels = [row[0] for row in coefficient_rows]
            estimates = [row[1] for row in coefficient_rows]
            errors = [1.96 * row[2] for row in coefficient_rows]
            path = figures_dir / "coef_plot.png"
            fig, ax = plt.subplots()
            y_positions = range(len(labels))
            ax.errorbar(estimates, y_positions, xerr=errors, fmt="o")
            ax.axvline(0, color="#8a94a6", linewidth=1)
            ax.set_yticks(list(y_positions), labels)
            ax.set_xlabel("Estimate")
            fig.tight_layout()
            fig.savefig(path)
            plt.close(fig)
            record = register_artifact(
                run_root, "coef_plot", path, "figure", "visualization", []
            )
            figures["coef_plot"] = record.path

    return figures


def _grid_dims(n: int) -> tuple[int, int]:
    """Roughly-square (rows, cols) for an n-panel grid."""
    cols = max(1, math.ceil(math.sqrt(n)))
    rows = max(1, math.ceil(n / cols))
    return rows, cols


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _save(fig, path: Path, run_root: Path, artifact_id: str, figures: dict[str, str]) -> None:
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    record = register_artifact(run_root, artifact_id, path, "figure", "visualization", [])
    figures[artifact_id] = record.path


def _create_eda_figures(
    frame: pd.DataFrame,
    figures_dir: Path,
    run_root: Path,
    available_numeric: list[str],
    outcome_column: str | None,
    figures: dict[str, str],
) -> None:
    columns = available_numeric[:_MAX_GRID_COLUMNS]
    if not columns:
        return

    # 1) Histograms — one panel per numeric column.
    rows, cols = _grid_dims(len(columns))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.6), squeeze=False)
    drew = False
    for i, column in enumerate(columns):
        ax = axes[i // cols][i % cols]
        data = _numeric_series(frame, column)
        if len(data) > 0:
            bins = min(30, max(5, int(len(data) ** 0.5)))
            ax.hist(data, bins=bins, color="#4c78a8")
            drew = True
        ax.set_title(column, fontsize=9)
    for j in range(len(columns), rows * cols):
        axes[j // cols][j % cols].axis("off")
    if drew:
        _save(fig, figures_dir / "histograms.png", run_root, "histograms", figures)
    else:
        plt.close(fig)

    # 2) KDE density — one panel per numeric column; constant/degenerate
    #    columns are skipped (gaussian_kde needs positive variance).
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.6), squeeze=False)
    plotted = 0
    for i, column in enumerate(columns):
        ax = axes[i // cols][i % cols]
        ax.set_title(column, fontsize=9)
        data = _numeric_series(frame, column)
        try:
            if len(data) >= 2 and float(data.std()) > 0:
                kde = stats.gaussian_kde(data.to_numpy())
                xs = np.linspace(float(data.min()), float(data.max()), 200)
                ys = kde(xs)
                ax.plot(xs, ys, color="#e45756")
                ax.fill_between(xs, ys, alpha=0.3, color="#e45756")
                plotted += 1
        except Exception:
            # Degenerate column — leave the panel empty rather than fail the run.
            pass
    for j in range(len(columns), rows * cols):
        axes[j // cols][j % cols].axis("off")
    if plotted > 0:
        _save(fig, figures_dir / "kde_plots.png", run_root, "kde_plots", figures)
    else:
        plt.close(fig)

    # 3) Boxplots — all numeric columns side by side in one figure.
    box_pairs = [(c, _numeric_series(frame, c)) for c in columns]
    box_pairs = [(c, s) for c, s in box_pairs if len(s) > 0]
    if box_pairs:
        fig, ax = plt.subplots(figsize=(max(6.0, len(box_pairs) * 0.9), 4.0))
        ax.boxplot([s.to_numpy() for _, s in box_pairs])
        ax.set_xticklabels([c for c, _ in box_pairs], rotation=45, ha="right")
        _save(fig, figures_dir / "boxplots.png", run_root, "boxplots", figures)

    # 4) Scatter — outcome vs each regressor when the outcome is known,
    #    else the first two numeric columns.
    targets: list[tuple[str, str]] = []
    if outcome_column and outcome_column in frame.columns:
        regressors = [c for c in columns if c != outcome_column]
        targets = [(x, outcome_column) for x in regressors]
    elif len(columns) >= 2:
        targets = [(columns[0], columns[1])]
    if targets:
        rows, cols = _grid_dims(len(targets))
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.8), squeeze=False)
        drew = False
        for i, (xcol, ycol) in enumerate(targets):
            ax = axes[i // cols][i % cols]
            aligned = pd.concat(
                [
                    pd.to_numeric(frame[xcol], errors="coerce").rename("x"),
                    pd.to_numeric(frame[ycol], errors="coerce").rename("y"),
                ],
                axis=1,
            ).dropna()
            if len(aligned) > 0:
                ax.scatter(aligned["x"], aligned["y"], alpha=0.6, s=14, color="#54a24b")
                drew = True
            ax.set_xlabel(xcol, fontsize=8)
            ax.set_ylabel(ycol, fontsize=8)
        for j in range(len(targets), rows * cols):
            axes[j // cols][j % cols].axis("off")
        if drew:
            _save(fig, figures_dir / "scatter_plots.png", run_root, "scatter_plots", figures)
        else:
            plt.close(fig)


def _first_model_result(model_results: list[tuple[str, dict]]) -> dict | None:
    for _, result in model_results:
        if isinstance(result, dict):
            return result
    return None


def _numeric_list(values: object) -> list[float]:
    if not isinstance(values, list):
        return []
    numeric: list[float] = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return []
        if pd.isna(parsed):
            return []
        numeric.append(parsed)
    return numeric


def _model_numeric_list(model_result: dict, *keys: str) -> list[float]:
    for key in keys:
        values = _numeric_list(model_result.get(key))
        if values:
            return values
    return []


def _coefficient_rows(model_result: dict) -> list[tuple[str, float, float]]:
    coefficients = model_result.get("coefficients", {})
    if not isinstance(coefficients, dict):
        return []
    rows: list[tuple[str, float, float]] = []
    for term, values in coefficients.items():
        if term == "Intercept" or str(term).startswith("C("):
            continue
        if not isinstance(values, dict):
            continue
        estimate = values.get("estimate")
        std_error = values.get("std_error")
        try:
            parsed_estimate = float(estimate)
            parsed_std_error = float(std_error)
        except (TypeError, ValueError):
            continue
        if pd.isna(parsed_estimate) or pd.isna(parsed_std_error):
            continue
        rows.append((str(term), parsed_estimate, parsed_std_error))
    return rows
