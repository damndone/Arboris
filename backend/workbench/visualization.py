from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from .artifacts import register_artifact


def create_figures(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    numeric_columns: list[str],
    time_column: str | None,
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

    return figures
