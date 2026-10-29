from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from itertools import combinations
import logging
from pathlib import Path
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json
from .statistical_test_requests import DEFAULT_TEST_PARAMETERS, StatisticalTestRequest, TestParameter
# Kernels, scan tests and evidence builders live in statistical_test_*; the names
# callers import from this module are re-exported here.
from .statistical_test_values import CATEGORY_MAX_UNIQUE, StatisticalTestContractError
from .statistical_test_kernels import (
    cohens_d,
    _GroupSummary,
    eta_squared,
    omega_squared,
    posthoc_anova,
    one_sample_t_test,
    paired_t_test,
    wilcoxon_signed_rank,
    variance_and_normality_tests,
)
from .statistical_test_pairs import (
    _is_numeric,
    _non_null_unique,
    _is_categorical,
    _pearson,
    _rank_correlations,
    _welch_t_test,
    _mann_whitney_u,
    _anova,
    _kruskal_wallis,
    _chi_square,
    _fisher_exact,
    _apply_multiple_testing_correction,
    _involves_variable,
    _p_value_sort_key,
    _summary_row,
)
from .statistical_test_evidence import (
    _statistics_evidence_payload,
    _build_advanced_evidence_results,
    _cohens_d_evidence,
    build_statistics_evidence_packet,
)


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
    parameters: Mapping[str, TestParameter] = field(default_factory=lambda: dict(DEFAULT_TEST_PARAMETERS))

    @property
    def request(self) -> StatisticalTestRequest:
        return StatisticalTestRequest(self.parameters)


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


# Candidate cutover: 100k has functional coverage, not performance acceptance.
# Full workflow resource gates must accept this scheduling candidate separately.
_STATISTICS_PARALLEL_MIN_ROWS = 100_000


def _statistical_columns(frame, analysis_columns):
    columns = [column for column in analysis_columns if column in frame.columns]
    numeric = [column for column in columns if _is_numeric(frame[column])]
    categorical = [column for column in columns if _is_categorical(frame[column])]
    binary = [column for column in categorical if _non_null_unique(frame[column]) == 2]
    multi = [column for column in categorical
             if 3 <= _non_null_unique(frame[column]) <= CATEGORY_MAX_UNIQUE]
    return numeric, categorical, binary, multi


def _serial_statistics_for_columns(frame, numeric, categorical, binary, multi,
                                   dataset_sha256, lineage_parent, reference_means,
                                   paired_columns, check_cancel):
    results = _build_core_results(frame, numeric, categorical, binary, multi, check_cancel)
    if check_cancel is not None:
        check_cancel()
    _apply_multiple_testing_correction(results)
    advanced = _build_advanced_evidence_results(
        frame, numeric=numeric, categorical=binary + [c for c in multi if c not in binary],
        reference_means=reference_means, paired_columns=paired_columns, check_cancel=check_cancel)
    return _finish_statistical_results(results, advanced, dataset_sha256, lineage_parent, check_cancel)


