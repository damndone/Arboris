from __future__ import annotations

import json

import numpy as np
import pytest

from workbench.engine.packs.resampling.bootstrap import run_bootstrap
from workbench.engine.packs.resampling.common import ResamplingPackError


def test_bootstrap_mean_is_deterministic_and_reports_percentile_semantics() -> None:
    values = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    first = run_bootstrap(
        values,
        statistic_id="mean",
        n_resamples=400,
        seed=17,
        confidence_level=0.9,
        interval_method="percentile",
    )
    second = run_bootstrap(
        values,
        statistic_id="mean",
        n_resamples=400,
        seed=17,
        confidence_level=0.9,
        interval_method="percentile",
    )

    assert first == second
    payload = first["result"]
    assert first["operation_id"] == "resampling.bootstrap"
    assert first["status"] == "completed"
    assert payload["estimate"] == pytest.approx(float(np.mean(values)))
    assert payload["n_resamples"] == 400
    assert payload["successful_resamples"] == 400
    assert payload["interval_semantics"] == "bootstrap_percentile_quantile_type_7"
    assert 0.0 < payload["confidence_interval"][0] < payload["confidence_interval"][1]
    json.dumps(first, allow_nan=False)


def test_bootstrap_basic_and_bca_are_explicitly_distinct_methods() -> None:
    values = [1.0, 2.0, 3.0, 9.0, 12.0, 20.0]
    basic = run_bootstrap(
        values,
        n_resamples=500,
        seed=9,
        interval_method="basic",
    )
    bca = run_bootstrap(
        values,
        n_resamples=500,
        seed=9,
        interval_method="bca",
    )

    assert basic["result"]["interval_method"] == "basic"
    assert basic["result"]["interval_semantics"] == "bootstrap_basic_reflection"
    assert bca["result"]["interval_method"] == "bca"
    assert bca["result"]["interval_semantics"] == "bootstrap_bca_jackknife"
    assert bca["result"]["bca"]["jackknife_count"] == len(values)
    assert bca["result"]["confidence_interval"] != basic["result"]["confidence_interval"]


def test_bootstrap_restores_global_numpy_rng_and_never_publishes_replicates() -> None:
    np.random.seed(1234)
    before = np.random.get_state()
    result = run_bootstrap([1.0, 2.0, 3.0, 5.0], n_resamples=200, seed=3)
    after = np.random.get_state()

    assert after[0] == before[0]
    assert np.array_equal(after[1], before[1])
    assert after[2:] == before[2:]
    serialized = json.dumps(result, allow_nan=False)
    for forbidden in ("replicate_values", "distribution_values", "raw_data"):
        assert forbidden not in serialized


def test_bca_degeneracy_is_rejected_without_percentile_fallback() -> None:
    with pytest.raises(ResamplingPackError, match="RESAMPLING_DEGENERATE_INTERVAL"):
        run_bootstrap(
            [1.0, 1.0, 1.0, 1.0],
            n_resamples=200,
            seed=4,
            interval_method="bca",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"statistic_id": "sum"},
        {"interval_method": "studentized"},
        {"confidence_level": 1.0},
        {"n_resamples": 1},
    ],
)
def test_bootstrap_rejects_undeclared_or_unsafe_options(kwargs: dict[str, object]) -> None:
    with pytest.raises(ResamplingPackError):
        run_bootstrap([1.0, 2.0, 3.0], **kwargs)


@pytest.mark.parametrize(
    "values",
    [[1.0], [1.0, float("nan")], [True, False], [1.0 + 1.0j, 2.0 + 0.0j], "1,2,3"],
)
def test_bootstrap_rejects_invalid_input(values: object) -> None:
    with pytest.raises(ResamplingPackError):
        run_bootstrap(values, n_resamples=10)
