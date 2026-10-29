"""Statistical test kernels: Welch statistics, effect sizes, group summaries, named one/two-sample, ANOVA post-hoc and variance/normality tests."""

from __future__ import annotations

import math
from statistics import StatisticsError
from itertools import combinations
from collections.abc import Mapping, Sequence
from typing import Any
import numpy as np
import pandas as pd
from scipy import stats

from .statistical_test_values import _safe_float


def _welch_t_statistics(
    left: Sequence[float], right: Sequence[float]
) -> tuple[float | None, float | None, list[str]]:
    """Compute Welch's statistic without asking SciPy to divide by zero.

    SciPy's t-test is still the reference for ordinary inputs, but its
    warning-producing moment path is not useful for a declared zero-variance
    boundary. Returning a typed warning keeps that boundary visible to the
    result contract while preserving the finite Welch calculation when only
    one group is constant.
    """
    return _welch_from(_GroupSummary([float(value) for value in left]),
                       _GroupSummary([float(value) for value in right]))


def _welch_from(
    left: _GroupSummary, right: _GroupSummary
) -> tuple[float | None, float | None, list[str]]:
    left_variance = left.variance
    right_variance = right.variance
    standard_error_squared = (
        left_variance / left.n + right_variance / right.n
    )
    warning_codes = (
        ["T_TEST_ZERO_VARIANCE"]
        if left_variance == 0 or right_variance == 0
        else []
    )
    if standard_error_squared <= 0:
        return None, None, warning_codes or ["T_TEST_ZERO_VARIANCE"]
    statistic = (
        left.total / left.n - right.total / right.n
    ) / math.sqrt(standard_error_squared)
    denominator = (
        (left_variance / left.n) ** 2 / (left.n - 1)
        + (right_variance / right.n) ** 2 / (right.n - 1)
    )
    if denominator <= 0:
        return None, None, warning_codes or ["T_TEST_ZERO_VARIANCE"]
    degrees_of_freedom = standard_error_squared**2 / denominator
    p_value = 2.0 * float(stats.t.sf(abs(statistic), degrees_of_freedom))
    return statistic, p_value, warning_codes


def sample_variance(values: Sequence[float]) -> float:
    """Sample variance (ddof=1), as ``statistics.variance`` computes it.

    ``statistics.variance`` works in exact fractions: correct, and minutes long
    on a million observations. This is the compensated two-pass algorithm in
    numpy; a constant sequence is exactly 0.0, so the zero-variance
    rejections that depend on it still fire.
    """

    array = np.asarray(values, dtype=float)
    if array.size < 2:
        raise StatisticsError("variance requires at least two data points")
    if array.max() == array.min():
        return 0.0
    deviations = array - array.mean()
    return float((np.dot(deviations, deviations) - deviations.sum() ** 2 / array.size) / (array.size - 1))


def _finite_array(values: Sequence[float], *, label: str, minimum: int = 2) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.size < minimum:
        raise ValueError(f"{label} requires at least two observations")
    if not np.isfinite(array).all():
        raise ValueError(f"{label} requires finite observations")
    return array


def _finite_values(values: Sequence[float], *, label: str, minimum: int = 2) -> list[float]:
    array = np.asarray(values, dtype=float)
    if array.size < minimum:
        raise ValueError(f"{label} requires at least two observations")
    if not np.isfinite(array).all():
        raise ValueError(f"{label} requires finite observations")
    return array.tolist()


def _evidence_result(
    *,
    test_id: str,
    test_type: str,
    nobs: int,
    statistic: float | None,
    p_value: float | None,
    effect_size: dict[str, Any] | None,
    assumptions: list[str],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "test_version": 1,
        "test_type": test_type,
        "nobs": nobs,
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect_size": effect_size,
        "assumptions": assumptions,
        "warnings": warnings or [],
    }


def cohens_d(left: Sequence[float], right: Sequence[float]) -> dict[str, Any]:
    left_values = _finite_values(left, label="left", minimum=2)
    right_values = _finite_values(right, label="right", minimum=2)
    # scipy.stats.tvar emits a RuntimeWarning for the constant/near-constant
    # groups that this function is required to reject. The standard-library
    # implementation preserves sample-variance semantics without turning a
    # predictable typed rejection into numerical warning noise.
    return _cohens_d_from(_GroupSummary(left_values), _GroupSummary(right_values))


class _GroupSummary:
    """A group's count, sum and sample variance, each computed once.

    The pairwise effect sizes of a grouping reuse each group many times; on a
    1,000,000-row import every comparison re-copied and re-converted both
    groups (268 Cohen's d and 272 Welch tests). The same Python sum and the
    same numpy variance of the same values are used, so results are
    bit-identical to computing them per comparison.
    """

    __slots__ = ("values", "n", "total", "_variance")

    def __init__(self, values: list[float] | np.ndarray) -> None:
        self.values = values
        self.n = len(values)
        # Stream Python floats in the original order, preserving builtin sum's
        # compensated reduction without retaining a boxed observation list.
        self.total = sum(map(float, values)) if isinstance(values, np.ndarray) else sum(values)
        self._variance: float | None = None

    @property
    def variance(self) -> float:
        if self._variance is None:
            self._variance = sample_variance(self.values)
        return self._variance


