from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats

from .artifacts import register_artifact


def create_figures(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    numeric_columns: list[str],
    time_column: str | None,
    model_results: list[tuple[str, dict]] | None = None,
) -> dict[str, str]:
    figures_dir = run_root / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, str] = {}

    available_numeric = [column for column in numeric_columns if column in frame.columns]
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
        residuals = _numeric_list(model_result.get("residuals"))
        fitted = _numeric_list(model_result.get("fitted_values"))
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
