"""Focused behavior and adversarial tests for nonparametric kernels."""

from __future__ import annotations

import numpy as np
import pytest

from workbench.engine.packs.nonparametric import (
    run_friedman,
    run_kendall,
    run_kruskal_wallis,
    run_mann_whitney,
    run_robust_summary,
    run_spearman,
    run_wilcoxon_signed_rank,
)
from workbench.engine.packs.nonparametric.common import NonparametricPackError


def test_rank_operations_return_scope_and_explicit_estimands() -> None:
    results = [
        run_mann_whitney([1, 2, 3], [4, 5, 6]),
        run_wilcoxon_signed_rank([2, 4, 6], [1, 3, 5]),
        run_kruskal_wallis({"a": [1, 2, 3], "b": [4, 5, 6]}),
        run_friedman([[1, 2, 3], [2, 3, 4], [3, 4, 5]]),
        run_spearman([1, 2, 3, 4], [2, 4, 1, 8]),
        run_kendall([1, 2, 3, 4], [2, 4, 1, 8]),
        run_robust_summary([1, 2, 3, 4, 100]),
    ]

    assert all(item["status"] == "completed" for item in results)
    assert all(set(item["result"]["scope"]) == {
        "estimand", "input_semantics", "assumptions", "limitations", "not_claimed", "unsupported_extensions"
    } for item in results)
    assert "mean" not in results[0]["result"]["scope"]["estimand"]


def test_mann_whitney_permutation_is_reproducible_and_bounded() -> None:
    first = run_mann_whitney([1, 2, 3, 4], [5, 6, 7, 8], method="permutation", n_resamples=199, seed=17)
    second = run_mann_whitney([1, 2, 3, 4], [5, 6, 7, 8], method="permutation", n_resamples=199, seed=17)

    assert first == second
    assert first["result"]["inference"]["method"] == "permutation_plus_one"
    assert 1 / 200 <= first["result"]["p_value"] <= 1.0


@pytest.mark.parametrize(
    "call",
    [
        lambda: run_mann_whitney([1, np.nan], [2, 3]),
        lambda: run_kruskal_wallis({"a": [1, 2], "b": [3, np.inf]}),
        lambda: run_spearman([1, 1, 1], [2, 3, 4]),
        lambda: run_wilcoxon_signed_rank([1, 2], [1, 2], method="exact"),
        lambda: run_mann_whitney([1, 1], [2, 2], method="exact"),
    ],
)
def test_invalid_or_ambiguous_policies_fail_closed(call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NonparametricPackError):
        call()


def test_missing_policy_is_explicit_not_implicit() -> None:
    with pytest.raises(NonparametricPackError):
        run_mann_whitney([1, np.nan, 3], [2, 4, 5])

    result = run_mann_whitney(
        [1, np.nan, 3], [2, 4, 5], missing_policy="complete_case_v1"
    )
    assert result["n_observations"] == 5


def test_robust_summary_is_descriptive_and_not_a_model_estimate() -> None:
    output = run_robust_summary([1, 2, 3, 4, 100], trim_fraction=0.2, winsor_fraction=0.2)

    assert output["result"]["summary"]["median"] == 3.0
    assert output["result"]["scope"]["not_claimed"]
    assert output["result"]["method"] == "robust_descriptive_summary"
