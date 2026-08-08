from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .artifacts import register_artifact, write_json

CATEGORY_MAX_UNIQUE = 20

@dataclass(frozen=True)
class TestFamilyContract:
    """One statistical test family's artifact name and what it actually runs.

    The summary is here rather than beside the capability inventory on purpose:
    a description kept next to the consumer is a second copy that drifts the
    first time a family changes what it computes. This is the declaration, and
    the inventory reads it.
    """

    artifact_filename: str
    summary: str


TEST_FAMILIES: dict[str, TestFamilyContract] = {
    "correlations": TestFamilyContract(
        "correlations.json",
        "Pearson correlation for every pair of numeric analysis columns.",
    ),
    "rank_correlations": TestFamilyContract(
        "rank_correlations.json",
        "Spearman and Kendall rank correlation, for monotonic association that "
        "is not linear.",
    ),
    "t_tests": TestFamilyContract(
        "t_tests.json",
        "Welch two-sample t-test of a numeric outcome across a binary group.",
    ),
    "anova": TestFamilyContract(
        "anova.json",
        "One-way ANOVA of a numeric outcome across a categorical group with "
        "three or more levels.",
    ),
    "nonparametric": TestFamilyContract(
        "nonparametric.json",
        "Mann-Whitney U and Kruskal-Wallis rank tests, for group differences "
        "without a normality assumption.",
    ),
    "chi_square": TestFamilyContract(
        "chi_square.json",
        "Chi-square test of independence between two categorical columns.",
    ),
    "fisher_exact": TestFamilyContract(
        "fisher_exact.json",
        "Fisher exact test of independence, for tables too sparse for the "
        "chi-square approximation.",
    ),
    "evidence": TestFamilyContract(
        "evidence.json",
        "Advanced evidence packet: effect sizes, ANOVA post-hoc comparisons, "
        "variance tests, and paired or one-sample tests for declared targets.",
    ),
}


class StatisticalTestContractError(ValueError):
    """A requested statistical comparison lacks explicit semantic columns."""


