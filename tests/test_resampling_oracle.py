from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from workbench.contracts.model.replicate_combine import ReplicatePlan
from workbench.engine.replicate_combine import ReplicateEvidence
from workbench.engine.packs.resampling.bootstrap import _BootstrapCombiner
from workbench.engine.packs.resampling.permutation import run_permutation


def _run_r(script: str) -> list[float]:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript is required for the external Oracle")
    output = subprocess.run(
        ["Rscript", "--vanilla", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return [float(item) for item in output.split(",")]


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is unavailable")
def test_bootstrap_combiner_matches_base_r_quantile_and_se_oracle() -> None:
    bootstrap_statistics = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 8.0])
    observed = 3.5
    combiner = _BootstrapCombiner(
        values=np.array([1.0, 2.0, 4.0, 8.0]),
        statistic_id="mean",
        observed=observed,
        confidence_level=0.8,
        interval_method="percentile",
    )
    plan = ReplicatePlan(
        kind="bootstrap",
        requested_replicates=len(bootstrap_statistics),
        seed=11,
        strategy_id="oracle.bootstrap.strategy",
        adapter_id="oracle.bootstrap.adapter",
        combiner_id="distribution_ci",
        max_failures=0,
        max_evidence_scalars=len(bootstrap_statistics),
    )
    evidence = tuple(
        ReplicateEvidence(scalars={"statistic": float(value)})
        for value in bootstrap_statistics
    )
    result = combiner.combine(evidence, plan=plan, batch=None)

    oracle = _run_r(
        "options(digits=17); x <- c(1,2,3,4,5,8); "
        "q <- quantile(x, c(.1,.9), type=7, names=FALSE); "
        "cat(mean(x), sd(x), q[1], q[2], sep=',')"
    )
    assert result["standard_error"] == pytest.approx(oracle[1], abs=1e-14)
    assert result["bias"] == pytest.approx(oracle[0] - observed, abs=1e-14)
    assert result["confidence_interval"] == pytest.approx(oracle[2:4], abs=1e-14)


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript is unavailable")
def test_exact_permutation_matches_base_r_combinations_oracle() -> None:
    result = run_permutation([1.0, 2.0], [3.0, 4.0], exact=True)
    oracle = _run_r(
        "options(digits=17); left <- c(1,2); right <- c(3,4); pooled <- c(left,right); "
        "s <- combn(seq_along(pooled), length(left), function(i) "
        "mean(pooled[i]) - mean(pooled[-i])); obs <- mean(left)-mean(right); "
        "cat(obs, mean(s), sd(s), sum(abs(s) >= abs(obs))/length(s), sep=',')"
    )
    payload = result["result"]
    assert payload["observed_statistic"] == pytest.approx(oracle[0], abs=1e-14)
    assert payload["null_mean"] == pytest.approx(oracle[1], abs=1e-14)
    assert payload["null_standard_error"] == pytest.approx(oracle[2], abs=1e-14)
    assert payload["p_value"] == pytest.approx(oracle[3], abs=1e-14)
