"""Automatic pairwise scan tests (correlations, group comparisons, contingency tables), multiple-testing correction and summary rows."""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from . import native_kendall, native_math
from .statistical_test_values import CATEGORY_MAX_UNIQUE, _safe_float
from .statistical_test_kernels import _welch_t_statistics


def _is_numeric(series: pd.Series) -> bool:
    return bool(pd.api.types.is_numeric_dtype(series))


def _non_null_unique(series: pd.Series) -> int:
    return int(series.nunique())  # dropna=True already; no copy of the column


def _categorical_cardinality(series: pd.Series) -> int | None:
    unique = _non_null_unique(series)
    if 2 <= unique <= CATEGORY_MAX_UNIQUE and (
        not _is_numeric(series) or unique < int(series.count())
    ):
        return unique
    return None


def _pairwise(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    deduped = list(dict.fromkeys(columns))
    available = [c for c in deduped if c in frame.columns]
    return frame.loc[:, available].dropna()


def _as_series(df: pd.DataFrame, column: str) -> pd.Series | None:
    result = df[column]
    if isinstance(result, pd.DataFrame):
        if result.shape[1] == 0:
            return None
        return result.iloc[:, 0]
    if isinstance(result, pd.Series):
        return result
    return None


class _PreparedGroups:
    """Preparation for one outcome/group pair; no statistical result is cached.

    Keep the pre-dropna conversion separately: ANOVA/Kruskal effect summaries
    originally used pandas skipna on that Series, not a repacked sample.
    The owning loop releases this object before advancing to its next pair.
    """

    def __init__(self, frame: pd.DataFrame, outcome: str, group: str) -> None:
        self.pair = _pairwise(frame, [outcome, group])
        self.group_series = _as_series(self.pair, group)
        self.labels = ([] if self.group_series is None else
                       sorted(self.group_series.dropna().unique().tolist(), key=str))
        self.outcome = outcome
        # Index by label position; raw labels with equal str() forms stay distinct.
        self._numeric: dict[int, pd.Series] = {}
        self._samples: dict[int, pd.Series] = {}

    def numeric(self, index: int) -> pd.Series:
        if index not in self._numeric:
            self._numeric[index] = pd.to_numeric(
                self.pair.loc[self.group_series == self.labels[index], self.outcome],
                errors="coerce",
            )
        return self._numeric[index]

    def sample(self, index: int) -> pd.Series:
        if index not in self._samples:
            self._samples[index] = self.numeric(index).dropna()
        return self._samples[index]


def _prepare_correlation_pair(
    frame: pd.DataFrame, left: str, right: str, *, complete_constancy: dict[str, bool] | None = None,
) -> tuple[pd.DataFrame, bool]:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 3:
        return pair, False
    if complete_constancy is None or len(pair) != len(frame):
        return pair, _non_null_unique(pair[left]) < 2 or _non_null_unique(pair[right]) < 2
    for column in (left, right):
        if column not in complete_constancy:
            complete_constancy[column] = _non_null_unique(pair[column]) < 2
        if complete_constancy[column]:
            return pair, True
    return pair, False


def _pearson(
    frame: pd.DataFrame, left: str, right: str, *,
    prepared: tuple[pd.DataFrame, bool] | None = None,
) -> dict[str, Any] | None:
    pair, constant_input = prepared if prepared is not None else _prepare_correlation_pair(frame, left, right)
    if len(pair) < 3:
        return None
    if constant_input:
        return {
            "test_id": f"correlation:{left}:{right}",
            "test_type": "pearson_correlation",
            "variables": [left, right],
            "nobs": int(len(pair)),
            "statistic": None,
            "p_value": None,
            "effect": {"r": None},
            "warnings": ["CORRELATION_CONSTANT_INPUT"],
            "source_id": f"statistical_tests.correlations.{left}.{right}",
        }
    statistic, p_value = stats.pearsonr(pair[left], pair[right])
    return {
        "test_id": f"correlation:{left}:{right}",
        "test_type": "pearson_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"r": _safe_float(statistic)},
        "warnings": [],
        "source_id": f"statistical_tests.correlations.{left}.{right}",
    }


def _rank_correlations(frame: pd.DataFrame, left: str, right: str, *, check_cancel=None,
                       rank_cache: dict | None = None, kendall_pool=None,
                       prepared: tuple[pd.DataFrame, bool] | None = None) -> list[Any]:
    """Spearman and Kendall rows of a pair.

    With kendall_pool (an executor) the Kendall row is a Future of that row: the native count
    releases the GIL, so it runs while the caller goes on with the next tests.
    """
    if check_cancel is not None:
        check_cancel()
    pair, constant_input = prepared if prepared is not None else _prepare_correlation_pair(frame, left, right)
    if len(pair) < 3:
        return []
    rows: list[dict[str, Any]] = []
    if constant_input:
        warning_codes = ["CORRELATION_CONSTANT_INPUT"]
    else:
        warning_codes = []
    if constant_input:
        statistic, p_value = None, None
        spearman_computation = {"engine": "not-computed", "reason": "constant-input"}
    else:
        whole_columns = len(pair) == len(frame) and frame.columns.is_unique and left != right
        spearman_outcome = native_math.evaluate_spearman(
            pair[left].to_numpy(copy=False), pair[right].to_numpy(copy=False),
            check_cancel=check_cancel,
            rank_keys=(left, right) if whole_columns else None, rank_cache=rank_cache,
        )
        statistic, p_value = spearman_outcome.statistic, spearman_outcome.pvalue
        spearman_computation = {"engine": spearman_outcome.engine, "reason": spearman_outcome.reason}
    rows.append({
        "test_id": f"spearman_correlation:{left}:{right}",
        "test_type": "spearman_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"rho": _safe_float(statistic)},
        "warnings": warning_codes,
        "source_id": f"statistical_tests.rank_correlations.spearman.{left}.{right}",
        "computation": spearman_computation,
    })
    if check_cancel is not None:
        check_cancel()
    if constant_input:
        rows.append(_kendall_row(left, right, len(pair), warning_codes, None))
    elif kendall_pool is None:
        rows.append(_kendall_row(left, right, len(pair), warning_codes, native_kendall.evaluate(
            pair[left].to_numpy(copy=False), pair[right].to_numpy(copy=False))))
    else:
        rows.append(kendall_pool.submit(_evaluated_kendall_row, left, right, len(pair), warning_codes,
                                        pair[left].to_numpy(copy=False), pair[right].to_numpy(copy=False)))
    if check_cancel is not None:
        check_cancel()
    return rows


def _evaluated_kendall_row(left, right, nobs, warning_codes, x, y) -> dict[str, Any]:
    return _kendall_row(left, right, nobs, warning_codes, native_kendall.evaluate(x, y))


def _kendall_row(left: str, right: str, nobs: int, warning_codes: list[str], outcome) -> dict[str, Any]:
    """The Kendall row of a pair; outcome None means a constant input, not computed."""
    kendall_warning_codes = list(warning_codes)
    if outcome is None:
        statistic, p_value = None, None
        computation = {"engine": "not-computed", "reason": "constant-input"}
    else:
        statistic, p_value = outcome.statistic, outcome.pvalue
        computation = {"engine": outcome.engine, "reason": outcome.reason}
        if outcome.reason == "public-integer-promotion":
            kendall_warning_codes.append("KENDALL_PUBLIC_INTEGER_PROMOTION")
    return {
        "test_id": f"kendall_correlation:{left}:{right}",
        "test_type": "kendall_correlation",
        "variables": [left, right],
        "nobs": int(nobs),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"tau": _safe_float(statistic)},
        "warnings": kendall_warning_codes,
        "source_id": f"statistical_tests.rank_correlations.kendall.{left}.{right}",
        "computation": computation,
    }


