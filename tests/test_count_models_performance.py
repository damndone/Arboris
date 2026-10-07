"""End-to-end NB2 fit budget, with all 100000 observations and 10 predictors."""
from time import perf_counter

import numpy as np
import pandas as pd

from workbench.econometrics.runner import run_negative_binomial


def test_nb2_100000_rows_10_predictors_finishes_in_five_seconds():
    rng = np.random.default_rng(2026100411)
    n, k = 100000, 10
    x = rng.normal(size=(n, k))
    beta = np.linspace(-.15, .2, k)
    mu = np.exp(.3+x@beta)
    y = rng.negative_binomial(2, 2/(2+mu))
    frame = pd.DataFrame(x, columns=[f"x{i}" for i in range(k)])
    frame["y"] = y
    started = perf_counter()
    result, fitted = run_negative_binomial(frame, "y", list(frame.columns[:-1]), "performance")
    elapsed = perf_counter()-started
    print(f"NB2 N={n} K={k}: {elapsed:.6f}s; iterations={result['convergence']['iterations']}; alpha={fitted.params.iloc[-1]:.12g}")
    assert result["nobs"] == n
    assert len(result["coefficients"]) == k+1
    assert result["convergence"]["converged"] is True
    assert elapsed < 5., f"NB2 exceeded full-sample budget: {elapsed:.6f}s"
