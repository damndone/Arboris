"""Independent SciPy Oracle checks for nonparametric kernels."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from workbench.engine.packs.nonparametric import (
    run_friedman,
    run_kendall,
    run_kruskal_wallis,
    run_mann_whitney,
    run_spearman,
    run_wilcoxon_signed_rank,
)


def test_mann_whitney_matches_scipy() -> None:
    x, y = [1, 2, 5, 6], [3, 4, 7, 8]
    reference = stats.mannwhitneyu(x, y, method="asymptotic")
    actual = run_mann_whitney(x, y)
    assert np.isclose(actual["result"]["statistic"], reference.statistic)
    assert np.isclose(actual["result"]["p_value"], reference.pvalue)


def test_wilcoxon_matches_scipy() -> None:
    x, y = [2, 4, 7, 8, 10], [1, 3, 6, 9, 9]
    reference = stats.wilcoxon(x, y, method="asymptotic", correction=True)
    actual = run_wilcoxon_signed_rank(x, y)
    assert np.isclose(actual["result"]["statistic"], reference.statistic)
    assert np.isclose(actual["result"]["p_value"], reference.pvalue)


def test_omnibus_and_correlations_match_scipy() -> None:
    groups = {"a": [1, 2, 5], "b": [3, 4, 7], "c": [6, 8, 9]}
    reference_kw = stats.kruskal(*groups.values())
    actual_kw = run_kruskal_wallis(groups)
    assert np.isclose(actual_kw["result"]["statistic"], reference_kw.statistic)
    assert np.isclose(actual_kw["result"]["p_value"], reference_kw.pvalue)

    matrix = [[1, 2, 3], [2, 4, 5], [3, 5, 8], [4, 7, 9]]
    reference_fr = stats.friedmanchisquare(*np.asarray(matrix).T)
    actual_fr = run_friedman(matrix)
    assert np.isclose(actual_fr["result"]["statistic"], reference_fr.statistic)

    x, y = [1, 2, 3, 4, 5], [5, 1, 4, 2, 3]
    reference_s = stats.spearmanr(x, y)
    reference_k = stats.kendalltau(x, y)
    actual_s = run_spearman(x, y)
    actual_k = run_kendall(x, y)
    assert np.isclose(actual_s["result"]["statistic"], reference_s.statistic)
    assert np.isclose(actual_k["result"]["statistic"], reference_k.statistic)


def test_base_r_oracle_matches_fixed_rank_statistics() -> None:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript unavailable")
    fixture = Path(__file__).parent / "fixtures" / "nonparametric" / "oracle_base_r.R"
    completed = subprocess.run(["Rscript", "--vanilla", str(fixture)], check=True, capture_output=True, text=True)
    reference = {
        line.split(",", 1)[0]: tuple(float(item) for item in line.strip().split(",")[1:])
        for line in completed.stdout.splitlines() if line.strip()
    }
    mw = run_mann_whitney([1, 2, 3, 4], [5, 6, 7, 8], method="exact")["result"]
    ws = run_wilcoxon_signed_rank([2, 5, 9, 14], [1, 3, 6, 10], method="exact")["result"]
    kw = run_kruskal_wallis({"x": [1, 2, 3, 4], "y": [5, 6, 7, 8], "z": [9, 10, 11, 12]})["result"]
    sp = run_spearman([1, 2, 3, 4], [5, 6, 7, 8])["result"]
    kt = run_kendall([1, 2, 3, 4], [5, 6, 7, 8])["result"]
    np.testing.assert_allclose([mw["statistic"], mw["p_value"]], reference["mann_whitney"], rtol=1e-12, atol=1e-12)
    # R reports the positive signed-rank sum (W+), while SciPy's two-sided
    # statistic is min(W+, W-).  The p-value is the shared inferential oracle.
    np.testing.assert_allclose(ws["p_value"], reference["wilcoxon"][1], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose([kw["statistic"], kw["p_value"]], reference["kruskal"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(sp["statistic"], reference["spearman"][0], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(kt["statistic"], reference["kendall"][0], rtol=1e-12, atol=1e-12)