def _welch_t_test(
    frame: pd.DataFrame, outcome: str, group: str, *, prepared: _PreparedGroups | None = None,
) -> dict[str, Any] | None:
    if prepared is None:
        prepared = _PreparedGroups(frame, outcome, group)
    if prepared.group_series is None:
        return None
    group_values = prepared.labels
    if len(group_values) != 2:
        return None
    left, right = prepared.sample(0), prepared.sample(1)
    if len(left) < 2 or len(right) < 2:
        return None
    statistic, p_value, warning_codes = _welch_t_statistics(_welch_input(left), _welch_input(right))
    mean_left = float(left.mean())
    mean_right = float(right.mean())
    return {
        "test_id": f"t_test:{outcome}:{group}",
        "test_type": "welch_t_test",
        "outcome": outcome,
        "group": group,
        "groups": [str(group_values[0]), str(group_values[1])],
        "nobs": int(len(left) + len(right)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {
            f"mean_{group_values[0]}": mean_left,
            f"mean_{group_values[1]}": mean_right,
            "difference": mean_right - mean_left,
        },
        "warnings": warning_codes,
        "source_id": f"statistical_tests.t_tests.{outcome}.{group}",
    }


def _welch_input(values: pd.Series) -> list[Any] | Any:
    """A numpy-typed group as a float64 array: the floats float(item) of tolist() would give,
    without boxing a million of them (int64 converts to the nearest double either way)."""
    if isinstance(values.dtype, np.dtype) and values.dtype.kind in "iuf" and values.dtype.itemsize == 8:
        return values.to_numpy(dtype=np.float64)
    return values.tolist()


def _mann_whitney_u(
    frame: pd.DataFrame, outcome: str, group: str, *, prepared: _PreparedGroups | None = None,
) -> dict[str, Any] | None:
    if prepared is None:
        prepared = _PreparedGroups(frame, outcome, group)
    if prepared.group_series is None:
        return None
    group_values = prepared.labels
    if len(group_values) != 2:
        return None
    left, right = prepared.sample(0), prepared.sample(1)
    if len(left) < 2 or len(right) < 2:
        return None
    statistic, p_value = stats.mannwhitneyu(left, right, alternative="two-sided")
    median_left = float(left.median())
    median_right = float(right.median())
    return {
        "test_id": f"mann_whitney_u:{outcome}:{group}",
        "test_type": "mann_whitney_u",
        "outcome": outcome,
        "group": group,
        "groups": [str(group_values[0]), str(group_values[1])],
        "nobs": int(len(left) + len(right)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {
            f"median_{group_values[0]}": median_left,
            f"median_{group_values[1]}": median_right,
            "median_difference": median_right - median_left,
        },
        "source_id": f"statistical_tests.nonparametric.mann_whitney_u.{outcome}.{group}",
    }


def _anova(
    frame: pd.DataFrame, outcome: str, group: str, *, prepared: _PreparedGroups | None = None,
) -> dict[str, Any] | None:
    if prepared is None:
        prepared = _PreparedGroups(frame, outcome, group)
    if prepared.group_series is None:
        return None
    group_values = prepared.labels
    samples = [prepared.sample(index) for index in range(len(group_values))]
    samples = [sample for sample in samples if len(sample) >= 2]
    if len(samples) < 2:
        return None
    statistic, p_value = stats.f_oneway(*samples)
    group_means = {
        str(value): float(prepared.numeric(index).mean())
        for index, value in enumerate(group_values)
    }
    return {
        "test_id": f"anova:{outcome}:{group}",
        "test_type": "one_way_anova",
        "outcome": outcome,
        "group": group,
        "groups": [str(value) for value in group_values],
        "nobs": int(sum(len(sample) for sample in samples)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"group_means": group_means},
        "source_id": f"statistical_tests.anova.{outcome}.{group}",
    }


def _kruskal_wallis(
    frame: pd.DataFrame, outcome: str, group: str, *, prepared: _PreparedGroups | None = None,
) -> dict[str, Any] | None:
    if prepared is None:
        prepared = _PreparedGroups(frame, outcome, group)
    if prepared.group_series is None:
        return None
    group_values = prepared.labels
    samples = [prepared.sample(index) for index in range(len(group_values))]
    if len(samples) < 2 or any(len(sample) < 2 for sample in samples):
        return None
    statistic, p_value = stats.kruskal(*samples)
    group_medians = {
        str(value): float(prepared.numeric(index).median())
        for index, value in enumerate(group_values)
    }
    return {
        "test_id": f"kruskal_wallis:{outcome}:{group}",
        "test_type": "kruskal_wallis",
        "outcome": outcome,
        "group": group,
        "groups": [str(value) for value in group_values],
        "nobs": int(sum(len(sample) for sample in samples)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"group_medians": group_medians},
        "source_id": f"statistical_tests.nonparametric.kruskal_wallis.{outcome}.{group}",
    }


def _prepare_contingency_table(frame: pd.DataFrame, left: str, right: str) -> pd.DataFrame | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 2:
        return None
    return pd.crosstab(pair[left], pair[right])


def _chi_square(table: pd.DataFrame | None, left: str, right: str) -> dict[str, Any] | None:
    if table is None or table.shape[0] < 2 or table.shape[1] < 2:
        return None
    statistic, p_value, dof, _expected = stats.chi2_contingency(table)
    return {
        "test_id": f"chi_square:{left}:{right}",
        "test_type": "chi_square",
        "variables": [left, right],
        "nobs": int(table.to_numpy().sum()),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "degrees_of_freedom": int(dof),
        "effect": {
            "contingency_table": {
                str(index): {str(column): int(value) for column, value in row.items()}
                for index, row in table.to_dict(orient="index").items()
            }
        },
        "source_id": f"statistical_tests.chi_square.{left}.{right}",
    }


def _fisher_exact(table: pd.DataFrame | None, left: str, right: str) -> dict[str, Any] | None:
    if table is None or table.shape != (2, 2):
        return None
    statistic, p_value = stats.fisher_exact(table)
    return {
        "test_id": f"fisher_exact:{left}:{right}",
        "test_type": "fisher_exact",
        "variables": [left, right],
        "nobs": int(table.to_numpy().sum()),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {
            "odds_ratio": _safe_float(statistic),
            "contingency_table": {
                str(index): {str(column): int(value) for column, value in row.items()}
                for index, row in table.to_dict(orient="index").items()
            },
        },
        "source_id": f"statistical_tests.fisher_exact.{left}.{right}",
    }


def _apply_multiple_testing_correction(results: dict[str, dict[str, Any]]) -> bool:
    rows: list[dict[str, Any]] = []
    p_values: list[float] = []
    for family in results.values():
        for row in family.get("results", []):
            p_value = _safe_float(row.get("p_value"))
            if p_value is None:
                continue
            rows.append(row)
            p_values.append(p_value)
    if not p_values:
        return False
    _rejected, corrected, _alpha_sidak, _alpha_bonf = multipletests(
        p_values,
        method="fdr_bh",
    )
    for row, p_value_corrected in zip(rows, corrected, strict=True):
        row["p_value_corrected"] = _safe_float(p_value_corrected)
        row["correction_method"] = "fdr_bh"
    return True


def _involves_variable(row: dict[str, Any], var: str) -> bool:
    variables = row.get("variables", [])
    if isinstance(variables, list) and var in variables:
        return True
    outcome = row.get("outcome")
    if outcome == var:
        return True
    group = row.get("group")
    if group == var:
        return True
    return False


def _p_value_sort_key(summary: dict[str, Any]) -> float:
    p = summary.get("p_value")
    if p is None:
        return 2.0
    return float(p)


def _p_value_text(p_value: float | None) -> str:
    if p_value is None:
        return "p-value unavailable"
    if p_value < 0.001:
        return "p < 0.001"
    return f"p = {p_value:.3f}"


def _summary_row(row: dict[str, Any]) -> dict[str, Any]:
    p_value = row.get("p_value")
    statistic = row.get("statistic")
    test_type = row.get("test_type")
    if test_type == "pearson_correlation":
        label = f"Pearson correlation: {row['variables'][0]} vs {row['variables'][1]}"
    elif test_type == "spearman_correlation":
        label = f"Spearman correlation: {row['variables'][0]} vs {row['variables'][1]}"
    elif test_type == "kendall_correlation":
        label = f"Kendall correlation: {row['variables'][0]} vs {row['variables'][1]}"
    elif test_type == "welch_t_test":
        label = f"Welch t-test: {row['outcome']} by {row['group']}"
    elif test_type == "one_way_anova":
        label = f"ANOVA: {row['outcome']} by {row['group']}"
    elif test_type == "mann_whitney_u":
        label = f"Mann-Whitney U: {row['outcome']} by {row['group']}"
    elif test_type == "kruskal_wallis":
        label = f"Kruskal-Wallis: {row['outcome']} by {row['group']}"
    elif test_type == "fisher_exact":
        label = f"Fisher exact: {row['variables'][0]} vs {row['variables'][1]}"
    elif test_type == "two_proportions":
        label = f"Two proportions: {row['outcome']} by {row['group']}"
    else:
        label = f"Chi-square: {row['variables'][0]} vs {row['variables'][1]}"
    return {
        "label": label,
        "statistic": statistic,
        "p_value": p_value,
        "interpretation": (
            f"Statistic {statistic:.4f}; {_p_value_text(p_value)}."
            if statistic is not None
            else _p_value_text(p_value)
        ),
        "source_id": row["source_id"],
    }
