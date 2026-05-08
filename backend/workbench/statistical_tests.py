from __future__ import annotations

import math
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd
from scipy import stats

from .artifacts import register_artifact, write_json

CATEGORY_MAX_UNIQUE = 20

TEST_FAMILIES = {
    "correlations": "correlations.json",
    "t_tests": "t_tests.json",
    "anova": "anova.json",
    "chi_square": "chi_square.json",
}


def run_statistical_tests(
    frame: pd.DataFrame,
    *,
    analysis_columns: list[str],
) -> dict[str, dict[str, Any]]:
    columns = [column for column in analysis_columns if column in frame.columns]
    results: dict[str, dict[str, Any]] = {
        name: {"schema_version": 1, "test_type": name, "results": []}
        for name in TEST_FAMILIES
    }
    numeric = [column for column in columns if _is_numeric(frame[column])]
    categorical = [column for column in columns if _is_categorical(frame[column])]
    binary = [column for column in categorical if _non_null_unique(frame[column]) == 2]
    multi = [
        column for column in categorical
        if 3 <= _non_null_unique(frame[column]) <= CATEGORY_MAX_UNIQUE
    ]

    for left, right in combinations(numeric, 2):
        row = _pearson(frame, left, right)
        if row is not None:
            results["correlations"]["results"].append(row)

    for outcome in numeric:
        for group in binary:
            if outcome == group:
                continue
            row = _welch_t_test(frame, outcome, group)
            if row is not None:
                results["t_tests"]["results"].append(row)

    for outcome in numeric:
        for group in multi:
            if outcome == group:
                continue
            row = _anova(frame, outcome, group)
            if row is not None:
                results["anova"]["results"].append(row)

    for left, right in combinations(categorical, 2):
        row = _chi_square(frame, left, right)
        if row is not None:
            results["chi_square"]["results"].append(row)

    return results


def write_statistical_test_artifacts(
    run_root: Path,
    results: dict[str, dict[str, Any]],
) -> None:
    tests_dir = run_root / "statistical_tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for family, filename in TEST_FAMILIES.items():
        path = tests_dir / filename
        write_json(path, results[family])
        register_artifact(
            run_root,
            f"statistical_tests_{family}",
            path,
            "statistical_test",
            "statistical_tests",
            ["cleaned_dataset"],
        )


_MAX_TEST_SUMMARIES_PER_FAMILY = 15


def summarize_statistical_tests(
    results: dict[str, dict[str, Any]],
    y: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    y_related: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for family in ("correlations", "t_tests", "anova", "chi_square"):
        for row in results.get(family, {}).get("results", []):
            summary = _summary_row(row)
            if y and _involves_variable(row, y):
                y_related.append(summary)
            else:
                other.append(summary)
    y_related.sort(key=_p_value_sort_key)
    other.sort(key=_p_value_sort_key)
    total_other = len(other)
    return {
        "y_related": y_related,
        "other": other[:_MAX_TEST_SUMMARIES_PER_FAMILY],
        "other_truncated": total_other - len(other[:_MAX_TEST_SUMMARIES_PER_FAMILY]),
    }


# --- Helpers ---


def _is_numeric(series: pd.Series) -> bool:
    return bool(pd.api.types.is_numeric_dtype(series))


def _non_null_unique(series: pd.Series) -> int:
    return int(series.dropna().nunique())


def _is_categorical(series: pd.Series) -> bool:
    if _is_numeric(series):
        unique = _non_null_unique(series)
        return 2 <= unique <= CATEGORY_MAX_UNIQUE and unique < int(series.dropna().shape[0])
    return 2 <= _non_null_unique(series) <= CATEGORY_MAX_UNIQUE


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


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


def _pearson(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 3:
        return None
    statistic, p_value = stats.pearsonr(pair[left], pair[right])
    return {
        "test_id": f"correlation:{left}:{right}",
        "test_type": "pearson_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"r": _safe_float(statistic)},
        "source_id": f"statistical_tests.correlations.{left}.{right}",
    }


def _welch_t_test(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_series = _as_series(pair, group)
    if group_series is None:
        return None
    group_values = sorted(group_series.dropna().unique().tolist(), key=str)
    if len(group_values) != 2:
        return None
    left = pd.to_numeric(pair.loc[group_series == group_values[0], outcome], errors="coerce").dropna()
    right = pd.to_numeric(pair.loc[group_series == group_values[1], outcome], errors="coerce").dropna()
    if len(left) < 2 or len(right) < 2:
        return None
    statistic, p_value = stats.ttest_ind(left, right, equal_var=False)
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
        "source_id": f"statistical_tests.t_tests.{outcome}.{group}",
    }


def _anova(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_series = _as_series(pair, group)
    if group_series is None:
        return None
    group_values = sorted(group_series.dropna().unique().tolist(), key=str)
    samples = [
        pd.to_numeric(pair.loc[group_series == value, outcome], errors="coerce").dropna()
        for value in group_values
    ]
    samples = [sample for sample in samples if len(sample) >= 2]
    if len(samples) < 2:
        return None
    statistic, p_value = stats.f_oneway(*samples)
    group_means = {
        str(value): float(pd.to_numeric(
            pair.loc[group_series == value, outcome], errors="coerce"
        ).mean())
        for value in group_values
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


def _chi_square(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 2:
        return None
    table = pd.crosstab(pair[left], pair[right])
    if table.shape[0] < 2 or table.shape[1] < 2:
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


def _involves_variable(row: dict[str, Any], var: str) -> bool:
    variables = row.get("variables", [])
    if isinstance(variables, list) and var in variables:
        return True
    outcome = row.get("outcome")
    if outcome == var:
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
    elif test_type == "welch_t_test":
        label = f"Welch t-test: {row['outcome']} by {row['group']}"
    elif test_type == "one_way_anova":
        label = f"ANOVA: {row['outcome']} by {row['group']}"
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
