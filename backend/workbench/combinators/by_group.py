"""Run one capability separately for each group (SPSS SPLIT FILE, Stata `by:`).

Explicit per analysis: a request names its grouping column; there is no global
switch to forget. Each capability declares its subset semantics:

- ``subset``: filter the rows of the group, then run as usual;
- ``domain``: keep every row and estimate for the group as a subpopulation.
  Under a complex sampling design this is the only correct choice -- filtering
  first destroys the design's variance estimate (Stata's svy documentation
  warns against `if` for exactly this reason);
- ``unsupported``: refused.

A missing group value forms its own group, labelled ``(missing)`` and
reported, never silently dropped. A group too small to estimate is listed as
not estimable with the reason; the minimum is read from the check library, so
by-group execution and the checks cannot disagree about what is too small.

Groups are compared only through a test of their difference (see
``group_difference_terms``); coefficients side by side are not such a test.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

MAX_GROUPS = 50
MISSING_GROUP = "(missing)"
SUBSET_SEMANTICS = ("subset", "domain", "unsupported")

#: Capabilities open to by-group execution: each declares its subset semantics
#: and is covered by the generic invariance test (tests/test_by_group_invariance.py).
BY_GROUP_OPEN: Mapping[str, str] = {
    "ols": "subset",
    "logit": "subset",
    "probit": "subset",
    "poisson": "subset",
    "statistical.explore": "subset",
    "test.t_tests": "subset",
    "test.chi_square": "subset",
    "test.correlations": "subset",
}


#: Handler keys that run an open capability under another name.
_ALIASES: Mapping[str, str] = {"poisson_rate": "poisson"}


def capability_for(model_type: str) -> str:
    return _ALIASES.get(model_type, model_type)


class ByGroupRefusal(ValueError):
    """A by-group request that is not offered, with the reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Group:
    index: int
    key: str           # the value as displayed, or MISSING_GROUP
    value: Any         # the raw value (None for the missing group)
    mask: np.ndarray   # rows of the frame in this group

    @property
    def slug(self) -> str:
        return f"g{self.index:02d}"

    @property
    def nobs(self) -> int:
        return int(self.mask.sum())


def semantics_for(capability: str, *, design_declared: bool) -> str:
    """How a capability runs on one group; refuses one that is not open."""
    declared = BY_GROUP_OPEN.get(capability)
    if declared is None:
        open_ = ", ".join(sorted(BY_GROUP_OPEN))
        raise ByGroupRefusal(
            "NOT_OFFERED",
            f"{capability} does not run by group yet: it has not declared how a group is "
            f"formed (subset or domain) and passed the invariance test. Offered: {open_}.",
        )
    if design_declared:
        if capability.startswith("test."):
            raise ByGroupRefusal(
                "DESIGN_NOT_SUPPORTED",
                f"{capability} by group under a sampling design would need domain estimation, "
                "which this test does not implement; filtering the rows first would make its "
                "variance wrong.",
            )
        return "domain"
    return declared


