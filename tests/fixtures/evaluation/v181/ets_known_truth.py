"""Known-truth synthetic ETS series for the v1.8.1 Independent Evaluation Lane.

These generators are the *oracle*: the Model Pack Lane cannot grade itself
against them, because the parameters here are the parameters that produced the
data, not the parameters some fitter reported.

Data-generating process
-----------------------
Every series is simulated from the **additive-error innovations state space
form** of exponential smoothing, which is exactly the family the locked contract
(`backend/workbench/contracts/model/ets.py`) says is fitted by maximum
likelihood via ``statsmodels`` ``ETSModel``. For ETS(A,Ad,N):

    y_t = l_{t-1} + phi * b_{t-1} + e_t
    l_t = l_{t-1} + phi * b_{t-1} + alpha * e_t
    b_t = phi * b_{t-1} + beta  * e_t
    e_t ~ iid N(0, sigma^2)

with ``phi = 1`` giving the undamped ETS(A,A,N) and ``beta = 0, phi = 1`` (no
trend state) giving ETS(A,N,N). The seasonal additive form adds a state vector
``s`` of length ``m``:

    y_t = l_{t-1} + phi * b_{t-1} + s_{t-m} + e_t
    s_t = s_{t-m} + gamma * e_t

Note ``beta`` here is statsmodels' ``smoothing_trend`` (sometimes written
``beta = alpha * beta_star``) and ``gamma`` is ``smoothing_seasonal``. The
recursions below are written out longhand and deliberately share no code with
the production pack.

Every series is fully reproducible from ``(seed, n, parameters)`` using
``numpy.random.default_rng``; ``KnownTruthETS.regenerate()`` re-runs the DGP so a
reviewer can confirm the bytes were not hand-edited.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# statsmodels' ETS parameters that our DGP pins directly. Anything the fitter
# reports outside this set is either an initial state or a nuisance parameter.
TRUTH_PARAM_NAMES = (
    "smoothing_level",
    "smoothing_trend",
    "smoothing_seasonal",
    "damping_trend",
)


@dataclass(frozen=True)
class KnownTruthETS:
    """One reproducible synthetic ETS series plus the truth that made it."""

    name: str
    seed: int
    n: int
    spec: dict[str, Any]
    truth: dict[str, float]
    sigma: float
    initial_level: float
    initial_trend: float
    initial_seasonal: tuple[float, ...]
    values: np.ndarray = field(repr=False)
    innovations: np.ndarray = field(repr=False)

    @property
    def canonical(self) -> str:
        letters = {"add": "A", "mul": "M", None: "N"}
        trend = letters[self.spec["trend"]] + ("d" if self.spec["damped_trend"] else "")
        return f"ETS({letters[self.spec['error']]},{trend},{letters[self.spec['seasonal']]})"

    def regenerate(self) -> np.ndarray:
        return _simulate(
            n=self.n,
            seed=self.seed,
            alpha=self.truth["smoothing_level"],
            beta=self.truth.get("smoothing_trend", 0.0),
            gamma=self.truth.get("smoothing_seasonal", 0.0),
            phi=self.truth.get("damping_trend", 1.0),
            sigma=self.sigma,
            level0=self.initial_level,
            trend0=self.initial_trend,
            seasonal0=self.initial_seasonal,
            has_trend=self.spec["trend"] is not None,
            has_seasonal=self.spec["seasonal"] is not None,
        )[0]

    def values_sha256(self) -> str:
        return hashlib.sha256(
            np.ascontiguousarray(self.values, dtype=np.float64).tobytes()
        ).hexdigest()

    def manifest(self) -> dict[str, Any]:
        """The publishable description of this oracle (no raw user data)."""

        return {
            "name": self.name,
            "canonical": self.canonical,
            "seed": self.seed,
            "n": self.n,
            "specification": dict(self.spec),
            "truth": dict(self.truth),
            "sigma": self.sigma,
            "initial_level": self.initial_level,
            "initial_trend": self.initial_trend,
            "initial_seasonal": list(self.initial_seasonal),
            "values_sha256": self.values_sha256(),
        }


def _simulate(
    *,
    n: int,
    seed: int,
    alpha: float,
    beta: float,
    gamma: float,
    phi: float,
    sigma: float,
    level0: float,
    trend0: float,
    seasonal0: tuple[float, ...],
    has_trend: bool,
    has_seasonal: bool,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    errors = rng.normal(0.0, sigma, size=n)
    values = np.empty(n, dtype=np.float64)

    level = float(level0)
    trend = float(trend0) if has_trend else 0.0
    season = list(seasonal0) if has_seasonal else []
    m = len(season)

    for t in range(n):
        seasonal_term = season[t % m] if has_seasonal else 0.0
        mu = level + (phi * trend if has_trend else 0.0) + seasonal_term
        e = errors[t]
        values[t] = mu + e
        new_level = level + (phi * trend if has_trend else 0.0) + alpha * e
        if has_trend:
            trend = phi * trend + beta * e
        if has_seasonal:
            season[t % m] = season[t % m] + gamma * e
        level = new_level

    return values, errors


def _make(
    *,
    name: str,
    seed: int,
    n: int,
    error: str = "add",
    trend: str | None,
    seasonal: str | None,
    seasonal_periods: int | None,
    damped_trend: bool,
    alpha: float,
    beta: float = 0.0,
    gamma: float = 0.0,
    phi: float = 1.0,
    sigma: float,
    level0: float,
    trend0: float = 0.0,
    seasonal0: tuple[float, ...] = (),
) -> KnownTruthETS:
    values, errors = _simulate(
        n=n,
        seed=seed,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        phi=phi,
        sigma=sigma,
        level0=level0,
        trend0=trend0,
        seasonal0=seasonal0,
        has_trend=trend is not None,
        has_seasonal=seasonal is not None,
    )
    truth: dict[str, float] = {"smoothing_level": alpha}
    if trend is not None:
        truth["smoothing_trend"] = beta
        if damped_trend:
            truth["damping_trend"] = phi
    if seasonal is not None:
        truth["smoothing_seasonal"] = gamma
    return KnownTruthETS(
        name=name,
        seed=seed,
        n=n,
        spec={
            "error": error,
            "trend": trend,
            "seasonal": seasonal,
            "seasonal_periods": seasonal_periods,
            "damped_trend": damped_trend,
        },
        truth=truth,
        sigma=sigma,
        initial_level=level0,
        initial_trend=trend0,
        initial_seasonal=tuple(seasonal0),
        values=values,
        innovations=errors,
    )


# --------------------------------------------------------------------------
# The four oracles. Sample sizes were chosen from the Monte-Carlo calibration
# recorded in tolerances.py: they are the smallest round n at which the MLE
# sampling spread of every pinned parameter is small enough for a tolerance that
# would still catch a wrong-parameterisation bug (e.g. beta vs beta*).
# --------------------------------------------------------------------------


def ann_local_level() -> KnownTruthETS:
    """ETS(A,N,N): pure local level. alpha only."""

    return _make(
        name="ann_local_level",
        seed=181_001,
        n=4000,
        trend=None,
        seasonal=None,
        seasonal_periods=None,
        damped_trend=False,
        alpha=0.35,
        sigma=1.0,
        level0=20.0,
    )


def aan_linear_trend() -> KnownTruthETS:
    """ETS(A,A,N): undamped additive trend."""

    return _make(
        name="aan_linear_trend",
        seed=181_002,
        n=4000,
        trend="add",
        seasonal=None,
        seasonal_periods=None,
        damped_trend=False,
        alpha=0.50,
        beta=0.10,
        sigma=1.0,
        level0=10.0,
        trend0=0.05,
    )


def aadn_damped_trend() -> KnownTruthETS:
    """ETS(A,Ad,N): damped trend — the specification in the locked fixture."""

    return _make(
        name="aadn_damped_trend",
        seed=181_003,
        n=6000,
        trend="add",
        seasonal=None,
        seasonal_periods=None,
        damped_trend=True,
        alpha=0.45,
        beta=0.08,
        phi=0.90,
        sigma=1.0,
        level0=18.0,
        trend0=0.20,
    )


def aaa_seasonal() -> KnownTruthETS:
    """ETS(A,A,A) with m=12: exercises seasonal_periods identity."""

    return _make(
        name="aaa_seasonal",
        seed=181_004,
        n=6000,
        trend="add",
        seasonal="add",
        seasonal_periods=12,
        damped_trend=False,
        alpha=0.40,
        beta=0.06,
        gamma=0.15,
        sigma=1.0,
        level0=50.0,
        trend0=0.02,
        seasonal0=(
            3.0,
            2.1,
            0.4,
            -1.2,
            -2.6,
            -3.1,
            -2.2,
            -0.7,
            0.9,
            1.8,
            2.4,
            -0.8,
        ),
    )


ALL_ORACLES = (
    ann_local_level,
    aan_linear_trend,
    aadn_damped_trend,
    aaa_seasonal,
)


__all__ = [
    "ALL_ORACLES",
    "KnownTruthETS",
    "TRUTH_PARAM_NAMES",
    "aadn_damped_trend",
    "aan_linear_trend",
    "aaa_seasonal",
    "ann_local_level",
]
