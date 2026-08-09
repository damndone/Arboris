from __future__ import annotations

import json

import numpy as np
import pytest

from workbench.engine.packs.spatial_statistics.common import SpatialStatisticsPackError
from workbench.engine.packs.spatial_statistics.autocorrelation import (
    run_geary_c,
    run_getis_ord_g,
    run_moran_i,
)


LINE_WEIGHTS = np.array(
    [
        [0.0, 1.0, 0.0, 0.0],
        [1.0, 0.0, 1.0, 0.0],
        [0.0, 1.0, 0.0, 1.0],
        [0.0, 0.0, 1.0, 0.0],
    ]
)
VALUES = np.array([1.0, 2.0, 4.0, 8.0])


def _policy(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "normalization": "none",
        "symmetry_policy": "require_symmetric",
        "row_sum_policy": "require_positive",
        "zero_diagonal_policy": "require_zero",
        "islands_policy": "reject",
        "negative_weight_policy": "reject",
    }
    value.update(overrides)
    return value


def _permutation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "n_permutations": 199,
        "seed": 17,
        "tail": "two-sided",
        "plus_one": True,
    }
    value.update(overrides)
    return value


def _kwargs(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "weight_policy": _policy(),
        "permutation_policy": _permutation(),
    }
    value.update(overrides)
    return value


def test_global_statistics_return_observed_and_bounded_permutation_evidence() -> None:
    results = [
        run_moran_i(VALUES, LINE_WEIGHTS, **_kwargs()),
        run_geary_c(VALUES, LINE_WEIGHTS, **_kwargs()),
        run_getis_ord_g(VALUES, LINE_WEIGHTS, **_kwargs()),
    ]

    assert [item["operation_id"] for item in results] == [
        "spatial.moran_i",
        "spatial.geary_c",
        "spatial.getis_ord_g",
    ]
    for envelope in results:
        assert envelope["status"] == "completed"
        payload = envelope["result"]
        assert np.isfinite(payload["observed_statistic"])
        assert payload["null_summary"]["successful_permutations"] == 199
        assert payload["permutation"]["p_value_semantics"] == "monte_carlo_plus_one"
        assert payload["scope"]["estimand"] == "global spatial association statistic"
        assert any("local" in item for item in payload["scope"]["not_claimed"])
        assert all("rows" not in key and "matrix" not in key for key in payload)
        json.dumps(envelope, allow_nan=False)


def test_moran_i_matches_direct_global_formula() -> None:
    result = run_moran_i(
        VALUES,
        LINE_WEIGHTS,
        **_kwargs(permutation_policy=_permutation(n_permutations=19)),
    )
    centered = VALUES - VALUES.mean()
    expected = len(VALUES) / LINE_WEIGHTS.sum() * (
        centered @ LINE_WEIGHTS @ centered
    ) / (centered @ centered)
    assert result["result"]["observed_statistic"] == pytest.approx(expected)
    assert result["result"]["expected_statistic"] == pytest.approx(-1.0 / 3.0)


def test_same_seed_is_reproducible_and_does_not_touch_legacy_global_rng() -> None:
    np.random.seed(2026)
    before = np.random.get_state()
    first = run_moran_i(VALUES, LINE_WEIGHTS, **_kwargs())
    after = np.random.get_state()
    second = run_moran_i(VALUES, LINE_WEIGHTS, **_kwargs())

    assert first == second
    assert before[0] == after[0]
    assert np.array_equal(before[1], after[1])
    assert before[2:] == after[2:]


