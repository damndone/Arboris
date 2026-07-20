"""Data-only, fail-closed trajectory context for linear mixed-effects results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from workbench.canonical import sha256_canonical

from .input import PreparedLmmInput


def _display_groups(prepared: PreparedLmmInput) -> list[tuple[object, str]]:
    """Return exactly the two displayed groups in stable label order."""

    return sorted(
        (
            (prepared.reference_group_value, prepared.reference_group),
            (prepared.comparison_group_value, prepared.comparison_group),
        ),
        key=lambda item: item[1],
    )


def _unbalanced_support_evidence(
    *,
    prepared: PreparedLmmInput,
) -> Mapping[str, object] | None:
    """Describe unequal observed-time support without altering any observations."""

    group_column = prepared.input.group
    time_column = prepared.input.time
    supports: list[tuple[str, list[float]]] = []
    for group_value, label in _display_groups(prepared):
        support = sorted(
            float(value)
            for value in prepared.frame.loc[
                prepared.frame[group_column] == group_value, time_column
            ].unique()
        )
        supports.append((label, support))
    first_support = supports[0][1]
    if all(support == first_support for _, support in supports[1:]):
        return None
    nonshared = sorted(
        set(first_support).symmetric_difference(set(supports[1][1]))
    )
    return {
        "reason": "unbalanced_observed_time_support",
        "group_support": [
            {"label": label, "observed_time_sha256": sha256_canonical(support)}
            for label, support in supports
        ],
        "first_nonshared_time": float(nonshared[0]),
    }


def build_lmm_trajectory_context(
    *,
    prepared: PreparedLmmInput,
    fitted: Any,
    outcome: str,
) -> tuple[dict[str, object] | None, Mapping[str, object] | None]:
    """Return the canonical trajectory or exact evidence explaining its absence."""

    unbalanced_evidence = _unbalanced_support_evidence(prepared=prepared)
    if unbalanced_evidence is not None:
        return None, unbalanced_evidence

    group_column = prepared.input.group
    time_column = prepared.input.time
    trajectory = prepared.frame[[group_column, time_column, outcome]].copy()
    trajectory["_fitted_mean"] = np.asarray(
        fitted.predict(prepared.frame), dtype=float
    )
    grouped = (
        trajectory.groupby([group_column, time_column], sort=True)
        .agg(
            observed_mean=(outcome, "mean"),
            fitted_mean=("_fitted_mean", "mean"),
        )
        .reset_index()
    )
    times = sorted(float(value) for value in grouped[time_column].unique())
    groups: list[dict[str, object]] = []
    for group_value, label in _display_groups(prepared):
        points = grouped[grouped[group_column] == group_value].sort_values(time_column)
        groups.append(
            {
                "label": label,
                "observed_mean": [float(value) for value in points["observed_mean"]],
                "fitted_mean": [float(value) for value in points["fitted_mean"]],
            }
        )
    return {
        "chart_type": "lmm_group_trajectory",
        "time": times,
        "groups": groups,
    }, None
