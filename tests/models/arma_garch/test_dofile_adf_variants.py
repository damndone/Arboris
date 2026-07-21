"""Do-file parity gap 1: ADF specification variants.

The reference runs `dfuller y, lags(0)` / `lags(5)` and, on the level series,
`dfuller lvix, lags(5) drift` and `lags(5) trend`. One ADF specification is not
enough evidence; the variants must be reported side by side.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from workbench.engine.packs.arma_garch.transforms import build_transform_profiles
from workbench.engine.packs.arma_garch.input import (
    PARSED_TIME_COLUMN,
    PARSED_VALUE_COLUMN,
    ROW_ID_COLUMN,
)


def _view(n: int = 300, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    level = 20.0 + np.cumsum(rng.normal(scale=0.4, size=n))
    level = np.abs(level) + 1.0
    return pd.DataFrame(
        {
            PARSED_TIME_COLUMN: pd.bdate_range("2020-01-01", periods=n),
            PARSED_VALUE_COLUMN: level,
            ROW_ID_COLUMN: [f"source-row:{i:010d}" for i in range(n)],
        }
    )


def test_each_transform_reports_adf_variants() -> None:
    profiles = build_transform_profiles(_view())
    payload = profiles["level"].to_dict()

    # Legacy scalars are untouched (0-drift for existing readers).
    assert "adf_statistic" in payload and "adf_p_value" in payload

    variants = payload["adf_variants"]
    assert isinstance(variants, list) and variants

    specs = {(item["regression"], item["lags"]) for item in variants}
    # constant-only, drift (constant), and trend, at auto and a fixed lag.
    assert ("c", None) in specs
    assert ("ct", None) in specs
    assert any(regression == "n" for regression, _ in specs)
    assert any(lags == 5 for _, lags in specs)

    for item in variants:
        assert item["status"] in {"ok", "unavailable"}
        if item["status"] == "ok":
            assert isinstance(item["statistic"], float)
            assert 0.0 <= item["p_value"] <= 1.0
            assert item["nobs"] > 0


def test_adf_variants_degrade_without_raising_on_a_short_series() -> None:
    profiles = build_transform_profiles(_view(n=9))
    variants = profiles["level"].to_dict()["adf_variants"]
    assert all(item["status"] in {"ok", "unavailable"} for item in variants)


def test_trend_variant_differs_from_the_constant_variant_on_a_trending_series() -> None:
    n = 300
    trending = pd.DataFrame(
        {
            PARSED_TIME_COLUMN: pd.bdate_range("2020-01-01", periods=n),
            PARSED_VALUE_COLUMN: 10.0 + 0.05 * np.arange(n),
            ROW_ID_COLUMN: [f"source-row:{i:010d}" for i in range(n)],
        }
    )
    variants = build_transform_profiles(trending)["level"].to_dict()["adf_variants"]
    by_spec = {(v["regression"], v["lags"]): v for v in variants}
    constant = by_spec[("c", None)]
    trend = by_spec[("ct", None)]
    if constant["status"] == "ok" and trend["status"] == "ok":
        assert constant["statistic"] != trend["statistic"]