def _run_statistical_tests_serial(
    frame: pd.DataFrame, *, analysis_columns: list[str],
    dataset_sha256: str | None = None, lineage_parent: str | None = None,
    reference_means: Mapping[str, float] | None = None,
    paired_columns: Sequence[tuple[str, str]] | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Direct serial reference, also used by ordinary small default workloads."""
    if check_cancel is not None:
        check_cancel()
    return _serial_statistics_for_columns(
        frame, *_statistical_columns(frame, analysis_columns), dataset_sha256, lineage_parent,
        reference_means, paired_columns, check_cancel)


def _log_statistics_secondary(primary, name, secondary):
    # Lifecycle serializes type/message; retain the secondary full traceback in
    # the existing logger without mutating a possibly frozen primary exception.
    logging.getLogger(__name__).error(
        "Concurrent statistics %s failed; preserving original %s failure",
        name, type(primary).__name__,
        exc_info=(type(secondary), secondary, secondary.__traceback__))


def _run_statistics_lanes(frame, numeric, categorical, binary, multi,
                          reference_means, paired_columns, check_cancel):
    """Own exactly the core and advanced pure computations until both exit.

    Each lane has its own shallow manager/cache and copied Context. Observation
    buffers are shared read-only. No warning filters, thread environment or
    persistence occur here; raw stderr warning order may interleave.
    """
    core_frame, advanced_frame = frame.copy(deep=False), frame.copy(deep=False)
    values, errors = [None, None], [None, None]
    completed = [threading.Event(), threading.Event()]

    def work(index):
        try:
            if index == 0:
                values[0] = _build_core_results(
                    core_frame, numeric, categorical, binary, multi, check_cancel)
            else:
                values[1] = _build_advanced_evidence_results(
                    advanced_frame, numeric=numeric,
                    categorical=binary + [c for c in multi if c not in binary],
                    reference_means=reference_means, paired_columns=paired_columns,
                    check_cancel=check_cancel)
        except BaseException as error:
            errors[index] = error
        finally:
            completed[index].set()

    workers = [threading.Thread(target=contextvars.copy_context().run, args=(work, index),
                                name=f"workbench-statistics-{name}", daemon=False)
               for index, name in enumerate(("core", "advanced"))]
    started, owner_failure = [], None
    try:
        for worker in workers:
            worker.start()
            started.append(worker)
        while not all(done.is_set() for done in completed):
            if check_cancel is not None:
                check_cancel()
            for done in completed:
                if not done.is_set():
                    done.wait(.05)
                    break
        if check_cancel is not None:
            check_cancel()
    except BaseException as error:
        owner_failure = error
    finally:
        # Existing individual SciPy/native calls are not bounded internally.
        # Returning cancellation cannot leave either actual computation alive.
        for worker in started:
            worker.join()
    if owner_failure is not None:
        from .engine.context import RunInterruptionRequested

        for name, error in zip(("core", "advanced"), errors, strict=True):
            expected_cancel = (isinstance(owner_failure, RunInterruptionRequested)
                               and isinstance(error, RunInterruptionRequested)
                               and owner_failure.reason == error.reason)
            if error is not None and not expected_cancel:
                _log_statistics_secondary(owner_failure, name, error)
        raise owner_failure
    if errors[0] is not None:
        if errors[1] is not None:
            _log_statistics_secondary(errors[0], "advanced", errors[1])
        raise errors[0]
    # Caller must run core BH before exposing advanced failure, matching serial.
    return values[0], values[1], errors[1]


def run_statistical_tests(
    frame: pd.DataFrame, *, analysis_columns: list[str],
    dataset_sha256: str | None = None, lineage_parent: str | None = None,
    reference_means: Mapping[str, float] | None = None,
    paired_columns: Sequence[tuple[str, str]] | None = None,
    check_cancel: Callable[[], None] | None = None,
) -> dict[str, dict[str, Any]]:
    if len(frame) < _STATISTICS_PARALLEL_MIN_ROWS:
        return _run_statistical_tests_serial(
            frame, analysis_columns=analysis_columns, dataset_sha256=dataset_sha256,
            lineage_parent=lineage_parent, reference_means=reference_means,
            paired_columns=paired_columns, check_cancel=check_cancel)
    if check_cancel is not None:
        check_cancel()
    numeric, categorical, binary, multi = _statistical_columns(frame, analysis_columns)
    distinct_groups = any(outcome != group for outcome in numeric for group in binary + multi)
    core_work = len(numeric) >= 2 or distinct_groups or len(categorical) >= 2
    advanced_work = (
        distinct_groups or any(column in numeric for column in (reference_means or {}))
        or any(isinstance(pair, (tuple, list)) and len(pair) == 2
               and all(isinstance(column, str) and column in numeric for column in pair)
               and pair[0] != pair[1] for pair in (paired_columns or ())))
    if not core_work or not advanced_work:
        return _serial_statistics_for_columns(
            frame, numeric, categorical, binary, multi, dataset_sha256, lineage_parent,
            reference_means, paired_columns, check_cancel)
    results, advanced, advanced_failure = _run_statistics_lanes(
        frame, numeric, categorical, binary, multi, reference_means, paired_columns, check_cancel)
    try:
        if check_cancel is not None:
            check_cancel()
        _apply_multiple_testing_correction(results)
    except BaseException as core_bh_failure:
        if advanced_failure is not None:
            _log_statistics_secondary(core_bh_failure, "advanced", advanced_failure)
        raise
    if advanced_failure is not None:
        raise advanced_failure
    return _finish_statistical_results(results, advanced, dataset_sha256, lineage_parent, check_cancel)


def _build_core_results(
    frame: pd.DataFrame,
    numeric: Sequence[str],
    categorical: Sequence[str],
    binary: Sequence[str],
    multi: Sequence[str],
    check_cancel: Callable[[], None] | None = None,
) -> dict[str, dict[str, Any]]:
    if check_cancel is not None:
        check_cancel()
    results: dict[str, dict[str, Any]] = {
        name: {
            "schema_version": 1,
            "test_type": name,
            "results": [],
            "execution_mode": "automatic_pipeline",
            "correction_scope": "automatic_core",
            "multiple_comparison_policy": (
                "Benjamini-Hochberg across the automatic eight-family core matrix."
            ),
        }
        for name in TEST_FAMILIES
    }
    for left, right in combinations(numeric, 2):
        if check_cancel is not None:
            check_cancel()
        row = _pearson(frame, left, right)
        if row is not None:
            results["correlations"]["results"].append(row)
        rank_rows = (_rank_correlations(frame, left, right, check_cancel=check_cancel)
                     if check_cancel is not None else _rank_correlations(frame, left, right))
        for rank_row in rank_rows:
            results["rank_correlations"]["results"].append(rank_row)

    for outcome in numeric:
        for group in binary:
            if outcome == group:
                continue
            if check_cancel is not None:
                check_cancel()
            row = _welch_t_test(frame, outcome, group)
            if row is not None:
                results["t_tests"]["results"].append(row)
            if check_cancel is not None:
                check_cancel()
            row = _mann_whitney_u(frame, outcome, group)
            if row is not None:
                results["nonparametric"]["results"].append(row)

    for outcome in numeric:
        for group in multi:
            if outcome == group:
                continue
            if check_cancel is not None:
                check_cancel()
            row = _anova(frame, outcome, group)
            if row is not None:
                results["anova"]["results"].append(row)
            if check_cancel is not None:
                check_cancel()
            row = _kruskal_wallis(frame, outcome, group)
            if row is not None:
                results["nonparametric"]["results"].append(row)

    for left, right in combinations(categorical, 2):
        if check_cancel is not None:
            check_cancel()
        row = _chi_square(frame, left, right)
        if row is not None:
            results["chi_square"]["results"].append(row)
        if check_cancel is not None:
            check_cancel()
        row = _fisher_exact(frame, left, right)
        if row is not None:
            results["fisher_exact"]["results"].append(row)

    return results


def _finish_statistical_results(results, advanced, dataset_sha256, lineage_parent, check_cancel):
    if check_cancel is not None:
        check_cancel()
    evidence_payload = _statistics_evidence_payload(
        advanced,
        dataset_sha256=dataset_sha256,
        lineage_parent=lineage_parent,
    )
    if advanced:
        _apply_multiple_testing_correction({"evidence": evidence_payload})
    evidence_payload["correction_scope"] = "advanced_evidence_family"
    evidence_payload["execution_mode"] = "automatic_pipeline"
    evidence_payload["multiple_comparison_policy"] = (
        "Benjamini-Hochberg within the independent advanced evidence family."
    )
    if not advanced:
        evidence_payload["correction_method"] = "not_applicable"
    results["evidence"] = evidence_payload
    if check_cancel is not None:
        check_cancel()
    return results


def run_named_statistical_test(
    frame: pd.DataFrame,
    *,
    family: str,
    analysis_columns: list[str],
    dataset_sha256: str | None = None,
    lineage_parent: str | None = None,
    reference_means: Mapping[str, float] | None = None,
    paired_columns: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Run exactly one explicitly named statistical family.

    The automatic stage remains dtype-driven and broad. This entry point is a
    separate evidence mode: its source columns are explicit, its family is
    fixed by the typed operation id, and its multiplicity correction cannot
    borrow p-values from unrelated automatic families.
    """

    if family not in TEST_FAMILIES:
        raise StatisticalTestContractError(
            f"unknown named statistical family: {family!r}; "
            "use a family published by TEST_FAMILIES"
        )
    columns = _named_analysis_columns(frame, analysis_columns)
    numeric = [column for column in columns if _is_numeric(frame[column])]
    categorical = [column for column in columns if _is_categorical(frame[column])]
    unclassified = [column for column in columns if column not in {*numeric, *categorical}]
    if unclassified:
        raise StatisticalTestContractError(
            f"named {family} analysis columns have unsupported semantic type(s): "
            + ", ".join(unclassified)
        )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "test_type": family,
        "results": [],
        "execution_mode": "named",
        "correction_scope": f"named:{family}",
        "multiple_comparison_policy": (
            f"Benjamini-Hochberg only across p-values returned by named:{family}."
        ),
    }
    if family in {"correlations", "rank_correlations"}:
        if len(numeric) < 2 or any(column not in numeric for column in columns):
            raise StatisticalTestContractError(
                f"named {family} requires at least two numeric analysis columns "
                "and no categorical columns"
            )
        for left, right in combinations(numeric, 2):
            if family == "correlations":
                row = _pearson(frame, left, right)
                if row is not None:
                    payload["results"].append(row)
            else:
                payload["results"].extend(_rank_correlations(frame, left, right))
    elif family == "t_tests":
        _require_named_group_shape(family, numeric, categorical)
        for outcome in numeric:
            for group in categorical:
                if _non_null_unique(frame[group]) == 2:
                    row = _welch_t_test(frame, outcome, group)
                    if row is not None:
                        payload["results"].append(row)
    elif family == "anova":
        _require_named_group_shape(family, numeric, categorical)
        for outcome in numeric:
            for group in categorical:
                if 3 <= _non_null_unique(frame[group]) <= CATEGORY_MAX_UNIQUE:
                    row = _anova(frame, outcome, group)
                    if row is not None:
                        payload["results"].append(row)
    elif family == "nonparametric":
        _require_named_group_shape(family, numeric, categorical)
        for outcome in numeric:
            for group in categorical:
                unique = _non_null_unique(frame[group])
                row = (
                    _mann_whitney_u(frame, outcome, group)
                    if unique == 2
                    else _kruskal_wallis(frame, outcome, group)
                    if 3 <= unique <= CATEGORY_MAX_UNIQUE
                    else None
                )
                if row is not None:
                    payload["results"].append(row)
    elif family in {"chi_square", "fisher_exact"}:
        if len(categorical) < 2 or any(column not in categorical for column in columns):
            raise StatisticalTestContractError(
                f"named {family} requires at least two categorical analysis columns "
                "and no numeric columns"
            )
        for left, right in combinations(categorical, 2):
            row = (
                _chi_square(frame, left, right)
                if family == "chi_square"
                else _fisher_exact(frame, left, right)
            )
            if row is not None:
                payload["results"].append(row)
    elif family == "evidence":
        if not numeric and not reference_means and not paired_columns:
            raise StatisticalTestContractError(
                "named evidence requires numeric analysis columns, explicit "
                "reference_means, or explicit paired_columns"
            )
        if reference_means:
            missing = sorted(set(reference_means) - set(numeric))
            if missing:
                raise StatisticalTestContractError(
                    "reference_means must name numeric analysis columns: "
                    + ", ".join(missing)
                )
        advanced = _build_advanced_evidence_results(
            frame,
            numeric=numeric,
            categorical=categorical,
            reference_means=reference_means,
            paired_columns=paired_columns,
        )
        evidence_payload = _statistics_evidence_payload(
            advanced,
            dataset_sha256=dataset_sha256,
            lineage_parent=lineage_parent,
        )
        payload.update(evidence_payload)
        payload["test_type"] = family
        payload["execution_mode"] = "named"
        payload["correction_scope"] = f"named:{family}"
        payload["multiple_comparison_policy"] = (
            f"Benjamini-Hochberg only across p-values returned by named:{family}."
        )

    corrected = _apply_multiple_testing_correction({family: payload})
    payload["correction_method"] = "fdr_bh" if corrected else "not_applicable"
    return payload


def _named_analysis_columns(frame: pd.DataFrame, analysis_columns: list[str]) -> list[str]:
    if not isinstance(analysis_columns, list) or not analysis_columns:
        raise StatisticalTestContractError(
            "named statistical tests require a non-empty analysis_columns list"
        )
    if any(not isinstance(column, str) or not column for column in analysis_columns):
        raise StatisticalTestContractError(
            "named statistical analysis_columns must contain non-empty strings"
        )
    if len(set(analysis_columns)) != len(analysis_columns):
        raise StatisticalTestContractError(
            "named statistical analysis_columns must not contain duplicates"
        )
    missing = [column for column in analysis_columns if column not in frame.columns]
    if missing:
        raise StatisticalTestContractError(
            "named statistical analysis column(s) are missing from the verified frame: "
            + ", ".join(missing)
        )
    return list(analysis_columns)


def _require_named_group_shape(
    family: str,
    numeric: Sequence[str],
    categorical: Sequence[str],
) -> None:
    if not numeric or not categorical:
        raise StatisticalTestContractError(
            f"named {family} requires at least one numeric outcome and one "
            "categorical grouping column"
        )


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



