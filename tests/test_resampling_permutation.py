from __future__ import annotations

import json

import numpy as np
import pytest

from workbench.engine.packs.resampling.common import ResamplingPackError
from workbench.engine.packs.resampling.permutation import run_permutation


def test_exact_difference_in_means_matches_direct_enumeration() -> None:
    result = run_permutation(
        [1.0, 2.0],
        [3.0, 4.0],
        statistic_id="difference_in_means",
        exact=True,
    )

    payload = result["result"]
    assert result["operation_id"] == "resampling.permutation"
    assert result["status"] == "completed"
    assert payload["method"] == "exact"
    assert payload["statistic_id"] == "difference_in_means"
    assert payload["p_value_semantics"] == "exact_inclusive_extreme_over_all_allocations"
    assert payload["observed_statistic"] == pytest.approx(-2.0)
    assert payload["n_resamples"] == 6
    assert payload["successful_resamples"] == 6
    assert payload["extreme_count"] == 2
    assert payload["p_value"] == pytest.approx(2.0 / 6.0)
    assert payload["null_mean"] == pytest.approx(0.0)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("alternative", "expected"),
    [("greater", 1.0), ("less", 1.0 / 6.0), ("two-sided", 2.0 / 6.0)],
)
def test_exact_alternative_semantics_are_explicit(alternative: str, expected: float) -> None:
    result = run_permutation(
        [1.0, 2.0],
        [3.0, 4.0],
        exact=True,
        alternative=alternative,
    )
    assert result["result"]["p_value"] == pytest.approx(expected)
    assert result["result"]["alternative"] == alternative


def test_monte_carlo_is_deterministic_and_uses_plus_one_correction() -> None:
    first = run_permutation(
        np.arange(6.0),
        np.arange(6.0, 12.0),
        n_resamples=300,
        seed=19,
        alternative="greater",
    )
    second = run_permutation(
        np.arange(6.0),
        np.arange(6.0, 12.0),
        n_resamples=300,
        seed=19,
        alternative="greater",
    )
    assert first == second
    assert first["result"]["method"] == "monte_carlo"
    assert first["result"]["p_value_semantics"] == "monte_carlo_plus_one"
    assert first["result"]["p_value"] > 0.0
    assert first["result"]["p_value"] <= 1.0


def test_exact_state_space_cap_fails_closed() -> None:
    with pytest.raises(ResamplingPackError, match="RESAMPLING_EXACT_STATE_SPACE_EXCEEDED"):
        run_permutation([float(i) for i in range(8)], [float(i) for i in range(8)], exact=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"statistic_id": "correlation"},
        {"alternative": "not-a-policy"},
        {"n_resamples": 1},
    ],
)
def test_permutation_rejects_undeclared_options(kwargs: dict[str, object]) -> None:
    with pytest.raises(ResamplingPackError):
        run_permutation([1.0, 2.0], [3.0, 4.0], **kwargs)
