"""Statistics evidence packets: advanced evidence results, effect and variance evidence, finite-value checks."""

from __future__ import annotations

import math
from itertools import combinations
from collections.abc import Callable, Mapping, Sequence
from typing import Any
import numpy as np
import pandas as pd

from .statistical_test_values import StatisticalTestContractError
from .statistical_test_kernels import _GroupSummary, _cohens_d_from, _evidence_result, _welch_from, _welch_t_statistics, cohens_d, eta_squared, omega_squared, one_sample_t_test, paired_t_test, posthoc_anova, variance_and_normality_tests, wilcoxon_signed_rank
from .statistical_test_pairs import _PreparedGroups, _anova, _pairwise


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
    check_cancel: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    if paired_columns is not None:
        for pair in paired_columns:
            if check_cancel is not None:
                check_cancel()
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
            if check_cancel is not None:
                check_cancel()
            prepared = _PreparedGroups(frame, outcome, group)
            grouped = _finite_groups(frame, outcome, group, check_cancel=check_cancel, prepared=prepared)
            if grouped is None:
                del prepared
                continue
            labels, arrays = grouped
            group_map = dict(zip(labels, arrays, strict=True))
            summaries = [_GroupSummary(values) for values in arrays]
            for left_index, right_index in combinations(range(len(arrays)), 2):
                if check_cancel is not None:
                    check_cancel()
                try:
                    evidence.append(
                        _cohens_d_evidence(
                            summaries[left_index],
                            summaries[right_index],
                            test_id=(
                                f"cohens_d:{outcome}:{group}:"
                                f"{labels[left_index]}:{labels[right_index]}"
                            ),
                            labels=(labels[left_index], labels[right_index]),
                        )
                    )
                except ValueError:
                    continue
            if check_cancel is not None:
                check_cancel()
            if len(arrays) >= 3:
                try:
                    posthoc = posthoc_anova(group_map, correction="tukey")
                    posthoc["test_id"] = f"anova_posthoc:{outcome}:{group}"
                    posthoc["source_id"] = f"statistical_tests.evidence.anova_posthoc.{outcome}.{group}"
                    evidence.append(posthoc)
                    anova = _anova(frame, outcome, group, prepared=prepared)
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
            if check_cancel is not None:
                check_cancel()
            evidence.extend(_safe_variance_evidence(grouped, outcome, group))
            del prepared

    for column, population_mean in (reference_means or {}).items():
        if check_cancel is not None:
            check_cancel()
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
        if check_cancel is not None:
            check_cancel()
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
            if check_cancel is not None:
                check_cancel()
            try:
                result = test_fn(left_values, right_values)
            except (TypeError, ValueError):
                continue
            result["test_id"] = f"{test_name}:{left}:{right}"
            result["source_id"] = f"statistical_tests.evidence.{test_name}.{left}.{right}"
            # Name the direction and give both means, as Stata's ttest a == b prints them: QRData 109
            # (3724e8b2 round) read a negative 1948-minus-2018 difference as fewer days in 2018.
            result["difference"] = f"{left} minus {right}"
            result["means"] = {left: math.fsum(left_values) / len(left_values),
                               right: math.fsum(right_values) / len(right_values)}
            evidence.append(result)
    if check_cancel is not None:
        check_cancel()
    return evidence


def _finite_groups(
    frame: pd.DataFrame,
    outcome: str,
    group: str,
    *,
    check_cancel: Callable[[], None] | None = None,
    prepared: _PreparedGroups | None = None,
) -> tuple[list[str], list[np.ndarray]] | None:
    if prepared is None:
        prepared = _PreparedGroups(frame, outcome, group)
    if prepared.group_series is None:
        return None
    labels = prepared.labels
    valid_labels: list[str] = []
    arrays: list[np.ndarray] = []
    for index, label in enumerate(labels):
        if check_cancel is not None:
            check_cancel()
        values = prepared.sample(index).to_numpy(dtype=float)
        if len(values) >= 2 and bool(np.isfinite(values).all()):
            valid_labels.append(str(label))
            arrays.append(values)
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
    if isinstance(left, _GroupSummary):
        # Groups from _finite_groups: finite floats, at least two each.
        effect = _cohens_d_from(left, right)
        statistic, p_value, warning_codes = _welch_from(left, right)
        nobs = left.n + right.n
    else:
        effect = cohens_d(left, right)
        statistic, p_value, warning_codes = _welch_t_statistics(left, right)
        nobs = len(left) + len(right)
    return _evidence_result(
        test_id=test_id,
        test_type="cohens_d",
        nobs=nobs,
        statistic=statistic,
        p_value=p_value,
        effect_size=effect,
        assumptions=[
            "independent observations",
            f"comparison is between declared groups {labels[0]} and {labels[1]}",
        ],
        warnings=warning_codes,
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
    grouped: tuple[list[str], list[np.ndarray]],
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
