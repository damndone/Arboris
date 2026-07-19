"""Data-only trajectory context for linear mixed-effects results."""

from __future__ import annotations

from typing import Any

import numpy as np

from .input import PreparedLmmInput


def build_lmm_trajectory_context(
    *,
    prepared: PreparedLmmInput,
    fitted: Any,
    outcome: str,
) -> dict[str, object]:
    """Return ordered observed and fixed-effect fitted group trajectories."""

    group_column = prepared.input.group
    time_column = prepared.input.time
    trajectory = prepared.frame[[group_column, time_column, outcome]].copy()
    trajectory["_fitted_marginal_mean"] = np.asarray(
        fitted.predict(prepared.frame), dtype=float
    )
    grouped = (
        trajectory.groupby([group_column, time_column], sort=True)
        .agg(
            observed_mean=(outcome, "mean"),
            fitted_marginal_mean=("_fitted_marginal_mean", "mean"),
        )
        .reset_index()
    )
    times = sorted(float(value) for value in grouped[time_column].unique())
    series: list[dict[str, object]] = []
    for group_value, group_label in (
        (prepared.reference_group_value, prepared.reference_group),
        (prepared.comparison_group_value, prepared.comparison_group),
    ):
        points = grouped[grouped[group_column] == group_value].sort_values(time_column)
        series.append(
            {
                "group": group_label,
                "time": [float(value) for value in points[time_column]],
                "observed_mean": [float(value) for value in points["observed_mean"]],
                "fitted_marginal_mean": [
                    float(value) for value in points["fitted_marginal_mean"]
                ],
            }
        )
    return {
        "chart_type": "lmm_group_trajectory",
        "time": times,
        "series": series,
    }
