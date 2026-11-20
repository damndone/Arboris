"""Two independent proportions: rate difference, risk ratio and odds ratio (Stata prtest and csi).

Rows are either one observation each (a binary outcome column) or already counted (an events
column with a trials or non-events column; rows are summed within each group). The comparison
is first group minus (or over) second group: by default the two group values in sorted order,
as Stata prtest ..., by() reports group 0 minus group 1.

Formulas, all at the declared confidence level with the normal quantile:
- rate difference: Wald interval with the unpooled standard error (prtest);
- z test of equal proportions: pooled standard error (prtest), two-sided;
- risk ratio: interval on the log scale, SE^2 = 1/x1 - 1/n1 + 1/x2 - 1/n2 (csi);
- odds ratio: Woolf interval, SE^2 = sum of reciprocal cell counts (csi, woolf).
A ratio with a zero cell is not estimable on the log scale and is reported as unavailable.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .statistical_test_values import StatisticalTestContractError, _safe_float

ROLE_PARAMETERS = ("group_column", "outcome_column", "events_column", "trials_column", "non_events_column")


def proportion_columns(options: dict[str, Any]) -> list[str]:
    return [str(options[name]) for name in ROLE_PARAMETERS if options.get(name)]


def check_roles(options: dict[str, Any]) -> None:
    outcome, events = options.get("outcome_column"), options.get("events_column")
    if not options.get("group_column") and not events:
        raise StatisticalTestContractError(
            "proportions requires group_column, except for counted rows (events_column) where each of exactly "
            "two rows is one group")
    trials, non_events = options.get("trials_column"), options.get("non_events_column")
    if bool(outcome) == bool(events) or (events and bool(trials) == bool(non_events)) or (outcome and (trials or non_events)):
        raise StatisticalTestContractError(
            "proportions takes either outcome_column (one row per observation) or events_column with exactly one of "
            "trials_column or non_events_column (rows already counted)"
        )


def _counts(frame: pd.DataFrame, options: dict[str, Any]) -> tuple[dict[Any, tuple[float, float]], int]:
    check_roles(options)
    group = options.get("group_column")
    outcome = options.get("outcome_column")
    events = options.get("events_column")
    totals = options.get("trials_column") or options.get("non_events_column")
    used = proportion_columns(options)
    rows = frame.loc[:, used].dropna()
    dropped = int(len(frame) - len(rows))
    if outcome:
        values = rows[outcome].unique().tolist()
        shown = sorted(map(str, values))[:6]
        event_value = options.get("event_value")
        if event_value is None:
            if not set(values) <= {0, 1}:
                raise StatisticalTestContractError(
                    f"proportions outcome_column {outcome} has values {shown}; set event_value to the value that "
                    "counts as an event"
                )
            event_value = 1
        if len(values) > 2 or not any(value == event_value or str(value) == str(event_value) for value in values):
            raise StatisticalTestContractError(
                f"proportions outcome_column {outcome} must be binary with event_value {event_value!r} among its "
                f"values; it has {shown}"
            )
        hits = (rows[outcome] == event_value) | (rows[outcome].astype(str) == str(event_value))
        grouped = pd.DataFrame({"group": rows[group], "x": hits.astype(float)}).groupby("group", sort=True)["x"]
        return {key: (float(value.sum()), float(len(value))) for key, value in grouped}, dropped
    for name in (events, totals):
        column = pd.to_numeric(rows[name], errors="coerce")
        if column.isna().any() or (column < 0).any() or not np.all(np.isclose(column, np.round(column))):
            raise StatisticalTestContractError(f"proportions {name} must hold non-negative whole counts")
    if not group:
        # A counted 2x2 table often has one row per arm and no label column (QRData 070); the model
        # recoded a label column by hand and gave both rows the same one. The rows are the groups here.
        if len(rows) != 2:
            raise StatisticalTestContractError(
                f"proportions without group_column needs exactly two counted rows, one per group; it has {len(rows)}")
        rows = rows.assign(**{"__row__": [f"row {index + 1}" for index in range(len(rows))]})
        group = "__row__"
    summed = rows.groupby(group, sort=True)[[events, totals]].sum()
    counts = {}
    for key, row in summed.iterrows():
        x, other = float(row[events]), float(row[totals])
        n = other if options.get("trials_column") else x + other
        if x > n:
            raise StatisticalTestContractError(f"proportions group {key}: events {x:g} exceed trials {n:g}")
        counts[key] = (x, n)
    return counts, dropped


def _ordered(counts: dict[Any, tuple[float, float]], order: Sequence[Any] | None) -> list[Any]:
    keys = list(counts)
    if len(keys) != 2:
        raise StatisticalTestContractError(
            f"proportions compares exactly two groups; group_column has {len(keys)}: {', '.join(map(str, keys[:8]))}"
        )
    if order is None:
        return keys
    by_text = {str(key): key for key in keys}
    if len(order) != 2 or {str(value) for value in order} != set(by_text):
        rows = " (without group_column the groups are the two counted rows, named by position)" \
            if set(by_text) == {"row 1", "row 2"} else ""
        raise StatisticalTestContractError(
            f"proportions group_order must list the two groups {sorted(by_text)}{rows}; got {list(order)}"
        )
    return [by_text[str(value)] for value in order]


def check_groups(frame: pd.DataFrame, options: dict[str, Any]) -> None:
    """The engine's own role, count and group checks, without computing the comparison.

    QRData 070 (08cfac50 round) wrote group_order ["1", "2"] for two counted rows, which the engine
    names "row 1" and "row 2"; the refusal came only after the person had approved the plan.
    """
    _ordered(_counts(frame, options)[0], options.get("group_order"))


def _log_interval(estimate: float, se: float, z: float) -> dict[str, Any]:
    log = math.log(estimate)
    return {"estimate": _safe_float(estimate), "std_error_log": _safe_float(se),
            "ci_lower": _safe_float(math.exp(log - z * se)), "ci_upper": _safe_float(math.exp(log + z * se))}


def two_proportions(frame: pd.DataFrame, options: dict[str, Any]) -> dict[str, Any]:
    level = float(options.get("confidence_level", 0.95))
    counts, dropped = _counts(frame, options)
    first, second = _ordered(counts, options.get("group_order"))
    (x1, n1), (x2, n2) = counts[first], counts[second]
    if min(n1, n2) <= 0:
        raise StatisticalTestContractError("proportions needs at least one trial in each group")
    p1, p2 = x1 / n1, x2 / n2
    z = float(stats.norm.ppf(0.5 + level / 2))
    difference = p1 - p2
    se_difference = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    pooled = (x1 + x2) / (n1 + n2)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    statistic = difference / se_pooled if se_pooled > 0 else None
    p_value = 2 * float(stats.norm.sf(abs(statistic))) if statistic is not None else None
    unavailable = "not estimable on the log scale: a cell count is zero"
    risk_ratio = (_log_interval(p1 / p2, math.sqrt(1 / x1 - 1 / n1 + 1 / x2 - 1 / n2), z)
                  if x1 > 0 and x2 > 0 else {"estimate": None, "unavailable": unavailable})
    cells = (x1, n1 - x1, x2, n2 - x2)
    odds_ratio = (_log_interval((cells[0] * cells[3]) / (cells[1] * cells[2]), math.sqrt(sum(1 / cell for cell in cells)), z)
                  if min(cells) > 0 else {"estimate": None, "unavailable": unavailable})
    group = str(options.get("group_column") or "row order")
    measured = str(options.get("outcome_column") or options["events_column"])
    labels = [str(first), str(second)]
    return {
        "test_id": f"two_proportions:{measured}:{group}",
        "test_type": "two_proportions",
        "outcome": measured,
        "group": group,
        "variables": proportion_columns(options),
        "groups": labels,
        "nobs": int(n1 + n2),
        "rows_dropped_missing": dropped,
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {
            "comparison": f"{labels[0]} minus (or over) {labels[1]}",
            "confidence_level": level,
            "counts": {labels[0]: {"events": int(x1), "trials": int(n1), "proportion": _safe_float(p1)},
                       labels[1]: {"events": int(x2), "trials": int(n2), "proportion": _safe_float(p2)}},
            "rate_difference": {"estimate": _safe_float(difference), "std_error": _safe_float(se_difference),
                                "ci_lower": _safe_float(difference - z * se_difference),
                                "ci_upper": _safe_float(difference + z * se_difference),
                                "method": "Wald interval, unpooled standard error (Stata prtest)"},
            "risk_ratio": {**risk_ratio, "method": "log-scale interval (Stata csi)"},
            "odds_ratio": {**odds_ratio, "method": "Woolf log-scale interval (Stata csi, woolf)"},
        },
        "assumptions": [
            "Observations are independent, within and between the two groups.",
            "The normal approximation needs enough events and non-events in each group; with few, use test.fisher_exact.",
            "The z test uses the pooled proportion; the rate-difference interval uses the unpooled standard error.",
        ],
        "source_id": f"statistical_tests.proportions.two_proportions.{measured}.{group}",
    }