def test_matrix_and_explicit_edge_graph_have_the_same_result() -> None:
    edges = [
        (0, 1, 1.0),
        (1, 0, 1.0),
        (1, 2, 1.0),
        (2, 1, 1.0),
        (2, 3, 1.0),
        (3, 2, 1.0),
    ]
    matrix_result = run_geary_c(VALUES, LINE_WEIGHTS, **_kwargs())
    edge_result = run_geary_c(
        VALUES,
        {"kind": "edges", "n_nodes": 4, "edges": edges},
        **_kwargs(),
    )
    assert edge_result["result"]["observed_statistic"] == pytest.approx(
        matrix_result["result"]["observed_statistic"]
    )
    assert edge_result["result"]["permutation"] == matrix_result["result"]["permutation"]


@pytest.mark.parametrize(
    ("weights", "policy", "reason"),
    [
        (
            np.array([[0.0, 1.0], [0.0, 0.0]]),
            _policy(symmetry_policy="require_symmetric"),
            "SPATIAL_ASYMMETRIC_WEIGHTS",
        ),
        (
            np.array([[1.0, 1.0], [1.0, 0.0]]),
            _policy(zero_diagonal_policy="require_zero"),
            "SPATIAL_NONZERO_DIAGONAL",
        ),
        (
            np.array([[0.0, -1.0], [-1.0, 0.0]]),
            _policy(negative_weight_policy="reject"),
            "SPATIAL_NEGATIVE_WEIGHT",
        ),
    ],
)
def test_weight_semantics_are_rejected_with_stable_reason_codes(
    weights: object, policy: dict[str, object], reason: str
) -> None:
    with pytest.raises(SpatialStatisticsPackError, match=reason):
        run_moran_i(VALUES[:2], weights, **_kwargs(weight_policy=policy))


def test_islands_are_never_silently_dropped_and_keep_zero_is_explicit() -> None:
    weights = np.array(
        [
            [0.0, 1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    with pytest.raises(SpatialStatisticsPackError, match="SPATIAL_ISLANDS_PRESENT"):
        run_moran_i(
            VALUES,
            weights,
            **_kwargs(
                weight_policy=_policy(
                    islands_policy="reject", row_sum_policy="allow_zero_islands"
                )
            ),
        )

    result = run_moran_i(
        VALUES,
        weights,
        **_kwargs(
            weight_policy=_policy(
                islands_policy="keep_zero", row_sum_policy="allow_zero_islands"
            )
        ),
    )
    assert result["result"]["weight_summary"]["n_nodes"] == 4
    assert result["result"]["weight_summary"]["n_islands"] == 2


def test_row_standardization_is_explicit_and_disconnected_components_are_reported() -> None:
    weights = np.array(
        [
            [0.0, 2.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 3.0],
            [0.0, 0.0, 4.0, 0.0],
        ]
    )
    result = run_getis_ord_g(
        VALUES,
        weights,
        **_kwargs(
            weight_policy=_policy(
                normalization="row_standardize", symmetry_policy="allow_asymmetric"
            )
        ),
    )
    summary = result["result"]["weight_summary"]
    assert summary["normalization"] == "row_standardize"
    assert summary["n_components"] == 2
    assert summary["n_islands"] == 0


def test_plus_one_semantics_are_visible_and_zero_p_is_not_returned_when_enabled() -> None:
    result = run_moran_i(
        VALUES,
        LINE_WEIGHTS,
        **_kwargs(
            permutation_policy=_permutation(
                n_permutations=1, seed=3, tail="greater", plus_one=True
            )
        ),
    )
    permutation = result["result"]["permutation"]
    assert permutation["p_value_semantics"] == "monte_carlo_plus_one"
    assert permutation["p_value"] == pytest.approx(1.0 / 2.0)
    assert permutation["p_value"] > 0.0


@pytest.mark.parametrize(
    "operation",
    [run_moran_i, run_geary_c, run_getis_ord_g],
)
def test_nonfinite_vectors_and_unsupported_local_operations_fail_closed(
    operation,
) -> None:
    with pytest.raises(SpatialStatisticsPackError, match="SPATIAL_NONFINITE_VALUE"):
        operation([1.0, float("inf"), 3.0, 4.0], LINE_WEIGHTS, **_kwargs())
