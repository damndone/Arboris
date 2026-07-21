"""Do-file parity for residual diagnostics.

Gap 3: the reference runs three normality tests (`sktest` omnibus, `swilk`
Shapiro-Wilk, `sfrancia` Shapiro-Francia).
Gap 4: the reference reports the in-sample standardized-residual failure rate
`fail = |z| > 1.96` as a count and a percentage.
"""

from __future__ import annotations

import numpy as np

from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics


def _normal(n: int = 800, seed: int = 11) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=n)


def _heavy_tailed(n: int = 800, seed: int = 12) -> np.ndarray:
    return np.random.default_rng(seed).standard_t(3, size=n)


def test_normality_reports_all_three_tests_on_a_normal_sample() -> None:
    values = _normal()
    normality = dict(build_mean_diagnostics(values, values).normality)

    # Legacy omnibus keys are preserved verbatim (0-drift for existing readers).
    assert normality["status"] == "ok"
    assert normality["p_value"] > 0.01
    assert "skew" in normality and "kurtosis" in normality

    wilk = dict(normality["shapiro_wilk"])
    francia = dict(normality["shapiro_francia"])
    assert wilk["status"] == "ok"
    assert francia["status"] == "ok"
    assert 0.0 < wilk["statistic"] <= 1.0
    assert 0.0 < francia["statistic"] <= 1.0
    assert wilk["p_value"] > 0.01
    assert francia["p_value"] > 0.01


def test_normality_rejects_a_heavy_tailed_sample_on_all_three() -> None:
    values = _heavy_tailed()
    normality = dict(build_mean_diagnostics(values, values).normality)

    assert normality["p_value"] < 0.01
    assert dict(normality["shapiro_wilk"])["p_value"] < 0.01
    assert dict(normality["shapiro_francia"])["p_value"] < 0.01


def test_normality_subtests_degrade_without_raising_on_tiny_samples() -> None:
    values = np.array([0.4, -0.2, 0.1])
    normality = dict(build_mean_diagnostics(values, values).normality)
    # Shapiro-Francia needs more observations than Shapiro-Wilk; neither may raise.
    assert dict(normality["shapiro_francia"])["status"] in {"ok", "unavailable"}
    assert dict(normality["shapiro_wilk"])["status"] in {"ok", "unavailable"}


def test_residual_exceedance_matches_the_reference_failure_rate() -> None:
    values = _normal()
    diagnostics = build_mean_diagnostics(values, values)
    exceedance = dict(diagnostics.residual_exceedance)

    assert exceedance["threshold"] == 1.96
    assert exceedance["n"] == len(values)
    expected_count = int(np.sum(np.abs(values) > 1.96))
    assert exceedance["count"] == expected_count
    assert exceedance["rate"] == expected_count / len(values)
    # A standard normal sample sits near the nominal 5%.
    assert 0.02 < exceedance["rate"] < 0.09


def test_residual_exceedance_is_higher_for_heavy_tails() -> None:
    normal_rate = dict(build_mean_diagnostics(_normal(), _normal()).residual_exceedance)["rate"]
    heavy_rate = dict(
        build_mean_diagnostics(_heavy_tailed(), _heavy_tailed()).residual_exceedance
    )["rate"]
    assert heavy_rate > normal_rate
