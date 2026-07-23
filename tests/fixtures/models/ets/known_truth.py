"""Deterministic synthetic known-truth series for the v1.8.1 ETS pack.

The generators implement the innovations state-space recursions of Hyndman's
ETS taxonomy directly, independently of any production or statsmodels code, so
that a recovery test is a genuine oracle rather than a tautology.

Additive-error recursions used here (m = seasonal_periods, phi = damping):

    ETS(A,A,N)   y_t = l_{t-1} + phi*b_{t-1} + e_t
                 l_t = l_{t-1} + phi*b_{t-1} + alpha*e_t
                 b_t = phi*b_{t-1} + beta*e_t

    ETS(A,A,A)   y_t = l_{t-1} + phi*b_{t-1} + s_{t-m} + e_t
                 l_t = l_{t-1} + phi*b_{t-1} + alpha*e_t
                 b_t = phi*b_{t-1} + beta*e_t
                 s_t = s_{t-m} + gamma*e_t

`beta` and `gamma` are the state-space smoothing parameters (Hyndman's
beta = alpha*beta*, gamma = (1-alpha)*gamma*), which is exactly what
statsmodels reports as `smoothing_trend` / `smoothing_seasonal`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ETSKnownTruthSeries:
    """A synthetic series plus the parameters that generated it."""

    values: np.ndarray
    innovations: np.ndarray
    seed: int
    parameters: dict[str, object]

    def frame(
        self,
        *,
        time_column: str = "date",
        value_column: str = "y",
        start: str = "2015-01-01",
        freq: str = "D",
    ) -> pd.DataFrame:
        index = pd.date_range(start=start, periods=len(self.values), freq=freq)
        return pd.DataFrame(
            {
                time_column: index.strftime("%Y-%m-%d"),
                value_column: self.values.astype(float),
            }
        )


def simulate_ets_additive(
    *,
    n: int,
    seed: int,
    alpha: float,
    beta: float | None = None,
    gamma: float | None = None,
    phi: float = 1.0,
    initial_level: float = 10.0,
    initial_trend: float = 0.0,
    initial_seasonal: Sequence[float] | None = None,
    sigma: float = 1.0,
) -> ETSKnownTruthSeries:
    """Simulate an additive-error ETS series from explicit known parameters."""

    if n <= 0:
        raise ValueError("n must be positive")
    rng = np.random.default_rng(seed)
    innovations = rng.normal(0.0, sigma, n)
    values = np.empty(n, dtype=float)

    level = float(initial_level)
    trend = float(initial_trend) if beta is not None else 0.0
    seasonal = list(float(value) for value in (initial_seasonal or ()))
    damping = float(phi) if beta is not None else 1.0

    for index in range(n):
        season = seasonal[0] if seasonal else 0.0
        error = float(innovations[index])
        values[index] = level + damping * trend + season + error
        next_level = level + damping * trend + alpha * error
        next_trend = damping * trend + (beta or 0.0) * error
        if seasonal:
            seasonal.pop(0)
            seasonal.append(season + (gamma or 0.0) * error)
        level, trend = next_level, next_trend

    return ETSKnownTruthSeries(
        values=values,
        innovations=innovations,
        seed=seed,
        parameters={
            "error": "add",
            "trend": None if beta is None else "add",
            "seasonal": None if gamma is None else "add",
            "seasonal_periods": len(initial_seasonal) if initial_seasonal else None,
            "damped_trend": beta is not None and float(phi) != 1.0,
            "smoothing_level": float(alpha),
            "smoothing_trend": None if beta is None else float(beta),
            "smoothing_seasonal": None if gamma is None else float(gamma),
            "damping_trend": None if beta is None else float(phi),
            "initial_level": float(initial_level),
            "initial_trend": None if beta is None else float(initial_trend),
            "sigma": float(sigma),
            "sigma2": float(sigma) ** 2,
            "n": int(n),
        },
    )


def additive_trend_series() -> ETSKnownTruthSeries:
    """ETS(A,A,N) — undamped additive trend."""

    return simulate_ets_additive(
        n=4_000,
        seed=1_810_101,
        alpha=0.40,
        beta=0.10,
        initial_level=10.0,
        initial_trend=0.05,
        sigma=1.0,
    )


def damped_trend_series() -> ETSKnownTruthSeries:
    """ETS(A,Ad,N) — damped additive trend, phi = 0.90."""

    return simulate_ets_additive(
        n=4_000,
        seed=1_810_102,
        alpha=0.40,
        beta=0.10,
        phi=0.90,
        initial_level=10.0,
        initial_trend=0.05,
        sigma=1.0,
    )


def seasonal_series() -> ETSKnownTruthSeries:
    """ETS(A,A,A) — additive trend plus a period-4 additive season."""

    return simulate_ets_additive(
        n=4_000,
        seed=1_810_103,
        alpha=0.40,
        beta=0.05,
        gamma=0.10,
        initial_level=10.0,
        initial_trend=0.02,
        initial_seasonal=(2.0, -1.0, -3.0, 2.0),
        sigma=1.0,
    )


def short_stable_series() -> ETSKnownTruthSeries:
    """A short, cheap series for structural (non-recovery) tests."""

    return simulate_ets_additive(
        n=120,
        seed=1_810_104,
        alpha=0.30,
        beta=0.05,
        initial_level=20.0,
        initial_trend=0.10,
        sigma=0.5,
    )


__all__ = [
    "ETSKnownTruthSeries",
    "additive_trend_series",
    "damped_trend_series",
    "seasonal_series",
    "short_stable_series",
    "simulate_ets_additive",
]