def _cohens_d_from(left: _GroupSummary, right: _GroupSummary) -> dict[str, Any]:
    pooled_variance = (
        (left.n - 1) * left.variance + (right.n - 1) * right.variance
    ) / (left.n + right.n - 2)
    pooled_sd = math.sqrt(pooled_variance)
    if pooled_sd == 0:
        raise ValueError("cohens_d requires non-constant groups")
    return {
        "effect_size_name": "cohens_d",
        "value": (left.total / left.n - right.total / right.n) / pooled_sd,
        "pooled_sd": pooled_sd,
        "nobs": left.n + right.n,
    }


def _group_sums_of_squares(groups: Mapping[str, Sequence[float]], name: str) -> tuple[float, float, int, int]:
    """Between- and within-group sums of squares, each group's mean computed once."""

    # The previous list round-trip made C-contiguous arrays. Keep that reduction
    # order for strided/Fortran inputs while reusing already contiguous buffers.
    arrays = {str(key): np.ascontiguousarray(_finite_array(values, label=f"group {key}")) for key, values in groups.items()}
    if len(arrays) < 2:
        raise ValueError(f"{name} requires at least two groups")
    total_n = sum(array.size for array in arrays.values())
    grand_mean = sum(float(array.sum()) for array in arrays.values()) / total_n
    between = 0.0
    within = 0.0
    for array in arrays.values():
        mean = float(array.mean())
        between += array.size * (mean - grand_mean) ** 2
        deviations = array - mean
        within += float(np.dot(deviations, deviations))
    return between, within, len(arrays), total_n


