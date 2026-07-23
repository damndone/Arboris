"""Re-runnable Monte-Carlo calibration behind ``tolerances.py``.

This is *not* a test. It regenerates the table quoted in ``tolerances.py`` so a
reviewer can verify the tolerances were measured rather than chosen.

Usage (from the repository root of this worktree)::

    LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \\
      .venv/bin/python tests/fixtures/evaluation/v181/calibrate_tolerances.py 40

It fits with ``statsmodels`` ``ETSModel`` directly and never imports the model
pack under evaluation.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.fixtures.evaluation.v181 import ets_known_truth as kt  # noqa: E402


def _fit(series: np.ndarray, spec: dict[str, object]):
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    model = ETSModel(
        np.asarray(series, dtype=float),
        error=spec["error"],
        trend=spec["trend"],
        seasonal=spec["seasonal"],
        seasonal_periods=spec["seasonal_periods"],
        damped_trend=spec["damped_trend"],
    )
    return model.fit(disp=False)


def main(reps: int) -> None:
    warnings.filterwarnings("ignore")
    report: dict[str, object] = {}
    for factory in kt.ALL_ORACLES:
        base = factory()
        deviations: dict[str, list[float]] = {name: [] for name in base.truth}
        started = time.time()
        for rep in range(reps):
            series = kt._simulate(
                n=base.n,
                seed=base.seed + 1000 * (rep + 1),
                alpha=base.truth["smoothing_level"],
                beta=base.truth.get("smoothing_trend", 0.0),
                gamma=base.truth.get("smoothing_seasonal", 0.0),
                phi=base.truth.get("damping_trend", 1.0),
                sigma=base.sigma,
                level0=base.initial_level,
                trend0=base.initial_trend,
                seasonal0=base.initial_seasonal,
                has_trend=base.spec["trend"] is not None,
                has_seasonal=base.spec["seasonal"] is not None,
            )[0]
            fitted = _fit(series, base.spec)
            values = dict(zip(fitted.param_names, fitted.params))
            for name in deviations:
                deviations[name].append(abs(values[name] - base.truth[name]))
        report[base.name] = {
            "canonical": base.canonical,
            "n": base.n,
            "reps": reps,
            "seconds": round(time.time() - started, 1),
            "max_abs_dev": {k: float(np.max(v)) for k, v in deviations.items()},
            "mean_abs_dev": {k: float(np.mean(v)) for k, v in deviations.items()},
        }
        print(base.name, json.dumps(report[base.name]["max_abs_dev"]), flush=True)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
