"""Rank tests with explicit method and missing-data policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

import numpy as np
from scipy import stats

from .common import (
    MAX_PERMUTATION_RESAMPLES,
    MIN_PERMUTATION_RESAMPLES,
    NonparametricPackError,
    alpha_value,
    clean_1d,
    groups_clean,
    matrix_clean,
    paired_clean,
    reject,
    result,
)


def _alternative(value: str) -> str:
    if value not in {"two-sided", "less", "greater"}:
        reject("NONPARAMETRIC_UNSUPPORTED_POLICY", "alternative is not declared")
    return value


def _method(value: str, allowed: set[str]) -> str:
    if value not in allowed:
        reject("NONPARAMETRIC_UNSUPPORTED_POLICY", "inference method is not declared")
    return value


def _u_statistic(x: np.ndarray, y: np.ndarray) -> float:
    pooled = np.concatenate([x, y])
    ranks = stats.rankdata(pooled, method="average")
    return float(np.sum(ranks[: x.size]) - x.size * (x.size + 1) / 2.0)


def _permutation_u(
    x: np.ndarray,
    y: np.ndarray,
    *,
    alternative: str,
    n_resamples: int,
    seed: int | None,
) -> tuple[float, float]:
    if type(n_resamples) is not int or not MIN_PERMUTATION_RESAMPLES <= n_resamples <= MAX_PERMUTATION_RESAMPLES:
        reject("NONPARAMETRIC_INVALID_INPUT", "n_resamples is outside the bounded permutation range")
    if seed is not None and (type(seed) is not int or isinstance(seed, bool) or seed < 0):
        reject("NONPARAMETRIC_INVALID_INPUT", "seed must be a non-negative integer")
    observed = _u_statistic(x, y)
    expected = x.size * y.size / 2.0
    combined = np.concatenate([x, y])
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(n_resamples):
        shuffled = rng.permutation(combined)
        statistic = _u_statistic(shuffled[: x.size], shuffled[x.size :])
        if alternative == "greater":
            is_extreme = statistic >= observed
        elif alternative == "less":
            is_extreme = statistic <= observed
        else:
            is_extreme = abs(statistic - expected) >= abs(observed - expected)
        extreme += int(is_extreme)
    return observed, float((extreme + 1) / (n_resamples + 1))


def run_mann_whitney(
    x: Sequence[float],
    y: Sequence[float],
    *,
    alternative: str = "two-sided",
    method: str = "asymptotic",
    missing_policy: str = "reject",
    n_resamples: int = 999,
    seed: int | None = 0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    alternative = _alternative(alternative)
    method = _method(method, {"asymptotic", "exact", "permutation"})
    left = clean_1d(x, "x", missing_policy=missing_policy)
    right = clean_1d(y, "y", missing_policy=missing_policy)
    if left.size < 2 or right.size < 2:
        reject("NONPARAMETRIC_TOO_FEW_OBSERVATIONS", "each sample needs at least two observations")
    pooled = np.concatenate([left, right])
    ties = np.unique(pooled).size != pooled.size
    if method == "exact" and ties:
        reject("NONPARAMETRIC_EXACT_UNAVAILABLE", "exact Mann-Whitney requires no ties")
    if method == "permutation":
        statistic, p_value = _permutation_u(
            left, right, alternative=alternative, n_resamples=n_resamples, seed=seed
        )
        inference = {"method": "permutation_plus_one", "n_resamples": n_resamples, "seed": seed}
    else:
        outcome = stats.mannwhitneyu(left, right, alternative=alternative, method=method)
        statistic, p_value = float(outcome.statistic), float(outcome.pvalue)
        inference = {"method": method, "continuity_correction": method == "asymptotic"}
    return result(
        operation_id="nonparametric.mann_whitney",
        n_observations=left.size + right.size,
        method="mann_whitney_u",
        estimand="probability that a random x observation ranks above a random y observation",
        input_semantics="two independent finite numeric samples",
        assumptions=["observations are independent within and between samples"],
        limitations=["rank probability is not a mean difference", "ties use an asymptotic correction unless rejected by exact policy"],
        not_claimed=["does not establish a causal effect", "does not identify which mechanism generated a distribution shift"],
        unsupported_extensions=["complex survey rank variance is not included"],
        statistic=statistic,
        p_value=p_value,
        alpha=level,
        alternative=alternative,
        inference=inference,
        sample_sizes={"x": int(left.size), "y": int(right.size)},
        effect_size={"rank_biserial": float(2.0 * statistic / (left.size * right.size) - 1.0)},
    )


def run_wilcoxon_signed_rank(
    x: Sequence[float],
    y: Sequence[float],
    *,
    alternative: str = "two-sided",
    method: str = "asymptotic",
    zero_method: str = "wilcox",
    missing_policy: str = "reject",
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    alternative = _alternative(alternative)
    method = _method(method, {"asymptotic", "exact"})
    if zero_method not in {"wilcox", "pratt", "zsplit"}:
        reject("NONPARAMETRIC_UNSUPPORTED_POLICY", "zero_method is not declared")
    left, right = paired_clean(x, y, missing_policy=missing_policy)
    differences = left - right
    if np.allclose(differences, 0.0):
        reject("NONPARAMETRIC_DEGENERATE_INPUT", "all paired differences are zero")
    nonzero = differences[np.abs(differences) > 0]
    if method == "exact" and (zero_method != "wilcox" or nonzero.size != differences.size or np.unique(np.abs(nonzero)).size != nonzero.size):
        reject("NONPARAMETRIC_EXACT_UNAVAILABLE", "exact Wilcoxon requires no zeros or absolute-value ties")
    outcome = stats.wilcoxon(
        left,
        right,
        alternative=alternative,
        zero_method=zero_method,
        correction=method == "asymptotic",
        method=method,
    )
    ranks = stats.rankdata(np.abs(nonzero), method="average")
    signed_rank = float(np.sum(ranks[nonzero > 0]) - np.sum(ranks[nonzero < 0]))
    denominator = float(np.sum(ranks))
    return result(
        operation_id="nonparametric.wilcoxon_signed_rank",
        n_observations=left.size,
        method="wilcoxon_signed_rank",
        estimand="symmetric paired rank-location evidence for x minus y",
        input_semantics="paired finite numeric samples with explicit zero policy",
        assumptions=["paired differences are independent across blocks", "the signed-rank symmetry assumption is declared for interpretation"],
        limitations=["the signed-rank test is not a paired mean test", "zero and tie handling changes the reference distribution"],
        not_claimed=["does not establish a causal effect", "does not prove symmetry from a non-significant result"],
        unsupported_extensions=["missing-not-at-random repeated-measures inference is not included"],
        statistic=float(outcome.statistic),
        p_value=float(outcome.pvalue),
        alpha=level,
        alternative=alternative,
        inference={"method": method, "zero_method": zero_method},
        sample_size=int(left.size),
        effect_size={"signed_rank_biserial": float(signed_rank / denominator)},
    )


def run_kruskal_wallis(
    groups: Mapping[str, Sequence[float]],
    *,
    method: str = "asymptotic",
    missing_policy: str = "reject",
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    _method(method, {"asymptotic"})
    labels, arrays = groups_clean(groups, missing_policy=missing_policy)
    if len(labels) < 2 or any(array.size < 2 for array in arrays):
        reject("NONPARAMETRIC_TOO_FEW_OBSERVATIONS", "Kruskal-Wallis needs at least two groups of size two")
    outcome = stats.kruskal(*arrays)
    n = sum(array.size for array in arrays)
    raw_epsilon = (float(outcome.statistic) - len(labels) + 1.0) / (n - len(labels))
    return result(
        operation_id="nonparametric.kruskal_wallis",
        n_observations=n,
        method="kruskal_wallis",
        estimand="global rank-distribution difference across independent groups",
        input_semantics="named independent finite numeric groups",
        assumptions=["independent observations", "groups have comparable distribution shape when interpreted as location evidence"],
        limitations=["a significant omnibus result does not identify pairwise differences", "rank evidence is not a mean comparison"],
        not_claimed=["does not establish a causal effect", "does not select a post-hoc procedure automatically"],
        unsupported_extensions=["complex survey rank variance is not included"],
        statistic=float(outcome.statistic),
        p_value=float(outcome.pvalue),
        alpha=level,
        inference={"method": method, "degrees_of_freedom": len(labels) - 1},
        group_labels=labels,
        group_sizes={label: int(array.size) for label, array in zip(labels, arrays)},
        effect_size={"epsilon_squared": float(np.clip(raw_epsilon, 0.0, 1.0)), "raw_epsilon_squared": float(raw_epsilon)},
    )


def run_friedman(
    values: Sequence[Sequence[float]],
    *,
    method: str = "asymptotic",
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    _method(method, {"asymptotic"})
    matrix = matrix_clean(values, "values")
    outcome = stats.friedmanchisquare(*matrix.T)
    n, k = matrix.shape
    return result(
        operation_id="nonparametric.friedman",
        n_observations=int(matrix.size),
        method="friedman",
        estimand="global within-block rank difference across repeated conditions",
        input_semantics="finite matrix with rows as blocks and columns as repeated conditions",
        assumptions=["blocks are independent", "each block contains every declared condition"],
        limitations=["a significant omnibus result does not identify pairwise differences", "missing repeated-measures patterns are not imputed"],
        not_claimed=["does not establish a causal effect", "does not replace a declared repeated-measures model"],
        unsupported_extensions=["unbalanced repeated-measures designs are not included"],
        statistic=float(outcome.statistic),
        p_value=float(outcome.pvalue),
        alpha=level,
        inference={"method": method, "degrees_of_freedom": k - 1},
        shape={"blocks": int(n), "conditions": int(k)},
        effect_size={"kendall_w": float(np.clip(float(outcome.statistic) / (n * (k - 1)), 0.0, 1.0))},
    )


def _correlation_input(x: Sequence[float], y: Sequence[float], missing_policy: str) -> tuple[np.ndarray, np.ndarray]:
    return paired_clean(x, y, missing_policy=missing_policy)


def run_spearman(
    x: Sequence[float],
    y: Sequence[float],
    *,
    missing_policy: str = "reject",
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    left, right = _correlation_input(x, y, missing_policy)
    if left.size < 3 or np.unique(left).size < 2 or np.unique(right).size < 2:
        reject("NONPARAMETRIC_DEGENERATE_INPUT", "Spearman correlation needs variation and at least three pairs")
    outcome = stats.spearmanr(left, right)
    return result(
        operation_id="nonparametric.spearman",
        n_observations=left.size,
        method="spearman",
        estimand="monotone rank association between paired variables",
        input_semantics="paired finite numeric observations",
        assumptions=["pairs are independent for the reference p-value", "association is interpreted as monotone evidence"],
        limitations=["correlation is not causation", "the asymptotic p-value is not a model specification test"],
        not_claimed=["does not establish a causal effect", "does not imply linear association"],
        unsupported_extensions=["clustered or survey correlation variance is not included"],
        statistic=float(outcome.statistic),
        p_value=float(outcome.pvalue),
        alpha=level,
        inference={"method": "asymptotic"},
        sample_size=int(left.size),
        effect_size={"spearman_rho": float(outcome.statistic)},
    )


def run_kendall(
    x: Sequence[float],
    y: Sequence[float],
    *,
    variant: str = "b",
    missing_policy: str = "reject",
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    if variant not in {"b", "c"}:
        reject("NONPARAMETRIC_UNSUPPORTED_POLICY", "Kendall variant must be b or c")
    left, right = _correlation_input(x, y, missing_policy)
    if left.size < 3 or np.unique(left).size < 2 or np.unique(right).size < 2:
        reject("NONPARAMETRIC_DEGENERATE_INPUT", "Kendall correlation needs variation and at least three pairs")
    outcome = stats.kendalltau(left, right, variant=variant)
    return result(
        operation_id="nonparametric.kendall",
        n_observations=left.size,
        method="kendall_tau",
        estimand="ordinal concordance association between paired variables",
        input_semantics="paired finite numeric observations",
        assumptions=["pairs are independent for the reference p-value", "ties follow the declared Kendall variant"],
        limitations=["association is not causation", "small samples and extensive ties require cautious inference"],
        not_claimed=["does not establish a causal effect", "does not identify a structural model"],
        unsupported_extensions=["clustered or survey concordance variance is not included"],
        statistic=float(outcome.statistic),
        p_value=float(outcome.pvalue),
        alpha=level,
        inference={"method": "asymptotic", "variant": variant},
        sample_size=int(left.size),
        effect_size={"kendall_tau": float(outcome.statistic)},
    )
