"""Numerically justified tolerances for the v1.8.1 ETS evaluation.

Nothing here may be widened to make an implementation pass (ADR §7D). Each
number below is derived from a recorded measurement; the derivation is written
next to it so a reviewer can re-run it.

Calibration run (evaluation lane, 2026-07-22)
---------------------------------------------
Command::

    .venv/bin/python tests/fixtures/evaluation/v181/calibrate_tolerances.py 40

Procedure: for each oracle specification in ``ets_known_truth.py``, 40
independent replications were simulated from the *same* known parameters with
shifted seeds and fitted by ``statsmodels`` ``ETSModel(...).fit()`` — the fit
method the contract locks. The table records the maximum absolute deviation of
each pinned parameter from truth across those 40 replications.

===================  ====  ==========  ==========  ==========  ==========
oracle               n     alpha max   beta max    phi max     gamma max
===================  ====  ==========  ==========  ==========  ==========
ann_local_level      4000  0.03165     --          --          --
aan_linear_trend     4000  0.03653     0.01453     --          --
aadn_damped_trend    6000  0.03759     0.01839     0.02883     --
aaa_seasonal         6000  0.02033     0.00699     --          0.01333
===================  ====  ==========  ==========  ==========  ==========

The tolerance is ``1.5 x`` that observed maximum, rounded up to a readable
figure. 1.5x buys headroom for a different-but-legitimate optimiser without
buying room for a *wrong* estimator.

Discriminating power (why these are not vacuous)
------------------------------------------------
The single most likely real bug is a parameterisation mix-up between
statsmodels' ``beta`` and the textbook ``beta* = beta / alpha`` (and
``gamma* = gamma / (1 - alpha)``). That bug would move the reported value by:

* aan_linear_trend  : |0.10 - 0.20|     = 0.100  vs tolerance 0.025  (4.0x)
* aadn_damped_trend : |0.08 - 0.1778|   = 0.098  vs tolerance 0.030  (3.3x)
* aaa_seasonal      : |0.15 - 0.25|     = 0.100  vs tolerance 0.021  (4.8x)

so every tolerance is at least 3x smaller than the deviation the bug it is
meant to catch would produce.

Reference-fit tolerances
------------------------
``ETS_REFERENCE_AIC_ABS`` compares the pack's reported AIC against an
independent ``ETSModel`` fit performed inside the harness on the same series.
Measured optimiser sensitivity on ``aadn_damped_trend`` (default start vs a
deliberately perturbed start) was **5.6e-07** AIC units. One additional free
parameter costs 2.0 AIC units. The tolerance 0.5 is therefore ~1e6x the
observed numerical jitter and 1/4 of the smallest structural error (a wrong
degrees-of-freedom count) it must catch.

``ETS_SIGMA2_RTOL`` = 0.10. The sampling standard error of a variance estimate
is ``sigma^2 * sqrt(2/n)`` = 2.2% at n=4000 and 1.8% at n=6000, so 10% is
~4.5 standard errors — loose enough not to flake, tight enough that a
scale/variance-definition error (typically a factor of 2 or of n/(n-k)
compounded, i.e. >>10%) still fails.
"""

from __future__ import annotations

from typing import Mapping

# Absolute tolerance on each pinned smoothing/damping parameter, per oracle.
ETS_PARAM_ABS_TOL: Mapping[str, Mapping[str, float]] = {
    "ann_local_level": {"smoothing_level": 0.050},
    "aan_linear_trend": {"smoothing_level": 0.055, "smoothing_trend": 0.025},
    "aadn_damped_trend": {
        "smoothing_level": 0.060,
        "smoothing_trend": 0.030,
        "damping_trend": 0.045,
    },
    "aaa_seasonal": {
        "smoothing_level": 0.035,
        "smoothing_trend": 0.012,
        "smoothing_seasonal": 0.021,
    },
}

# Independent-reference agreement.
ETS_REFERENCE_AIC_ABS = 0.5
ETS_REFERENCE_LLF_ABS = 0.25  # half the AIC tolerance, same reasoning (AIC = -2llf + 2k)
ETS_SIGMA2_RTOL = 0.10

# Internal arithmetic consistency: AIC/BIC must be the same likelihood and the
# same k. Pure float arithmetic on numbers of magnitude ~1e4 in float64 carries
# relative error ~1e-13; 1e-6 is many orders of magnitude looser than that and
# still catches any real inconsistency (the smallest real one is k off by 1,
# which moves the identity by ln(n) - 2 ~= 6.7).
IC_IDENTITY_ABS_TOL = 1e-6

__all__ = [
    "ETS_PARAM_ABS_TOL",
    "ETS_REFERENCE_AIC_ABS",
    "ETS_REFERENCE_LLF_ABS",
    "ETS_SIGMA2_RTOL",
    "IC_IDENTITY_ABS_TOL",
]
