"""The robust IV fit's Wooldridge tests: linearmodels' bits, without its auxiliary _OLS models.

2026-11-09 footprint diagnostics: on the 1M-row robust IV reference path the peak sat first in
fitted.wooldridge_overid (its _OLS(ones, test_functions) held about 330 MiB; +461 MiB traced
against +122 MiB on plain arrays), then in fitted.wooldridge_regression (+604 against +221 MiB).
The first lean exogeneity test differed in the last bits on 360 of 1,296 designs: its augmented
design was column-major where _OLS's copy is row-major.
"""
from __future__ import annotations

import itertools
import struct

import numpy as np
import pandas as pd
import pytest
from linearmodels.iv import IV2SLS

from workbench.econometrics import panel_iv
from workbench.econometrics.iv_tests import wooldridge_overid, wooldridge_regression


def _bits(value) -> str:
    return struct.pack("<d", float(value)).hex()


def _data(seed: int, n: int, nexog: int, nendog: int, extra: int):
    rng = np.random.default_rng(seed)
    exog = pd.DataFrame({"Intercept": np.ones(n), **{f"w{i}": rng.normal(size=n) for i in range(nexog - 1)}})
    z = rng.normal(size=(n, nendog + extra))
    d = z[:, :nendog] @ rng.normal(size=(nendog, nendog)) + 0.3 * z[:, nendog:].sum(1, keepdims=True)
    d = d + rng.normal(size=(n, nendog))
    y = pd.Series(d.sum(1) + rng.normal(size=n), name="y")
    return (y, exog, pd.DataFrame(d, columns=[f"d{i}" for i in range(nendog)]),
            pd.DataFrame(z, columns=[f"z{i}" for i in range(nendog + extra)]))


@pytest.mark.parametrize("seed,n,nexog,nendog,extra,covariance", [
    case for case in itertools.product((1, 2), (60, 3000), (1, 3), (1, 2), (1, 3), ("robust", "unadjusted", "kernel"))])
def test_the_statistic_equals_linearmodels_bit_for_bit(seed, n, nexog, nendog, extra, covariance):
    library = IV2SLS(*_data(seed, n, nexog, nendog, extra)).fit(cov_type=covariance).wooldridge_overid
    lean = wooldridge_overid(IV2SLS(*_data(seed, n, nexog, nendog, extra)).fit(cov_type=covariance))
    assert (_bits(lean.stat), _bits(lean.pval), lean.df, lean.dist_name, str(lean.null), str(lean)) == (
        _bits(library.stat), _bits(library.pval), library.df, library.dist_name, str(library.null), str(library))


@pytest.mark.parametrize("seed,n,nexog,nendog,extra,covariance", [
    case for case in itertools.product((1, 2), (50, 3000), (1, 3), (1, 2), (0, 2),
                                       ("robust", "heteroskedastic", "unadjusted", "kernel"))])
def test_the_exogeneity_statistic_equals_linearmodels_bit_for_bit(seed, n, nexog, nendog, extra, covariance):
    library = IV2SLS(*_data(seed, n, nexog, nendog, extra)).fit(cov_type=covariance).wooldridge_regression
    lean = wooldridge_regression(IV2SLS(*_data(seed, n, nexog, nendog, extra)).fit(cov_type=covariance))
    assert (_bits(lean.stat), _bits(lean.pval), lean.df, str(lean)) == (
        _bits(library.stat), _bits(library.pval), library.df, str(library))


def test_an_exactly_identified_fit_is_not_overidentified():
    fitted = IV2SLS(*_data(3, 200, 2, 1, 0)).fit(cov_type="robust")
    assert type(wooldridge_overid(fitted)) is type(fitted.wooldridge_overid)


def test_a_robust_reference_fit_never_builds_the_ols_model(monkeypatch):
    from linearmodels.iv import model as iv_model

    y, exog, endog, instruments = _data(4, 500, 2, 1, 2)
    frame = pd.concat([y, exog.drop(columns="Intercept"), endog, instruments], axis=1)
    reference = IV2SLS(y, exog, endog, instruments).fit(cov_type="robust")
    expected = (reference.wooldridge_overid.stat, reference.wooldridge_regression.stat)
    monkeypatch.setattr(iv_model, "_OLS", lambda *a, **k: (_ for _ in ()).throw(AssertionError("_OLS built")))
    _, fitted = panel_iv.run_iv_2sls(frame, "y", ["w0"], ["d0"], ["z0", "z1", "z2"], "iv_2sls_1", covariance="robust")
    assert (_bits(fitted.wooldridge_overid.stat), _bits(fitted.wooldridge_regression.stat)) == tuple(map(_bits, expected))
