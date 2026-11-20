import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench import native_time_series as common
from workbench.native_build import default_output, manifest_path
from workbench.native_markov import run_markov_switching
from workbench.native_research import compute_native_research

ROOT = Path(__file__).resolve().parents[1]


def regime_frame():
    seed, regime = 173, 0

    def uniform():
        nonlocal seed
        seed = 16807 * seed % 2147483647
        return seed / 2147483647

    y = []
    for _ in range(360):
        if uniform() > [0.86, 0.79][regime]:
            regime = 1 - regime
        y.append([-2.2, 2.9][regime] + 0.72 * (sum(uniform() for _ in range(12)) - 6))
    for position in [0, 39, 40, 71, 181, 358, 359]:
        y[position] = np.nan
    return pd.DataFrame({"t": pd.date_range("1990-01-31", periods=360, freq=pd.offsets.MonthEnd()), "y": y})


@pytest.fixture
def regular():
    if not manifest_path(default_output(ROOT / "native/time_series")).is_file():
        pytest.skip("build with native/time_series/build.py to exercise Markov switching")
    return regime_frame()


def test_monthly_holdout_has_fixed_origin_and_no_future_observation_leakage(regular):
    opts = {"time_col": "t", "outcome": "y", "forecast_periods": 4, "holdout_periods": 8}
    base = run_markov_switching(regular, **opts)
    changed = regular.copy()
    changed.loc[352:, "y"] += 0.2
    after = run_markov_switching(changed, **opts)
    assert base["holdout"]["forecast"] == after["holdout"]["forecast"]
    assert base["holdout"]["origin_time"] == regular["t"].iloc[351].isoformat()
    assert base["holdout"]["forecast"]["time"] == [time.isoformat() for time in regular["t"].iloc[-8:]]
    assert base["holdout"]["n_observed"] == 6
    assert base["forecast"]["time"][0] == (regular["t"].iloc[-1] + pd.offsets.MonthEnd()).isoformat()
    assert base["fit"]["log_likelihood"] != after["fit"]["log_likelihood"]


def test_interval_inverts_the_mixture_and_trace_stays_local(regular):
    result = run_markov_switching(regular, time_col="t", outcome="y", forecast_periods=4)
    fit, forecast = result["fit"], result["forecast"]
    mu = [fit["mean_low"], fit["mean_high"]]
    deviation = math.sqrt(fit["shared_variance"])
    for low, high, w0, w1 in zip(forecast["lower"], forecast["upper"],
                                  forecast["probability_low"], forecast["probability_high"], strict=True):
        for value, sign in [(low, -1), (high, 1)]:
            probability = 0.5 * sum(w * math.erfc(sign * (value - m) / (deviation * math.sqrt(2)))
                                    for w, m in zip([w0, w1], mu, strict=True))
            assert probability == pytest.approx(0.025, abs=1e-12)
    np.testing.assert_allclose(
        forecast["probability_low"][0],
        fit["last_filtered_low"] * fit["p_low_low"] + fit["last_filtered_high"] * (1 - fit["p_high_high"]),
        atol=1e-14, rtol=0,
    )
    public, local = compute_native_research(regular, {
        "operation_id": "time_series.markov_switching", "column_bindings": {"time_col": "t", "outcome": "y"},
        "options": {"forecast_periods": 4},
    })
    assert "trace" not in public["fit"] and "time" not in public["forecast"]
    assert len(local["trace"]["filtered_low"]) == 360
    assert local["trace"]["log_likelihood"][-1] == 0.0
    assert json.dumps(public, allow_nan=False)


def test_irregular_clock_fails_before_model_loading(regular, monkeypatch):
    broken = regular.drop(index=10).reset_index(drop=True)
    monkeypatch.setattr(common, "_loaded", lambda: pytest.fail("irregular grid reached native loader"))
    with pytest.raises(common.TimeSeriesPackError, match="TIME_SERIES_IRREGULAR_TIME"):
        run_markov_switching(broken, time_col="t", outcome="y")