def eta_squared(groups: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    between, within, _groups, total_n = _group_sums_of_squares(groups, "eta_squared")
    total = between + within
    if total == 0:
        raise ValueError("eta_squared requires non-constant observations")
    return {"effect_size_name": "eta_squared", "value": between / total, "nobs": total_n}


def omega_squared(groups: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    between, within, group_count, total_n = _group_sums_of_squares(groups, "omega_squared")
    degrees_between = group_count - 1
    degrees_within = total_n - group_count
    mean_within = within / degrees_within if degrees_within else 0.0
    denominator = between + within + mean_within
    value = (between - degrees_between * mean_within) / denominator if denominator else 0.0
    return {"effect_size_name": "omega_squared", "value": value, "nobs": total_n}


def posthoc_anova(groups: Mapping[str, Sequence[float]], *, correction: str) -> dict[str, Any]:
    # The old list round-trip made contiguous float64 groups. Keep that
    # reduction order for strided inputs without boxing each observation.
    arrays = {str(name): np.ascontiguousarray(_finite_array(values, label=f"group {name}"))
              for name, values in groups.items()}
    if len(arrays) < 2:
        raise ValueError("posthoc_anova requires at least two groups")
    if correction not in {"tukey", "bonferroni"}:
        raise ValueError("correction must be tukey or bonferroni")
    sizes = tuple(map(len, arrays.values()))
    statistic, p_value = stats.f_oneway(*arrays.values())
    comparisons: list[dict[str, Any]] = []
    if correction == "tukey":
        values = np.concatenate(tuple(arrays.values()))
        labels = np.repeat(np.asarray(tuple(arrays)), sizes)
        tukey = statsmodels_pairwise_tukey(values, labels)
        for row in tukey:
            comparisons.append(row)
    else:
        pairs = list(combinations(arrays, 2))
        for left_name, right_name in pairs:
            pair_stat, pair_p = stats.ttest_ind(arrays[left_name], arrays[right_name], equal_var=False)
            comparisons.append(
                {
                    "group1": left_name,
                    "group2": right_name,
                    "statistic": _safe_float(pair_stat),
                    "p_value": min(1.0, float(pair_p) * len(pairs)),
                    "correction": "bonferroni",
                    "effect_size": cohens_d(arrays[left_name], arrays[right_name]),
                }
            )
    result = _evidence_result(
        test_id="anova_posthoc",
        test_type="anova_posthoc",
        nobs=sum(sizes),
        statistic=statistic,
        p_value=p_value,
        effect_size=eta_squared(arrays),
        assumptions=["independent observations", "approximately normal residuals", "homogeneous variance"],
    )
    result.update({"correction": correction, "family": "all_group_pairs", "comparisons": comparisons})
    return result


def statsmodels_pairwise_tukey(values: Sequence[float], labels: Sequence[str]) -> list[dict[str, Any]]:
    from statsmodels.stats.multicomp import pairwise_tukeyhsd

    table = pairwise_tukeyhsd(values, labels).summary().data
    headers = [str(header) for header in table[0]]
    comparisons: list[dict[str, Any]] = []
    for row in table[1:]:
        raw = dict(zip(headers, row, strict=True))
        comparisons.append(
            {
                "group1": str(raw["group1"]),
                "group2": str(raw["group2"]),
                "mean_difference": _safe_float(raw["meandiff"]),
                "p_value": _safe_float(raw["p-adj"]),
                "ci_low": _safe_float(raw["lower"]),
                "ci_high": _safe_float(raw["upper"]),
                "reject": bool(raw["reject"]),
                "correction": "tukey",
            }
        )
    return comparisons


def one_sample_t_test(values: Sequence[float], *, population_mean: float) -> dict[str, Any]:
    observations = _finite_values(values, label="one_sample_t_test")
    statistic, p_value = stats.ttest_1samp(observations, population_mean)
    return _evidence_result(
        test_id="one_sample_t_test",
        test_type="one_sample_t_test",
        nobs=len(observations),
        statistic=statistic,
        p_value=p_value,
        effect_size={"effect_size_name": "mean_difference", "value": sum(observations) / len(observations) - population_mean},
        assumptions=["independent observations", "approximately normal observations"],
    )


def paired_t_test(left: Sequence[float], right: Sequence[float]) -> dict[str, Any]:
    left_values = _finite_values(left, label="paired_t_test")
    right_values = _finite_values(right, label="paired_t_test")
    if len(left_values) != len(right_values):
        raise ValueError("paired_t_test requires equal-length pairs")
    differences = [right_values[index] - left_values[index] for index in range(len(left_values))]
    mean_difference = math.fsum(differences) / len(differences)
    difference_variance = sample_variance(differences)
    if math.isclose(difference_variance, 0.0, abs_tol=1e-24):
        statistic = None
        p_value = 0.0 if mean_difference != 0 else None
        warning_codes = ["PAIRED_T_ZERO_VARIANCE"]
    else:
        statistic = mean_difference / math.sqrt(difference_variance / len(differences))
        p_value = 2.0 * float(stats.t.sf(abs(statistic), len(differences) - 1))
        warning_codes = []
    return _evidence_result(
        test_id="paired_t_test",
        test_type="paired_t_test",
        nobs=len(left_values),
        statistic=statistic,
        p_value=p_value,
        effect_size={"effect_size_name": "mean_paired_difference", "value": mean_difference},
        assumptions=["valid one-to-one pairing", "approximately normal paired differences"],
        warnings=warning_codes,
    )


def wilcoxon_signed_rank(left: Sequence[float], right: Sequence[float]) -> dict[str, Any]:
    left_values = _finite_values(left, label="wilcoxon_signed_rank")
    right_values = _finite_values(right, label="wilcoxon_signed_rank")
    if len(left_values) != len(right_values):
        raise ValueError("wilcoxon_signed_rank requires equal-length pairs")
    statistic, p_value = stats.wilcoxon(left_values, right_values)
    return _evidence_result(
        test_id="wilcoxon_signed_rank",
        test_type="wilcoxon_signed_rank",
        nobs=len(left_values),
        statistic=statistic,
        p_value=p_value,
        effect_size={"effect_size_name": "median_paired_difference", "value": float(pd.Series(right_values).subtract(left_values).median())},
        assumptions=["valid one-to-one pairing", "symmetric paired differences for signed-rank interpretation"],
    )


def variance_and_normality_tests(groups: Mapping[str, Sequence[float]]) -> list[dict[str, Any]]:
    # The same finite float values as _finite_values gives, kept as arrays:
    # scipy and sample_variance convert lists to exactly these arrays anyway.
    arrays = [_finite_array(values, label=f"group {name}") for name, values in groups.items()]
    if len(arrays) < 2:
        raise ValueError("variance tests require at least two groups")
    combined = np.concatenate(arrays)
    zero_variance_group = any(sample_variance(values) == 0 for values in arrays)
    if zero_variance_group:
        levene_stat, levene_p = None, None
        bartlett_stat, bartlett_p = None, None
    else:
        levene_stat, levene_p = stats.levene(*arrays, center="median")
        bartlett_stat, bartlett_p = stats.bartlett(*arrays)
    if sample_variance(combined) == 0:
        shapiro_stat, shapiro_p = None, None
        shapiro_warnings = ["SHAPIRO_ZERO_VARIANCE"]
    else:
        shapiro_stat, shapiro_p = stats.shapiro(combined)
        shapiro_warnings = []
    variance_warnings = ["ZERO_VARIANCE_GROUP"] if zero_variance_group else []
    return [
        _evidence_result(
            test_id="levene",
            test_type="levene",
            nobs=len(combined),
            statistic=levene_stat,
            p_value=levene_p,
            effect_size=None,
            assumptions=["independent observations", "groups contain at least two finite values"],
            warnings=variance_warnings,
        ),
        _evidence_result(
            test_id="bartlett",
            test_type="bartlett",
            nobs=len(combined),
            statistic=bartlett_stat,
            p_value=bartlett_p,
            effect_size=None,
            assumptions=["independent observations", "approximately normal groups"],
            warnings=variance_warnings,
        ),
        _evidence_result(
            test_id="shapiro_wilk",
            test_type="shapiro_wilk",
            nobs=len(combined),
            statistic=shapiro_stat,
            p_value=shapiro_p,
            effect_size=None,
            assumptions=["independent observations", "sample size is within Shapiro-Wilk operating range"],
            warnings=shapiro_warnings,
        ),
    ]