def run_statistical_tests(
    frame: pd.DataFrame,
    *,
    analysis_columns: list[str],
    dataset_sha256: str | None = None,
    lineage_parent: str | None = None,
    reference_means: Mapping[str, float] | None = None,
    paired_columns: Sequence[tuple[str, str]] | None = None,
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
        for rank_row in _rank_correlations(frame, left, right):
            results["rank_correlations"]["results"].append(rank_row)

    for outcome in numeric:
        for group in binary:
            if outcome == group:
                continue
            row = _welch_t_test(frame, outcome, group)
            if row is not None:
                results["t_tests"]["results"].append(row)
            row = _mann_whitney_u(frame, outcome, group)
            if row is not None:
                results["nonparametric"]["results"].append(row)

    for outcome in numeric:
        for group in multi:
            if outcome == group:
                continue
            row = _anova(frame, outcome, group)
            if row is not None:
                results["anova"]["results"].append(row)
            row = _kruskal_wallis(frame, outcome, group)
            if row is not None:
                results["nonparametric"]["results"].append(row)

    for left, right in combinations(categorical, 2):
        row = _chi_square(frame, left, right)
        if row is not None:
            results["chi_square"]["results"].append(row)
        row = _fisher_exact(frame, left, right)
        if row is not None:
            results["fisher_exact"]["results"].append(row)

    # Keep the historical eight-family FDR scope stable. The new evidence
    # packet is assembled only after this correction pass.
    _apply_multiple_testing_correction(results)
    advanced = _build_advanced_evidence_results(
        frame,
        numeric=numeric,
        categorical=binary + [column for column in multi if column not in binary],
        reference_means=reference_means,
        paired_columns=paired_columns,
    )
    evidence_payload = _statistics_evidence_payload(
        advanced,
        dataset_sha256=dataset_sha256,
        lineage_parent=lineage_parent,
    )
    if advanced:
        _apply_multiple_testing_correction({"evidence": evidence_payload})
        evidence_payload["correction_scope"] = "advanced_evidence_family"
    results["evidence"] = evidence_payload
    return results


def write_statistical_test_artifacts(
    run_root: Path,
    results: dict[str, dict[str, Any]],
) -> None:
    tests_dir = run_root / "statistical_tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for family, contract in TEST_FAMILIES.items():
        payload = results.get(family)
        if not isinstance(payload, dict):
            continue
        if family == "evidence" and not payload.get("results"):
            continue
        path = tests_dir / contract.artifact_filename
        write_json(path, payload)
        register_artifact(
            run_root,
            f"statistical_tests_{family}",
            path,
            "statistical_test",
            "statistical_tests",
            ["cleaned_dataset"],
        )


def _statistics_evidence_payload(
    results: list[dict[str, Any]],
    *,
    dataset_sha256: str | None,
    lineage_parent: str | None,
) -> dict[str, Any]:
    if dataset_sha256 is not None and lineage_parent is not None and results:
        return build_statistics_evidence_packet(
            results,
            dataset_sha256=dataset_sha256,
            lineage_parent=lineage_parent,
        )
    payload = {
        "payload_schema": "workbench.statistics.evidence-packet",
        "schema_version": 1,
        "producer": {
            "component": "workbench.statistical_tests",
            "code_version": "workbench-v1.8.6",
        },
        "dataset_ref": {"dataset_sha256": None},
        "lineage_parent": lineage_parent,
        "results": results,
        "limits": [
            "standalone statistical loop call has no persisted dataset identity",
            "independent statistical evidence; not a model-selection decision",
        ],
    }
    if dataset_sha256 is not None:
        payload["dataset_ref"] = {"dataset_sha256": dataset_sha256}
    return payload


def _build_advanced_evidence_results(
    frame: pd.DataFrame,
    *,
    numeric: Sequence[str],
    categorical: Sequence[str],
    reference_means: Mapping[str, float] | None,
    paired_columns: Sequence[tuple[str, str]] | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    if paired_columns is not None:
        for pair in paired_columns:
            if (
                not isinstance(pair, (tuple, list))
                or len(pair) != 2
                or not all(isinstance(column, str) and column for column in pair)
            ):
                raise StatisticalTestContractError(
                    "paired columns must be declared as two column names; "
                    "provide an explicit before/after pair"
                )
            left, right = pair
            if left == right or left not in numeric or right not in numeric:
                raise StatisticalTestContractError(
                    f"paired column pair ({left!r}, {right!r}) must name two "
                    "distinct numeric analysis columns; provide the pair explicitly"
                )
    for outcome in numeric:
        for group in categorical:
            if group == outcome:
                continue
            grouped = _finite_groups(frame, outcome, group)
            if grouped is None:
                continue
            labels, arrays = grouped
            group_map = dict(zip(labels, arrays, strict=True))
            for left_index, right_index in combinations(range(len(arrays)), 2):
                try:
                    evidence.append(
                        _cohens_d_evidence(
                            arrays[left_index],
                            arrays[right_index],
                            test_id=(
                                f"cohens_d:{outcome}:{group}:"
                                f"{labels[left_index]}:{labels[right_index]}"
                            ),
                            labels=(labels[left_index], labels[right_index]),
                        )
                    )
                except ValueError:
                    continue
            if len(arrays) >= 3:
                try:
                    posthoc = posthoc_anova(group_map, correction="tukey")
                    posthoc["test_id"] = f"anova_posthoc:{outcome}:{group}"
                    posthoc["source_id"] = f"statistical_tests.evidence.anova_posthoc.{outcome}.{group}"
                    evidence.append(posthoc)
                    anova = _anova(frame, outcome, group)
                    evidence.append(
                        _effect_evidence(
                            eta_squared(group_map),
                            test_id=f"eta_squared:{outcome}:{group}",
                            statistic=anova.get("statistic") if anova else None,
                            p_value=anova.get("p_value") if anova else None,
                            assumptions=["independent observations", "group membership is declared"],
                        )
                    )
                    evidence.append(
                        _effect_evidence(
                            omega_squared(group_map),
                            test_id=f"omega_squared:{outcome}:{group}",
                            statistic=anova.get("statistic") if anova else None,
                            p_value=anova.get("p_value") if anova else None,
                            assumptions=["independent observations", "group membership is declared"],
                        )
                    )
                except ValueError:
                    # Degenerate groups are not evidence; retain old families.
                    pass
            evidence.extend(_safe_variance_evidence(grouped, outcome, group))

    for column, population_mean in (reference_means or {}).items():
        if column not in numeric:
            continue
        observations = pd.to_numeric(frame[column], errors="coerce").dropna().tolist()
        try:
            result = one_sample_t_test(observations, population_mean=float(population_mean))
        except (TypeError, ValueError):
            continue
        result["test_id"] = f"one_sample_t_test:{column}"
        result["source_id"] = f"statistical_tests.evidence.one_sample_t_test.{column}"
        evidence.append(result)

    for pair in paired_columns or ():
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        left, right = pair
        if not isinstance(left, str) or not isinstance(right, str):
            continue
        if left not in numeric or right not in numeric or left == right:
            continue
        paired = _pairwise(frame, [left, right])
        left_values = pd.to_numeric(paired[left], errors="coerce").dropna().tolist()
        right_values = pd.to_numeric(paired[right], errors="coerce").dropna().tolist()
        if len(left_values) != len(right_values):
            continue
        for test_name, test_fn in (
            ("paired_t_test", paired_t_test),
            ("wilcoxon_signed_rank", wilcoxon_signed_rank),
        ):
            try:
                result = test_fn(left_values, right_values)
            except (TypeError, ValueError):
                continue
            result["test_id"] = f"{test_name}:{left}:{right}"
            result["source_id"] = f"statistical_tests.evidence.{test_name}.{left}.{right}"
            evidence.append(result)
    return evidence


def _finite_groups(
    frame: pd.DataFrame,
    outcome: str,
    group: str,
) -> tuple[list[str], list[list[float]]] | None:
    pair = _pairwise(frame, [outcome, group])
    group_series = _as_series(pair, group)
    if group_series is None:
        return None
    labels = sorted(group_series.dropna().unique().tolist(), key=str)
    valid_labels: list[str] = []
    arrays: list[list[float]] = []
    for label in labels:
        values = pd.to_numeric(
            pair.loc[group_series == label, outcome], errors="coerce"
        ).dropna().tolist()
        if len(values) >= 2 and all(math.isfinite(float(value)) for value in values):
            valid_labels.append(str(label))
            arrays.append([float(value) for value in values])
    if len(arrays) < 2:
        return None
    return valid_labels, arrays


def _cohens_d_evidence(
    left: Sequence[float],
    right: Sequence[float],
    *,
    test_id: str,
    labels: Sequence[str],
) -> dict[str, Any]:
    effect = cohens_d(left, right)
    statistic, p_value = stats.ttest_ind(left, right, equal_var=False)
    return _evidence_result(
        test_id=test_id,
        test_type="cohens_d",
        nobs=len(left) + len(right),
        statistic=statistic,
        p_value=p_value,
        effect_size=effect,
        assumptions=[
            "independent observations",
            f"comparison is between declared groups {labels[0]} and {labels[1]}",
        ],
    )


def _effect_evidence(
    effect: dict[str, Any],
    *,
    test_id: str,
    statistic: float | None,
    p_value: float | None,
    assumptions: list[str],
) -> dict[str, Any]:
    return _evidence_result(
        test_id=test_id,
        test_type=str(effect["effect_size_name"]),
        nobs=int(effect["nobs"]),
        statistic=statistic,
        p_value=p_value,
        effect_size=effect,
        assumptions=assumptions,
    )


def _safe_variance_evidence(
    grouped: tuple[list[str], list[list[float]]],
    outcome: str,
    group: str,
) -> list[dict[str, Any]]:
    labels, arrays = grouped
    try:
        results = variance_and_normality_tests(dict(zip(labels, arrays, strict=True)))
    except ValueError:
        return []
    for result in results:
        result["test_id"] = f"{result['test_id']}:{outcome}:{group}"
        result["source_id"] = f"statistical_tests.evidence.{result['test_type']}.{outcome}.{group}"
    return results


_MAX_TEST_SUMMARIES_PER_FAMILY = 15


def summarize_statistical_tests(
    results: dict[str, dict[str, Any]],
    y: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    y_related: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for family in TEST_FAMILIES:
        if family == "evidence":
            continue
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


def _rank_correlations(frame: pd.DataFrame, left: str, right: str) -> list[dict[str, Any]]:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 3:
        return []
    rows: list[dict[str, Any]] = []
    statistic, p_value = stats.spearmanr(pair[left], pair[right])
    rows.append({
        "test_id": f"spearman_correlation:{left}:{right}",
        "test_type": "spearman_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"rho": _safe_float(statistic)},
        "source_id": f"statistical_tests.rank_correlations.spearman.{left}.{right}",
    })
    statistic, p_value = stats.kendalltau(pair[left], pair[right])
    rows.append({
        "test_id": f"kendall_correlation:{left}:{right}",
        "test_type": "kendall_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"tau": _safe_float(statistic)},
        "source_id": f"statistical_tests.rank_correlations.kendall.{left}.{right}",
    })
    return rows


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


def _mann_whitney_u(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
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


def _kruskal_wallis(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_series = _as_series(pair, group)
    if group_series is None:
        return None
    group_values = sorted(group_series.dropna().unique().tolist(), key=str)
    samples = [
        pd.to_numeric(pair.loc[group_series == value, outcome], errors="coerce").dropna()
        for value in group_values
    ]
    if len(samples) < 2 or any(len(sample) < 2 for sample in samples):
        return None
    statistic, p_value = stats.kruskal(*samples)
    group_medians = {
        str(value): float(pd.to_numeric(
            pair.loc[group_series == value, outcome], errors="coerce"
        ).median())
        for value in group_values
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


def _fisher_exact(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 2:
        return None
    table = pd.crosstab(pair[left], pair[right])
    if table.shape != (2, 2):
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


def _apply_multiple_testing_correction(results: dict[str, dict[str, Any]]) -> None:
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
        return
    _rejected, corrected, _alpha_sidak, _alpha_bonf = multipletests(
        p_values,
        method="fdr_bh",
    )
    for row, p_value_corrected in zip(rows, corrected, strict=True):
        row["p_value_corrected"] = _safe_float(p_value_corrected)
        row["correction_method"] = "fdr_bh"


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


# --- v1.8.6 independent statistical evidence slice ---


def _finite_values(values: Sequence[float], *, label: str, minimum: int = 2) -> list[float]:
    result = [float(value) for value in values]
    if len(result) < minimum:
        raise ValueError(f"{label} requires at least two observations")
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} requires finite observations")
    return result


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
    pooled_variance = (
        (len(left_values) - 1) * stats.tvar(left_values) + (len(right_values) - 1) * stats.tvar(right_values)
    ) / (len(left_values) + len(right_values) - 2)
    pooled_sd = math.sqrt(pooled_variance)
    if pooled_sd == 0:
        raise ValueError("cohens_d requires non-constant groups")
    return {
        "effect_size_name": "cohens_d",
        "value": (sum(left_values) / len(left_values) - sum(right_values) / len(right_values)) / pooled_sd,
        "pooled_sd": pooled_sd,
        "nobs": len(left_values) + len(right_values),
    }


def eta_squared(groups: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    arrays = {str(name): _finite_values(values, label=f"group {name}") for name, values in groups.items()}
    if len(arrays) < 2:
        raise ValueError("eta_squared requires at least two groups")
    all_values = [value for values in arrays.values() for value in values]
    grand_mean = sum(all_values) / len(all_values)
    between = sum(len(values) * (sum(values) / len(values) - grand_mean) ** 2 for values in arrays.values())
    total = sum((value - grand_mean) ** 2 for value in all_values)
    if total == 0:
        raise ValueError("eta_squared requires non-constant observations")
    return {"effect_size_name": "eta_squared", "value": between / total, "nobs": len(all_values)}


def omega_squared(groups: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    arrays = {str(name): _finite_values(values, label=f"group {name}") for name, values in groups.items()}
    if len(arrays) < 2:
        raise ValueError("omega_squared requires at least two groups")
    all_values = [value for values in arrays.values() for value in values]
    grand_mean = sum(all_values) / len(all_values)
    between = sum(len(values) * (sum(values) / len(values) - grand_mean) ** 2 for values in arrays.values())
    within = sum(sum((value - sum(values) / len(values)) ** 2 for value in values) for values in arrays.values())
    degrees_between = len(arrays) - 1
    degrees_within = len(all_values) - len(arrays)
    mean_within = within / degrees_within if degrees_within else 0.0
    denominator = between + within + mean_within
    value = (between - degrees_between * mean_within) / denominator if denominator else 0.0
    return {"effect_size_name": "omega_squared", "value": value, "nobs": len(all_values)}


def posthoc_anova(groups: Mapping[str, Sequence[float]], *, correction: str) -> dict[str, Any]:
    arrays = {str(name): _finite_values(values, label=f"group {name}") for name, values in groups.items()}
    if len(arrays) < 2:
        raise ValueError("posthoc_anova requires at least two groups")
    if correction not in {"tukey", "bonferroni"}:
        raise ValueError("correction must be tukey or bonferroni")
    labels = [name for name, values in arrays.items() for _ in values]
    values = [value for group in arrays.values() for value in group]
    statistic, p_value = stats.f_oneway(*arrays.values())
    comparisons: list[dict[str, Any]] = []
    if correction == "tukey":
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
        nobs=len(values),
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
    statistic, p_value = stats.ttest_rel(left_values, right_values)
    return _evidence_result(
        test_id="paired_t_test",
        test_type="paired_t_test",
        nobs=len(left_values),
        statistic=statistic,
        p_value=p_value,
        effect_size={"effect_size_name": "mean_paired_difference", "value": sum(right_values[i] - left_values[i] for i in range(len(left_values))) / len(left_values)},
        assumptions=["valid one-to-one pairing", "approximately normal paired differences"],
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
    arrays = [_finite_values(values, label=f"group {name}") for name, values in groups.items()]
    if len(arrays) < 2:
        raise ValueError("variance tests require at least two groups")
    combined = [value for values in arrays for value in values]
    levene_stat, levene_p = stats.levene(*arrays, center="median")
    bartlett_stat, bartlett_p = stats.bartlett(*arrays)
    shapiro_stat, shapiro_p = stats.shapiro(combined)
    return [
        _evidence_result(
            test_id="levene",
            test_type="levene",
            nobs=len(combined),
            statistic=levene_stat,
            p_value=levene_p,
            effect_size=None,
            assumptions=["independent observations", "groups contain at least two finite values"],
        ),
        _evidence_result(
            test_id="bartlett",
            test_type="bartlett",
            nobs=len(combined),
            statistic=bartlett_stat,
            p_value=bartlett_p,
            effect_size=None,
            assumptions=["independent observations", "approximately normal groups"],
        ),
        _evidence_result(
            test_id="shapiro_wilk",
            test_type="shapiro_wilk",
            nobs=len(combined),
            statistic=shapiro_stat,
            p_value=shapiro_p,
            effect_size=None,
            assumptions=["independent observations", "sample size is within Shapiro-Wilk operating range"],
        ),
    ]


def build_statistics_evidence_packet(
    results: Sequence[Mapping[str, Any]],
    *,
    dataset_sha256: str,
    lineage_parent: str,
    producer_code_version: str = "workbench-v1.8.6",
) -> dict[str, Any]:
    """Build the versioned, model-selection-independent statistics packet.

    The packet deliberately keeps each test result intact.  Consumers may
    summarize or display it, but this producer does not rank results or turn
    posthoc/effect-size evidence into a model-selection decision.
    """

    if (
        not isinstance(dataset_sha256, str)
        or len(dataset_sha256) != 64
        or any(character not in "0123456789abcdef" for character in dataset_sha256)
    ):
        raise ValueError("dataset_sha256 must be a lowercase sha256 digest")
    if not isinstance(lineage_parent, str) or not lineage_parent.strip():
        raise ValueError("lineage_parent is required")
    if not isinstance(producer_code_version, str) or not producer_code_version.strip():
        raise ValueError("producer_code_version is required")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)) or not results:
        raise ValueError("statistics evidence packet requires at least one result")

    normalized: list[dict[str, Any]] = []
    required = {
        "test_id",
        "test_version",
        "test_type",
        "nobs",
        "statistic",
        "p_value",
        "effect_size",
        "assumptions",
        "warnings",
    }
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("each statistical evidence result must be an object")
        missing = required - result.keys()
        if missing:
            raise ValueError(f"statistical evidence result is missing fields: {sorted(missing)}")
        if not isinstance(result["test_id"], str) or not result["test_id"].strip():
            raise ValueError("statistical evidence test_id is required")
        if result["test_version"] != 1:
            raise ValueError("unsupported statistical evidence test version")
        if not isinstance(result["test_type"], str) or not result["test_type"].strip():
            raise ValueError("statistical evidence test_type is required")
        if not isinstance(result["nobs"], int) or result["nobs"] < 2:
            raise ValueError("statistical evidence nobs must be an integer of at least two")
        if result["statistic"] is not None and not _is_finite_number(result["statistic"]):
            raise ValueError("statistical evidence statistic must be finite or null")
        if result["p_value"] is not None and not _is_finite_number(result["p_value"]):
            raise ValueError("statistical evidence p_value must be finite or null")
        if not isinstance(result["assumptions"], list) or not all(
            isinstance(item, str) for item in result["assumptions"]
        ):
            raise ValueError("statistical evidence assumptions must be a string list")
        if not isinstance(result["warnings"], list) or not all(
            isinstance(item, str) for item in result["warnings"]
        ):
            raise ValueError("statistical evidence warnings must be a string list")
        normalized_result = dict(result)
        _reject_nonfinite_values(normalized_result)
        normalized.append(normalized_result)

    packet = {
        "payload_schema": "workbench.statistics.evidence-packet",
        "schema_version": 1,
        "producer": {
            "component": "workbench.statistical_tests",
            "code_version": producer_code_version,
        },
        "dataset_ref": {"dataset_sha256": dataset_sha256},
        "lineage_parent": lineage_parent,
        "results": normalized,
        "limits": [
            "independent statistical evidence; not a model-selection decision",
        ],
    }
    from .predictive_research.schema import default_v1_prediction_registry

    return default_v1_prediction_registry().validate(packet)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _reject_nonfinite_values(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("statistical evidence cannot contain non-finite values")
    if isinstance(value, Mapping):
        for child in value.values():
            _reject_nonfinite_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_nonfinite_values(child)
