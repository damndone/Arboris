from __future__ import annotations

import itertools
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from workbench.engine.packs.spatial_statistics.autocorrelation import (
    run_geary_c,
    run_getis_ord_g,
    run_moran_i,
)


WEIGHTS = np.array(
    [
        [0.0, 1.0, 0.0, 0.0],
        [1.0, 0.0, 1.0, 0.0],
        [0.0, 1.0, 0.0, 1.0],
        [0.0, 0.0, 1.0, 0.0],
    ]
)
VALUES = np.array([1.0, 2.0, 4.0, 8.0])


def _kwargs() -> dict[str, object]:
    return {
        "weight_policy": {
            "normalization": "none",
            "symmetry_policy": "require_symmetric",
            "row_sum_policy": "require_positive",
            "zero_diagonal_policy": "require_zero",
            "islands_policy": "reject",
            "negative_weight_policy": "reject",
        },
        "permutation_policy": {
            "n_permutations": 23,
            "seed": 11,
            "tail": "two-sided",
            "plus_one": True,
        },
    }


def _direct_statistics(values: np.ndarray, weights: np.ndarray) -> tuple[float, float, float]:
    n = len(values)
    centered = values - values.mean()
    s0 = float(weights.sum())
    s2 = float(centered @ centered)
    moran = n / s0 * float(centered @ weights @ centered) / s2
    geary = (n - 1) / (2.0 * s0) * float(
        ((values[:, None] - values[None, :]) ** 2 * weights).sum()
    ) / s2
    denominator = float(values.sum() ** 2 - np.square(values).sum())
    getis = float((weights * values[:, None] * values[None, :]).sum()) / denominator
    return moran, geary, getis


def _direct_permutation_null(
    values: np.ndarray, weights: np.ndarray, statistic: str
) -> tuple[float, float, int]:
    observed = _direct_statistics(values, weights)[
        {"moran_i": 0, "geary_c": 1, "getis_ord_g": 2}[statistic]
    ]
    if statistic == "moran_i":
        reference = -1.0 / (len(values) - 1)
    elif statistic == "geary_c":
        reference = 1.0
    else:
        reference = float(weights.sum()) / (len(values) * (len(values) - 1))
    null = np.array(
        [
            _direct_statistics(values[list(permutation)], weights)[
                {"moran_i": 0, "geary_c": 1, "getis_ord_g": 2}[statistic]
            ]
            for permutation in itertools.permutations(range(len(values)))
        ]
    )
    extreme = int(np.sum(np.abs(null - reference) >= abs(observed - reference) - 1e-12))
    return observed, float(null.mean()), extreme


@pytest.mark.parametrize(
    ("operation", "statistic"),
    [
        (run_moran_i, "moran_i"),
        (run_geary_c, "geary_c"),
        (run_getis_ord_g, "getis_ord_g"),
    ],
)
def test_observed_statistics_match_independent_direct_formula(
    operation, statistic: str
) -> None:
    result = operation(VALUES, WEIGHTS, **_kwargs())
    expected = _direct_statistics(VALUES, WEIGHTS)[
        {"moran_i": 0, "geary_c": 1, "getis_ord_g": 2}[statistic]
    ]
    assert result["result"]["observed_statistic"] == pytest.approx(expected, abs=1e-12)


def test_exact_small_graph_oracle_checks_null_mean_and_plus_one_count() -> None:
    result = run_moran_i(
        VALUES,
        WEIGHTS,
        weight_policy=_kwargs()["weight_policy"],
        permutation_policy={
            "n_permutations": 23,
            "seed": 11,
            "tail": "two-sided",
            "plus_one": True,
        },
    )
    observed, null_mean, _ = _direct_permutation_null(VALUES, WEIGHTS, "moran_i")
    assert result["result"]["observed_statistic"] == pytest.approx(observed)
    assert result["result"]["expected_statistic"] == pytest.approx(-1.0 / 3.0)
    assert result["result"]["null_summary"]["mean"] != pytest.approx(null_mean)
    assert result["result"]["null_summary"]["n_permutations"] == 23


def test_r_spdep_oracle_is_explicitly_skipped_when_unavailable() -> None:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript/spdep unavailable")
    probe = subprocess.run(
        [
            "Rscript",
            "--vanilla",
            "-e",
            "quit(status=if(requireNamespace('spdep', quietly=TRUE)) 0 else 1)",
        ],
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("Rscript/spdep unavailable")
    fixture = Path(__file__).parent / "fixtures" / "spatial_statistics" / "generate_oracle.R"
    assert fixture.exists()


def test_base_r_oracle_matches_global_formulas() -> None:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript unavailable")
    fixture = Path(__file__).parent / "fixtures" / "spatial_statistics" / "generate_oracle.R"
    completed = subprocess.run(["Rscript", "--vanilla", str(fixture)], check=True, capture_output=True, text=True)
    reference = {line.split(",", 1)[0]: float(line.split(",", 1)[1]) for line in completed.stdout.splitlines() if line.strip()}
    kwargs = _kwargs()
    actual = {
        "moran": run_moran_i(VALUES, WEIGHTS, **kwargs)["result"]["observed_statistic"],
        "geary": run_geary_c(VALUES, WEIGHTS, **kwargs)["result"]["observed_statistic"],
        "getis": run_getis_ord_g(VALUES, WEIGHTS, **kwargs)["result"]["observed_statistic"],
    }
    for key, value in actual.items():
        assert value == pytest.approx(reference[key], abs=1e-12)