def _display(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def plan_groups(frame: pd.DataFrame, column: str, *, max_groups: int = MAX_GROUPS) -> list[Group]:
    """The groups of ``column``, sorted by value, the missing group last."""
    if column not in frame.columns:
        raise ByGroupRefusal("COLUMN_MISSING", f"the grouping column {column!r} is not in the data")
    values = frame[column]
    present = values.dropna()
    distinct = sorted(present.unique().tolist(), key=lambda item: (str(type(item)), item))
    has_missing = bool(values.isna().any())
    count = len(distinct) + int(has_missing)
    if count > max_groups:
        raise ByGroupRefusal(
            "TOO_MANY_GROUPS",
            f"{column} has {count} groups, more than the {max_groups} allowed. With this many "
            "groups the question is a multilevel one: use an interaction with the group, or a "
            "mixed-effects model.",
        )
    if count < 2:
        raise ByGroupRefusal("ONE_GROUP", f"{column} has only {count} group; there is nothing to split.")
    groups = [
        Group(index=index, key=_display(value), value=value, mask=(values == value).to_numpy())
        for index, value in enumerate(distinct, start=1)
    ]
    if has_missing:
        groups.append(Group(index=len(groups) + 1, key=MISSING_GROUP, value=None,
                            mask=values.isna().to_numpy()))
    return groups


def too_small(nobs: int, parameters: int, *, events: int | None = None) -> str | None:
    """Why a group cannot be estimated, by the check library's thresholds; None if it can."""
    from ..checks.design_checks import ROWS_PER_PARAMETER
    from ..checks.fit_checks import EVENTS_PER_VARIABLE

    rows_limit = ROWS_PER_PARAMETER.threshold("caution_below")
    if parameters > 0 and nobs / parameters < rows_limit:
        source = next(item.source for item in ROWS_PER_PARAMETER.thresholds if item.name == "caution_below")
        return (
            f"{nobs} rows for {parameters} parameters ({nobs / parameters:.1f} per parameter), "
            f"below the {rows_limit:g} rows per parameter the check library requires ({source})."
        )
    if events is not None:
        events_limit = EVENTS_PER_VARIABLE.threshold("caution_below")
        regressors = max(parameters - 1, 1)
        if events / regressors < events_limit:
            source = next(item.source for item in EVENTS_PER_VARIABLE.thresholds if item.name == "caution_below")
            return (
                f"{events} events of the smaller outcome class for {regressors} regressors "
                f"({events / regressors:.1f} per regressor), below the {events_limit:g} the check "
                f"library requires ({source})."
            )
    return None


def adjust_p_values(p_values: Sequence[float | None], method: str) -> list[float | None]:
    """Holm (step-down) or Benjamini-Hochberg adjusted p-values; None stays None."""
    if method not in {"holm", "bh"}:
        raise ByGroupRefusal("UNKNOWN_ADJUSTMENT", "adjustment must be holm or bh")
    indexed = [(i, p) for i, p in enumerate(p_values) if p is not None and math.isfinite(p)]
    m = len(indexed)
    adjusted: list[float | None] = [None] * len(p_values)
    if not m:
        return adjusted
    order = sorted(indexed, key=lambda item: item[1])
    if method == "holm":
        running = 0.0
        for rank, (i, p) in enumerate(order):
            running = max(running, min(1.0, (m - rank) * p))
            adjusted[i] = running
    else:
        running = 1.0
        for rank in range(m - 1, -1, -1):
            i, p = order[rank]
            running = min(running, min(1.0, p * m / (rank + 1)))
            adjusted[i] = running
    return adjusted


def group_member(group: Group, *, status: str, result_ref: str | None = None,
                 reason: str | None = None, nobs: int | None = None) -> dict[str, Any]:
    """A collection member for one group (contracts/model/result_collection.py).

    ``nobs`` is the rows the estimate used when there is one (rows missing a
    modelled variable are left out); otherwise the group's rows.
    """
    member: dict[str, Any] = {"key": group.key, "status": status,
                              "nobs": int(nobs) if nobs is not None else group.nobs}
    if status == "estimated":
        member["result_ref"] = result_ref
    else:
        member["reason"] = reason
    return member


def run_by_group(frame: pd.DataFrame, column: str, run_one: Any) -> list[dict[str, Any]]:
    """Run ``run_one(subset)`` on each group's rows; a failure is not estimable, with its reason."""
    outcomes: list[dict[str, Any]] = []
    for group in plan_groups(frame, column):
        entry: dict[str, Any] = {"key": group.key, "index": group.index, "nobs": group.nobs}
        try:
            entry.update(status="estimated", result=run_one(frame.loc[group.mask]))
        except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
            entry.update(status="not_estimable", reason=str(error) or type(error).__name__)
        outcomes.append(entry)
    return outcomes


def adjust_across_groups(rows: list[dict[str, Any]], *, identity: str = "test_id") -> None:
    """Holm and Benjamini-Hochberg p-values across groups, for each test, in place.

    The same test run in k groups is k tests; reading one group's significance
    without this adjustment overstates it.
    """
    by_test: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        by_test.setdefault(row.get(identity), []).append(row)
    for members in by_test.values():
        p_values = [row.get("p_value") if isinstance(row.get("p_value"), (int, float)) else None for row in members]
        for method, field in (("holm", "p_value_holm_across_groups"), ("bh", "p_value_bh_across_groups")):
            for row, adjusted in zip(members, adjust_p_values(p_values, method)):
                row[field] = adjusted
            for row in members:
                row["groups_in_adjustment"] = sum(value is not None for value in p_values)
