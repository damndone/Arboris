"""Fault-injection cases for the v1.8.1 ETS Model Pack.

Each case states, *before* any implementation exists, what the locked contract
requires the system to do. The expectation is expressed as a machine-checkable
verdict so an implementation cannot satisfy it by producing plausible-looking
numbers.

Verdicts
--------
``blocked``
    The pack must refuse to report an estimate. Concretely: either it raises,
    or it returns a result whose ``convergence_code`` is a non-``converged``
    code *and* which carries no headline parameter estimates presented as
    usable. A silent numeric answer is a failure.
``rejected``
    The specification itself is illegal and must be refused at contract or
    validation time (``ETSContractError`` or an equivalent refusal), before any
    optimiser runs.
``converged``
    The case is legal and must fit.

Contract basis (``backend/workbench/contracts/model/ets.py``):
point 4 — interior gaps are blocking; point 5 — non-convergence is a blocking
diagnostic, "not a warning with numbers shown"; ``ETSSpecification.__post_init__``
— illegal component combinations are refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .ets_known_truth import aadn_damped_trend, aan_linear_trend, ann_local_level


@dataclass(frozen=True)
class FaultCase:
    """One injected fault plus the verdict the contract requires."""

    name: str
    verdict: str  # blocked | rejected | converged
    contract_basis: str
    description: str
    spec: dict[str, Any]
    values: np.ndarray | None = field(default=None, repr=False)
    expected_reason_substrings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in {"blocked", "rejected", "converged"}:
            raise ValueError(f"unknown verdict {self.verdict!r}")


def _spec(
    error: str = "add",
    trend: str | None = "add",
    seasonal: str | None = None,
    seasonal_periods: int | None = None,
    damped_trend: bool = False,
) -> dict[str, Any]:
    return {
        "error": error,
        "trend": trend,
        "seasonal": seasonal,
        "seasonal_periods": seasonal_periods,
        "damped_trend": damped_trend,
    }


# --- data faults ----------------------------------------------------------


def interior_missing() -> FaultCase:
    """A gap in the middle of the series. Contract point 4: blocking.

    An interior NaN cannot be complete-cased away: dropping it silently
    re-indexes time, so the surviving observations are no longer one period
    apart and every smoothing recursion is quietly wrong.
    """

    base = aan_linear_trend()
    values = base.values.copy()
    values[1500:1505] = np.nan
    return FaultCase(
        name="interior_missing",
        verdict="blocked",
        contract_basis="ets.py docstring point 4",
        description="5 consecutive NaN at t=1500..1504 in an otherwise clean ETS(A,A,N)",
        spec=_spec(trend="add"),
        values=values,
        expected_reason_substrings=("interior", "gap", "missing"),
    )


def leading_and_trailing_missing() -> FaultCase:
    """Edge NaNs are *not* interior; complete-case is legitimate and must be counted."""

    base = aan_linear_trend()
    values = base.values.copy()
    values[:3] = np.nan
    values[-2:] = np.nan
    return FaultCase(
        name="leading_and_trailing_missing",
        verdict="converged",
        contract_basis="ets.py docstring point 4 (counted and reported)",
        description="3 leading and 2 trailing NaN; n_excluded must equal 5",
        spec=_spec(trend="add"),
        values=values,
    )


def too_short_for_trend() -> FaultCase:
    """4 observations, 5 free parameters for ETS(A,A,N). Not identified."""

    return FaultCase(
        name="too_short_for_trend",
        verdict="blocked",
        contract_basis="identification: n_obs < number of free parameters",
        description="ETS(A,A,N) on 4 observations",
        spec=_spec(trend="add"),
        values=np.array([10.0, 10.4, 10.9, 11.1]),
        expected_reason_substrings=("short", "observation", "insufficient"),
    )


def too_short_for_seasonal() -> FaultCase:
    """Seasonal with m=12 but fewer than two full cycles."""

    rng = np.random.default_rng(181_101)
    return FaultCase(
        name="too_short_for_seasonal",
        verdict="blocked",
        contract_basis="identification: fewer than two seasonal cycles",
        description="ETS(A,A,A) m=12 on 14 observations",
        spec=_spec(trend="add", seasonal="add", seasonal_periods=12),
        values=50.0 + rng.normal(0.0, 1.0, size=14),
        expected_reason_substrings=("season", "cycle", "short"),
    )


def degenerate_constant_series() -> FaultCase:
    """A perfectly constant series: zero innovation variance, singular likelihood.

    The log-likelihood of an additive-error ETS is unbounded as sigma^2 -> 0, so
    any reported AIC is meaningless. Reporting a converged fit here is exactly
    the "numbers shown for a fit that did not happen" failure mode.
    """

    return FaultCase(
        name="degenerate_constant_series",
        verdict="blocked",
        contract_basis="ets.py docstring point 5 (degenerate/singular fit)",
        description="400 identical values; sigma^2 -> 0, likelihood unbounded",
        spec=_spec(trend=None),
        values=np.full(400, 7.5),
        expected_reason_substrings=("degenerate", "constant", "singular", "variance"),
    )


def degenerate_exact_line() -> FaultCase:
    """A noiseless deterministic line: also zero-variance, trend model singular."""

    return FaultCase(
        name="degenerate_exact_line",
        verdict="blocked",
        contract_basis="ets.py docstring point 5 (degenerate/singular fit)",
        description="500 points on y = 3 + 0.5t exactly, no noise",
        spec=_spec(trend="add"),
        values=3.0 + 0.5 * np.arange(500.0),
        expected_reason_substrings=("degenerate", "singular", "variance"),
    )


def non_finite_value() -> FaultCase:
    """A +inf in the middle. Never estimable; must not become a NaN AIC."""

    base = ann_local_level()
    values = base.values.copy()
    values[900] = np.inf
    return FaultCase(
        name="non_finite_value",
        verdict="blocked",
        contract_basis="envelope.freeze_json: packets must contain only finite numbers",
        description="a single +inf at t=900",
        spec=_spec(trend=None),
        values=values,
        expected_reason_substrings=("finite", "inf", "invalid"),
    )


def multiplicative_error_on_non_positive_data() -> FaultCase:
    """ETS(M,*,*) requires strictly positive data; this series crosses zero."""

    base = aadn_damped_trend()
    values = base.values.copy() - float(np.mean(base.values))
    return FaultCase(
        name="multiplicative_error_on_non_positive_data",
        verdict="blocked",
        contract_basis="multiplicative error is undefined at y <= 0",
        description="ETS(M,N,N) on a mean-centred series containing negatives",
        spec=_spec(error="mul", trend=None),
        values=values,
        expected_reason_substrings=("positive", "multiplicative"),
    )


DATA_FAULT_CASES = (
    interior_missing,
    leading_and_trailing_missing,
    too_short_for_trend,
    too_short_for_seasonal,
    degenerate_constant_series,
    degenerate_exact_line,
    non_finite_value,
    multiplicative_error_on_non_positive_data,
)


# --- specification faults (must be refused before fitting) ----------------

ILLEGAL_SPECIFICATIONS: tuple[FaultCase, ...] = (
    FaultCase(
        name="damped_without_trend",
        verdict="rejected",
        contract_basis="ETSSpecification.__post_init__",
        description="damped_trend=True with trend=None",
        spec=_spec(trend=None, damped_trend=True),
    ),
    FaultCase(
        name="seasonal_without_periods",
        verdict="rejected",
        contract_basis="ETSSpecification.__post_init__",
        description="seasonal='add' with seasonal_periods=None",
        spec=_spec(seasonal="add", seasonal_periods=None),
    ),
    FaultCase(
        name="seasonal_periods_zero",
        verdict="rejected",
        contract_basis="ETSSpecification.__post_init__ (falsy seasonal_periods)",
        description="seasonal='add' with seasonal_periods=0",
        spec=_spec(seasonal="add", seasonal_periods=0),
    ),
    FaultCase(
        name="error_none",
        verdict="rejected",
        contract_basis="ERROR_COMPONENTS = (add, mul)",
        description="error=None is not an ETS error component",
        spec=_spec(error=None),  # type: ignore[arg-type]
    ),
    FaultCase(
        name="error_unknown_letter",
        verdict="rejected",
        contract_basis="ERROR_COMPONENTS = (add, mul)",
        description="error='additive' (long form) must not be coerced",
        spec=_spec(error="additive"),
    ),
    FaultCase(
        name="trend_unknown",
        verdict="rejected",
        contract_basis="TREND_COMPONENTS",
        description="trend='linear' is not a component",
        spec=_spec(trend="linear"),
    ),
    FaultCase(
        name="seasonal_unknown",
        verdict="rejected",
        contract_basis="SEASONAL_COMPONENTS",
        description="seasonal='additive' is not a component",
        spec=_spec(seasonal="additive", seasonal_periods=12),
    ),
)


__all__ = [
    "DATA_FAULT_CASES",
    "FaultCase",
    "ILLEGAL_SPECIFICATIONS",
]
