"""Deterministic synthetic known-truth series for the v1.8 ARMA-GARCH pack.

The generators intentionally stay independent of the production fitting code.
They implement only the data-generating recursions needed by acceptance tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class KnownTruthSeries:
    values: np.ndarray
    innovations: np.ndarray
    standardized_shocks: np.ndarray
    conditional_variance: np.ndarray
    seed: int
    parameters: dict[str, object]


def arma11_homoskedastic() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=650,
        seed=18_041,
        ar=0.45,
        ma=-0.30,
        omega=1.0,
    )


def ar1_garch11() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=900,
        seed=18_042,
        ar=0.35,
        omega=0.08,
        alphas=(0.14,),
        betas=(0.80,),
    )


def sequential_arma11_garch11() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=800,
        seed=18_043,
        ar=0.40,
        ma=-0.25,
        omega=0.10,
        alphas=(0.12,),
        betas=(0.80,),
    )


def arch5() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=1_000,
        seed=18_044,
        omega=0.20,
        alphas=(0.08, 0.06, 0.05, 0.04, 0.45),
    )


def student_t_garch11() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=1_300,
        seed=18_045,
        omega=0.08,
        alphas=(0.12,),
        betas=(0.80,),
        distribution="student_t",
        degrees_of_freedom=5.0,
    )


def no_arch() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=700,
        seed=18_046,
        omega=1.0,
    )


def near_unit_garch11() -> KnownTruthSeries:
    return simulate_arma_garch(
        n=500,
        seed=18_047,
        omega=0.01,
        alphas=(0.04,),
        betas=(0.955,),
    )


def simulate_arma_garch(
    *,
    n: int,
    seed: int,
    ar: float = 0.0,
    ma: float = 0.0,
    omega: float,
    alphas: tuple[float, ...] = (),
    betas: tuple[float, ...] = (),
    distribution: str = "normal",
    degrees_of_freedom: float | None = None,
    burn_in: int = 500,
) -> KnownTruthSeries:
    """Simulate a stationary ARMA(1,1) with ARCH/GARCH innovations."""

    persistence = sum(alphas) + sum(betas)
    if n < 1 or burn_in < 1:
        raise ValueError("n and burn_in must be positive")
    if not 0.0 <= persistence < 1.0:
        raise ValueError("known-truth simulation requires stationary variance")
    if omega <= 0.0 or abs(ar) >= 1.0 or abs(ma) >= 1.0:
        raise ValueError("known-truth parameters are outside the stable test envelope")

    total = n + burn_in
    rng = np.random.default_rng(seed)
    if distribution == "normal":
        shocks = rng.normal(size=total)
    elif distribution == "student_t":
        if degrees_of_freedom is None or degrees_of_freedom <= 2.0:
            raise ValueError("student_t simulation requires degrees_of_freedom > 2")
        shocks = rng.standard_t(degrees_of_freedom, size=total)
        shocks /= math.sqrt(degrees_of_freedom / (degrees_of_freedom - 2.0))
    else:
        raise ValueError(f"unsupported innovation distribution: {distribution}")

    values = np.zeros(total, dtype=float)
    innovations = np.zeros(total, dtype=float)
    variance = np.full(total, omega / max(1.0 - persistence, 1e-12), dtype=float)
    for index in range(total):
        current_variance = omega
        for lag, coefficient in enumerate(alphas, start=1):
            if index >= lag:
                current_variance += coefficient * innovations[index - lag] ** 2
            else:
                current_variance += coefficient * variance[0]
        for lag, coefficient in enumerate(betas, start=1):
            current_variance += coefficient * variance[index - lag if index >= lag else 0]
        variance[index] = current_variance
        innovations[index] = math.sqrt(current_variance) * shocks[index]
        if index:
            values[index] = (
                ar * values[index - 1]
                + innovations[index]
                + ma * innovations[index - 1]
            )
        else:
            values[index] = innovations[index]

    kept = slice(burn_in, None)
    return KnownTruthSeries(
        values=values[kept].copy(),
        innovations=innovations[kept].copy(),
        standardized_shocks=shocks[kept].copy(),
        conditional_variance=variance[kept].copy(),
        seed=seed,
        parameters={
            "ar": ar,
            "ma": ma,
            "omega": omega,
            "alphas": alphas,
            "betas": betas,
            "persistence": persistence,
            "distribution": distribution,
            "degrees_of_freedom": degrees_of_freedom,
        },
    )


__all__ = [
    "KnownTruthSeries",
    "arch5",
    "ar1_garch11",
    "arma11_homoskedastic",
    "near_unit_garch11",
    "no_arch",
    "sequential_arma11_garch11",
    "simulate_arma_garch",
    "student_t_garch11",
]
