"""Standalone, fail-closed study-level meta-analysis kernels.

The runtime is deliberately independent of statsmodels and R.  Those libraries
are useful as fixed-input verification oracles, but the formulas here are
implemented directly so the pack has explicit method and scale semantics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from scipy import stats

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.meta_analysis import (
    META_ANALYSIS_COMBINE_METHODS,
    META_ANALYSIS_COMPLETED,
    META_ANALYSIS_EFFECT_MEASURES,
    META_ANALYSIS_MAX_OUTPUT_ROWS,
    META_ANALYSIS_MAX_STUDIES,
    META_ANALYSIS_OPERATION_IDS,
    MetaAnalysisResultEnvelope,
    make_meta_analysis_envelope,
)


MAX_STUDIES = META_ANALYSIS_MAX_STUDIES
MAX_OUTPUT_ROWS = META_ANALYSIS_MAX_OUTPUT_ROWS
MAX_NUMERIC_INPUT = 1e100
MAX_PM_ITERATIONS = 200
PM_TOLERANCE = 1e-12


class MetaAnalysisPackError(ValueError):
    """Stable, machine-readable meta-analysis input or policy failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _reject(reason_code: str, message: str) -> None:
    raise MetaAnalysisPackError(reason_code, message)


def _canonical_effect_measure(value: Any) -> str:
    if type(value) is not str or not value.strip():
        _reject("META_INVALID_EFFECT_MEASURE", "effect_measure must be declared")
    aliases = {
        "direct": "direct",
        "direct_yi_vi": "direct",
        "yi_vi": "direct",
        "yi/vi": "direct",
        "mean_difference": "mean_difference",
        "mean_difference_raw": "mean_difference",
        "mean difference": "mean_difference",
        "md": "mean_difference",
        "standardized_mean_difference": "standardized_mean_difference",
        "standardized mean difference": "standardized_mean_difference",
        "smd": "standardized_mean_difference",
        "hedges_g": "standardized_mean_difference",
        "log_risk_ratio": "log_risk_ratio",
        "log risk ratio": "log_risk_ratio",
        "log_rr": "log_risk_ratio",
        "risk_ratio": "log_risk_ratio",
        "log_odds_ratio": "log_odds_ratio",
        "log odds ratio": "log_odds_ratio",
        "log_or": "log_odds_ratio",
        "odds_ratio": "log_odds_ratio",
    }
    canonical = aliases.get(value.strip().lower())
    if canonical is None or canonical not in META_ANALYSIS_EFFECT_MEASURES:
        _reject(
            "META_INVALID_EFFECT_MEASURE",
            "effect_measure is not one of the declared meta-analysis scales",
        )
    return canonical


def _canonical_method(value: Any) -> str:
    if type(value) is not str or not value.strip():
        _reject("META_INVALID_METHOD", "method must be explicitly selected")
    aliases = {
        "fixed": "fixed_effect",
        "fixed_effect": "fixed_effect",
        "fixed-effects": "fixed_effect",
        "fixed effect": "fixed_effect",
        "dl": "derSimonian_laird",
        "chi2": "derSimonian_laird",
        "der_simonian_laird": "derSimonian_laird",
        "derSimonian_laird": "derSimonian_laird",
        "dersimonian_laird": "derSimonian_laird",
        "der-simonian-laird": "derSimonian_laird",
        "paule_mandel": "paule_mandel",
        "paule-mandel": "paule_mandel",
        "pm": "paule_mandel",
        "iterated": "paule_mandel",
    }
    canonical = aliases.get(value.strip()) or aliases.get(value.strip().lower())
    if canonical is None or canonical not in META_ANALYSIS_COMBINE_METHODS:
        _reject("META_INVALID_METHOD", "method is not a declared meta-analysis method")
    return canonical


def _canonical_ci_method(
    value: Any, *, use_t: bool | None
) -> str:
    if value is None:
        if use_t is not None and type(use_t) is not bool:
            _reject("META_INVALID_CI_SEMANTICS", "use_t must be an explicit boolean")
        return "t" if use_t else "normal_z"
    if type(value) is not str or not value.strip():
        _reject("META_INVALID_CI_SEMANTICS", "ci_method must be declared")
    aliases = {
        "normal": "normal_z",
        "normal_z": "normal_z",
        "z": "normal_z",
        "t": "t",
        "student_t": "t",
        "hksj": "hksj",
        "hksj_t": "hksj",
    }
    canonical = aliases.get(value.strip().lower())
    if canonical is None:
        _reject("META_INVALID_CI_SEMANTICS", "ci_method is not declared")
    if use_t is not None and type(use_t) is not bool:
        _reject("META_INVALID_CI_SEMANTICS", "use_t must be an explicit boolean")
    if use_t is not None and use_t != (canonical in {"t", "hksj"}):
        _reject("META_CONFLICTING_CI_SEMANTICS", "use_t conflicts with ci_method")
    return canonical


def _validate_alpha(value: Any) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _reject("META_INVALID_ALPHA", "alpha must be explicitly supplied as a number")
    try:
        alpha = float(value)
    except (TypeError, ValueError, OverflowError):
        _reject("META_INVALID_ALPHA", "alpha must be finite")
    if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
        _reject("META_INVALID_ALPHA", "alpha must be strictly between 0 and 1")
    return alpha


def _finite_number(value: Any, field_name: str, *, maximum: float = MAX_NUMERIC_INPUT) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject("META_NONFINITE_VALUE", f"{field_name} must be a real number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _reject("META_NONFINITE_VALUE", f"{field_name} must be finite")
    if not math.isfinite(number):
        _reject("META_NONFINITE_VALUE", f"{field_name} must be finite")
    if abs(number) > maximum:
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} exceeds the supported numeric bound")
    return number


def _positive_variance(value: Any) -> float:
    variance = _finite_number(value, "variance")
    if variance <= 0.0:
        _reject("META_NONPOSITIVE_VARIANCE", "every study variance must be strictly positive")
    return variance


def _rows(value: Any, field_name: str = "studies") -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        _reject("META_INVALID_STUDIES", f"{field_name} must be an array of study objects")
    if not isinstance(value, Sequence):
        _reject("META_INVALID_STUDIES", f"{field_name} must be an array of study objects")
    rows = list(value)
    if len(rows) < 2:
        _reject("META_TOO_FEW_STUDIES", "at least two stable study IDs are required")
    if len(rows) > MAX_STUDIES:
        _reject("META_STUDY_COUNT_EXCEEDED", f"study count is bounded at {MAX_STUDIES}")
    if any(not isinstance(row, Mapping) for row in rows):
        _reject("META_INVALID_STUDIES", "every study must be an object")
    return rows


def _study_id(row: Mapping[str, Any]) -> str:
    if "study_id" in row and "id" in row and row["study_id"] != row["id"]:
        _reject("META_AMBIGUOUS_STUDY_ID", "study_id and id disagree")
    value = row.get("study_id", row.get("id"))
    if type(value) is not str or not value.strip():
        _reject("META_INVALID_STUDY_ID", "study_id must be a stable non-empty string")
    return value


def _prepare_ids(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    prepared: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for row in rows:
        identifier = _study_id(row)
        if identifier in seen:
            _reject("META_DUPLICATE_STUDY_ID", "study_id values must be unique")
        seen.add(identifier)
        prepared.append((identifier, row))
    return prepared


def _direct_alias_value(
    row: Mapping[str, Any], primary_name: str, alias_name: str
) -> Any:
    primary_present = primary_name in row
    alias_present = alias_name in row
    if primary_present and alias_present:
        primary = _finite_number(row[primary_name], primary_name)
        alias = _finite_number(row[alias_name], alias_name)
        if primary != alias:
            _reject(
                "META_AMBIGUOUS_DIRECT_FIELD",
                f"{primary_name} and {alias_name} must have the same value",
            )
        return primary
    if primary_present:
        return row[primary_name]
    if alias_present:
        return row[alias_name]
    return None


def _field(row: Mapping[str, Any], names: Sequence[str], label: str) -> Any:
    present = [name for name in names if name in row]
    if not present:
        _reject("META_MISSING_SUMMARY_FIELD", f"{label} is required")
    if len(present) > 1:
        first = row[present[0]]
        if any(row[name] != first for name in present[1:]):
            _reject("META_AMBIGUOUS_SUMMARY_FIELD", f"{label} has conflicting aliases")
    return row[present[0]]


def _direct_rows(studies: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for identifier, row in _prepare_ids(_rows(studies)):
        if "effect_measure" in row:
            row_measure = _canonical_effect_measure(row["effect_measure"])
            if row_measure != "direct":
                _reject("META_MIXED_EFFECT_SCALE", "study effect scales do not match direct yi/vi")
        effect = _direct_alias_value(row, "yi", "effect")
        variance = _direct_alias_value(row, "vi", "variance")
        if effect is None or variance is None:
            _reject("META_MISSING_DIRECT_FIELD", "direct studies require yi and vi")
        yi = _finite_number(effect, "yi")
        vi = _positive_variance(variance)
        normalized.append(
            {
                "study_id": identifier,
                "effect_measure": "direct",
                "effect": yi,
                "variance": vi,
                "standard_error": _safe_sqrt(vi, "standard_error"),
            }
        )
    return normalized


def _row_effect_measure(row: Mapping[str, Any], expected: str) -> None:
    if "effect_measure" not in row:
        return
    row_measure = _canonical_effect_measure(row["effect_measure"])
    if row_measure != expected:
        _reject(
            "META_MIXED_EFFECT_SCALE",
            f"study effect scale {row_measure!r} does not match {expected!r}",
        )


def _nonnegative_number(value: Any, field_name: str) -> float:
    number = _finite_number(value, field_name)
    if number < 0.0:
        _reject("META_INVALID_SUMMARY", f"{field_name} must be non-negative")
    return number


def _sample_size(value: Any, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject("META_INVALID_SAMPLE_SIZE", f"{field_name} must be an integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        _reject("META_INVALID_SAMPLE_SIZE", f"{field_name} must be finite")
    if not math.isfinite(numeric) or not numeric.is_integer():
        _reject("META_INVALID_SAMPLE_SIZE", f"{field_name} must be an integer")
    count = int(numeric)
    if count < minimum or count > MAX_NUMERIC_INPUT:
        _reject(
            "META_INVALID_SAMPLE_SIZE",
            f"{field_name} must be at least {minimum} and bounded",
        )
    return count


def _count(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject("META_INVALID_COUNT", f"{field_name} must be an integer count")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        _reject("META_INVALID_COUNT", f"{field_name} must be finite")
    if not math.isfinite(numeric) or not numeric.is_integer():
        _reject("META_INVALID_COUNT", f"{field_name} must be an integer count")
    count = int(numeric)
    if count < 0 or count > MAX_NUMERIC_INPUT:
        _reject("META_INVALID_COUNT", f"{field_name} is outside the supported count bound")
    return count


def _resolve_continuity_correction(
    continuity_correction: Any, zero_correction: Any
) -> float | None:
    if continuity_correction is not None and zero_correction is not None:
        left = _finite_number(continuity_correction, "continuity_correction")
        right = _finite_number(zero_correction, "zero_correction")
        if left != right:
            _reject(
                "META_CONFLICTING_CORRECTION",
                "continuity_correction and zero_correction disagree",
            )
        value = left
    elif continuity_correction is not None:
        value = _finite_number(continuity_correction, "continuity_correction")
    elif zero_correction is not None:
        value = _finite_number(zero_correction, "zero_correction")
    else:
        return None
    if value <= 0.0:
        _reject("META_INVALID_CORRECTION", "continuity correction must be strictly positive")
    return value


def _validate_correction_applicability(
    effect_measure: str, correction: float | None
) -> None:
    if correction is None:
        return
    if effect_measure == "direct":
        _reject("META_INVALID_OPTION", "continuity correction is not used for direct yi/vi")
    if effect_measure in {"mean_difference", "standardized_mean_difference"}:
        _reject(
            "META_INAPPLICABLE_CORRECTION",
            "continuity correction is only valid for binary effect measures",
        )


def _validate_evidence_correction(
    conversion: Mapping[str, Any], *, effect_measure: str, correction: float | None
) -> None:
    if correction is None:
        return
    _validate_correction_applicability(effect_measure, correction)
    recorded = conversion.get("continuity_correction")
    if recorded is None or float(recorded) != correction:
        _reject(
            "META_CORRECTION_MISMATCH",
            "combine correction must match the correction recorded in converted evidence",
        )


def _mean_rows(studies: Any, *, effect_measure: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for identifier, row in _prepare_ids(_rows(studies)):
        _row_effect_measure(row, effect_measure)
        mean1 = _finite_number(
            _field(row, ("mean_treatment", "mean1", "group1_mean"), "treatment mean"),
            "mean_treatment",
        )
        mean2 = _finite_number(
            _field(row, ("mean_control", "mean2", "group2_mean"), "control mean"),
            "mean_control",
        )
        sd1 = _nonnegative_number(
            _field(row, ("sd_treatment", "sd1", "std1"), "treatment standard deviation"),
            "sd_treatment",
        )
        sd2 = _nonnegative_number(
            _field(row, ("sd_control", "sd2", "std2"), "control standard deviation"),
            "sd_control",
        )
        n1 = _sample_size(
            _field(row, ("n_treatment", "n1", "nobs1"), "treatment sample size"),
            "n_treatment",
            minimum=2,
        )
        n2 = _sample_size(
            _field(row, ("n_control", "n2", "nobs2"), "control sample size"),
            "n_control",
            minimum=2,
        )
        term1 = _safe_product(sd1, sd1, "mean-difference variance") / n1
        term2 = _safe_product(sd2, sd2, "mean-difference variance") / n2
        variance = term1 + term2
        if not math.isfinite(variance) or variance <= 0.0:
            _reject("META_DEGENERATE_SUMMARY", "mean-difference variance must be positive")
        effect = mean1 - mean2
        normalized.append(
            {
                "study_id": identifier,
                "effect_measure": effect_measure,
                "effect": effect,
                "variance": variance,
                "standard_error": _safe_sqrt(variance, "standard_error"),
            }
        )
    return normalized, {
        "kind": "summary_to_effect",
        "effect_measure": effect_measure,
        "variance_semantics": "unequal_group_sampling_variance",
    }


def _standardized_mean_rows(
    studies: Any,
    *,
    effect_measure: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for identifier, row in _prepare_ids(_rows(studies)):
        _row_effect_measure(row, effect_measure)
        mean1 = _finite_number(
            _field(row, ("mean_treatment", "mean1", "group1_mean"), "treatment mean"),
            "mean_treatment",
        )
        mean2 = _finite_number(
            _field(row, ("mean_control", "mean2", "group2_mean"), "control mean"),
            "mean_control",
        )
        sd1 = _nonnegative_number(
            _field(row, ("sd_treatment", "sd1", "std1"), "treatment standard deviation"),
            "sd_treatment",
        )
        sd2 = _nonnegative_number(
            _field(row, ("sd_control", "sd2", "std2"), "control standard deviation"),
            "sd_control",
        )
        n1 = _sample_size(
            _field(row, ("n_treatment", "n1", "nobs1"), "treatment sample size"),
            "n_treatment",
            minimum=2,
        )
        n2 = _sample_size(
            _field(row, ("n_control", "n2", "nobs2"), "control sample size"),
            "n_control",
            minimum=2,
        )
        total = n1 + n2
        pooled_df = total - 2
        pooled_variance = (
            _safe_product(_safe_product(sd1, sd1, "pooled variance"), n1 - 1, "pooled variance")
            + _safe_product(_safe_product(sd2, sd2, "pooled variance"), n2 - 1, "pooled variance")
        ) / pooled_df
        if not math.isfinite(pooled_variance) or pooled_variance <= 0.0:
            _reject("META_DEGENERATE_SUMMARY", "pooled standard deviation must be positive")
        pooled_sd = _safe_sqrt(pooled_variance, "pooled standard deviation")
        correction_denominator = 4.0 * total - 9.0
        variance_denominator = total - 3.94
        if correction_denominator <= 0.0 or variance_denominator <= 0.0:
            _reject("META_DEGENERATE_SUMMARY", "standardized mean difference correction is undefined")
        raw_d = (mean1 - mean2) / pooled_sd
        bias_correction = 1.0 - 3.0 / correction_denominator
        effect = bias_correction * raw_d
        variance = total / (n1 * n2) + effect * effect / (2.0 * variance_denominator)
        if not math.isfinite(effect) or not math.isfinite(variance) or variance <= 0.0:
            _reject("META_DEGENERATE_SUMMARY", "standardized mean difference is not finite")
        normalized.append(
            {
                "study_id": identifier,
                "effect_measure": effect_measure,
                "effect": effect,
                "variance": variance,
                "standard_error": _safe_sqrt(variance, "standard_error"),
            }
        )
    return normalized, {
        "kind": "summary_to_effect",
        "effect_measure": effect_measure,
        "effect_semantics": "hedges_g_bias_corrected",
        "variance_semantics": "statsmodels_effectsize_smd_sampling_variance",
    }


def _binary_rows(
    studies: Any,
    *,
    effect_measure: str,
    continuity_correction: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    correction_applied_count = 0
    for identifier, row in _prepare_ids(_rows(studies)):
        _row_effect_measure(row, effect_measure)
        count1 = _count(
            _field(
                row,
                ("events_treatment", "event_treatment", "events1", "event1", "count1"),
                "treatment event count",
            ),
            "count1",
        )
        n1 = _count(
            _field(
                row,
                ("total_treatment", "total1", "n_treatment", "n1", "nobs1"),
                "treatment sample size",
            ),
            "nobs1",
        )
        count2 = _count(
            _field(
                row,
                ("events_control", "event_control", "events2", "event2", "count2"),
                "control event count",
            ),
            "count2",
        )
        n2 = _count(
            _field(
                row,
                ("total_control", "total2", "n_control", "n2", "nobs2"),
                "control sample size",
            ),
            "nobs2",
        )
        if n1 <= 0 or n2 <= 0 or count1 > n1 or count2 > n2:
            _reject("META_INVALID_COUNT", "event counts must lie between zero and sample size")
        zero_cell = count1 in {0, n1} or count2 in {0, n2}
        if zero_cell and continuity_correction is None:
            _reject(
                "META_ZERO_CELL_REQUIRES_CORRECTION",
                "zero cells require an explicit continuity correction",
            )
        cc = continuity_correction if zero_cell else 0.0
        if zero_cell:
            correction_applied_count += 1
        a = float(count1) + cc
        b = float(n1 - count1) + cc
        c = float(count2) + cc
        d = float(n2 - count2) + cc
        n1_adjusted = a + b
        n2_adjusted = c + d
        p1 = a / n1_adjusted
        p2 = c / n2_adjusted
        if not (0.0 < p1 < 1.0 and 0.0 < p2 < 1.0):
            _reject("META_INVALID_COUNT", "binary effect probabilities must be strictly interior")
        if effect_measure == "log_risk_ratio":
            effect = math.log(p1) - math.log(p2)
            variance = (1.0 - p1) / (p1 * n1_adjusted) + (1.0 - p2) / (p2 * n2_adjusted)
        else:
            effect = math.log(p1) - math.log(1.0 - p1) - math.log(p2) + math.log(1.0 - p2)
            variance = 1.0 / (p1 * (1.0 - p1) * n1_adjusted) + 1.0 / (
                p2 * (1.0 - p2) * n2_adjusted
            )
        if not math.isfinite(effect) or not math.isfinite(variance) or variance <= 0.0:
            _reject("META_NUMERIC_OVERFLOW", "binary effect conversion is not finite")
        normalized.append(
            {
                "study_id": identifier,
                "effect_measure": effect_measure,
                "effect": effect,
                "variance": variance,
                "standard_error": _safe_sqrt(variance, "standard_error"),
            }
        )
    return normalized, {
        "kind": "2x2_summary_to_effect",
        "effect_measure": effect_measure,
        "variance_semantics": "binomial_sampling_variance",
        "continuity_correction": continuity_correction,
        "correction_applied_count": correction_applied_count,
        "zero_cell_policy": "explicit_continuity_correction_required",
    }


def _converted_rows(
    studies: Any,
    *,
    effect_measure: str,
    continuity_correction: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if effect_measure == "direct":
        return _direct_rows(studies), {
            "kind": "direct_yi_vi",
            "effect_measure": effect_measure,
            "variance_semantics": "declared_study_level_sampling_variance",
        }
    if effect_measure == "mean_difference":
        return _mean_rows(studies, effect_measure=effect_measure)
    if effect_measure == "standardized_mean_difference":
        return _standardized_mean_rows(studies, effect_measure=effect_measure)
    if effect_measure in {"log_risk_ratio", "log_odds_ratio"}:
        return _binary_rows(
            studies,
            effect_measure=effect_measure,
            continuity_correction=continuity_correction,
        )
    _reject("META_INVALID_EFFECT_MEASURE", "effect_measure is not declared")


def _evidence_rows(
    studies: Any,
    *,
    effect_measure: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for identifier, row in _prepare_ids(_rows(studies)):
        _row_effect_measure(row, effect_measure)
        effect = row.get("effect", row.get("yi"))
        variance = row.get("variance", row.get("vi"))
        if effect is None or variance is None:
            _reject("META_MISSING_DIRECT_FIELD", "preconverted studies require effect and variance")
        effect_value = _finite_number(effect, "effect")
        variance_value = _positive_variance(variance)
        normalized.append(
            {
                "study_id": identifier,
                "effect_measure": effect_measure,
                "effect": effect_value,
                "variance": variance_value,
                "standard_error": _safe_sqrt(variance_value, "standard_error"),
            }
        )
    return normalized


def _safe_sqrt(value: float, field_name: str) -> float:
    try:
        result = math.sqrt(value)
    except (ValueError, OverflowError):
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} could not be evaluated")
    if not math.isfinite(result):
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} is not finite")
    return result


def _safe_sum(values: Sequence[float], field_name: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError):
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} overflowed")
    if not math.isfinite(result):
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} is not finite")
    return result


def _safe_product(left: float, right: float, field_name: str) -> float:
    try:
        result = left * right
    except OverflowError:
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} overflowed")
    if not math.isfinite(result):
        _reject("META_NUMERIC_OVERFLOW", f"{field_name} is not finite")
    return result


def _weights(variances: Sequence[float], tau2: float) -> list[float]:
    weights: list[float] = []
    for variance in variances:
        try:
            weight = 1.0 / (variance + tau2)
        except (OverflowError, ZeroDivisionError):
            _reject("META_NUMERIC_OVERFLOW", "inverse-variance weight could not be evaluated")
        if not math.isfinite(weight) or weight <= 0.0:
            _reject("META_NUMERIC_OVERFLOW", "inverse-variance weight is not finite")
        weights.append(weight)
    return weights


def _weighted_mean(effects: Sequence[float], weights: Sequence[float]) -> float:
    numerator = _safe_sum(
        [_safe_product(effect, weight, "weighted effect") for effect, weight in zip(effects, weights)],
        "weighted effect sum",
    )
    denominator = _safe_sum(weights, "weight sum")
    if denominator <= 0.0:
        _reject("META_NUMERIC_OVERFLOW", "weight sum must be positive")
    value = numerator / denominator
    if not math.isfinite(value):
        _reject("META_NUMERIC_OVERFLOW", "pooled effect is not finite")
    return value


def _q_statistic(effects: Sequence[float], variances: Sequence[float]) -> tuple[float, float, list[float]]:
    weights = _weights(variances, 0.0)
    pooled = _weighted_mean(effects, weights)
    q = _safe_sum(
        [
            _safe_product(weight, (effect - pooled) ** 2, "Q contribution")
            for effect, weight in zip(effects, weights)
        ],
        "Q",
    )
    return q, pooled, weights


def _der_simonian_laird_tau2(q: float, df: int, weights: Sequence[float]) -> tuple[float, float]:
    sum_weights = _safe_sum(weights, "fixed weight sum")
    sum_squared_weights = _safe_sum([weight * weight for weight in weights], "squared weight sum")
    c = sum_weights - sum_squared_weights / sum_weights
    if not math.isfinite(c) or c <= 0.0:
        _reject("META_NUMERIC_OVERFLOW", "DerSimonian-Laird denominator is not positive")
    raw = (q - df) / c
    if not math.isfinite(raw):
        _reject("META_NUMERIC_OVERFLOW", "DerSimonian-Laird estimate is not finite")
    return max(0.0, raw), raw


def _pm_q(effects: Sequence[float], variances: Sequence[float], tau2: float) -> float:
    weights = _weights(variances, tau2)
    pooled = _weighted_mean(effects, weights)
    return _safe_sum(
        [
            _safe_product(weight, (effect - pooled) ** 2, "Paule-Mandel Q contribution")
            for effect, weight in zip(effects, weights)
        ],
        "Paule-Mandel Q",
    )


def _paule_mandel_tau2(
    effects: Sequence[float], variances: Sequence[float], df: int, q_at_zero: float
) -> float:
    if q_at_zero <= df:
        return 0.0
    lower = 0.0
    upper = max(max(variances), 1.0)
    for _ in range(MAX_PM_ITERATIONS):
        if _pm_q(effects, variances, upper) <= df:
            break
        upper *= 2.0
        if not math.isfinite(upper) or upper > MAX_NUMERIC_INPUT:
            _reject("META_NUMERIC_OVERFLOW", "Paule-Mandel bracket exceeded the numeric bound")
    else:
        _reject("META_PM_NOT_CONVERGED", "Paule-Mandel bracket could not be found")

    for _ in range(MAX_PM_ITERATIONS):
        midpoint = (lower + upper) / 2.0
        q_mid = _pm_q(effects, variances, midpoint)
        if abs(q_mid - df) <= PM_TOLERANCE * max(1.0, float(df)):
            return midpoint
        if q_mid > df:
            lower = midpoint
        else:
            upper = midpoint
        if upper - lower <= PM_TOLERANCE * max(1.0, upper):
            return (lower + upper) / 2.0
    _reject("META_PM_NOT_CONVERGED", "Paule-Mandel iterations did not converge")


def _critical_value(ci_method: str, alpha: float, df: int) -> tuple[float, str]:
    if ci_method == "normal_z":
        critical = float(stats.norm.isf(alpha / 2.0))
        distribution = "normal"
    else:
        critical = float(stats.t.isf(alpha / 2.0, df))
        distribution = "student_t"
    if not math.isfinite(critical):
        _reject("META_NUMERIC_OVERFLOW", "confidence critical value is not finite")
    return critical, distribution


def _combine_core(
    normalized: Sequence[Mapping[str, Any]],
    *,
    effect_measure: str,
    method: str,
    alpha: float,
    ci_method: str,
    conversion: Mapping[str, Any],
) -> dict[str, Any]:
    effects = [float(row["effect"]) for row in normalized]
    variances = [float(row["variance"]) for row in normalized]
    study_ids = [str(row["study_id"]) for row in normalized]
    k = len(normalized)
    df = k - 1

    q, fixed_effect, fixed_weights = _q_statistic(effects, variances)
    fixed_sum_weights = _safe_sum(fixed_weights, "fixed weight sum")
    fixed_se = _safe_sqrt(1.0 / fixed_sum_weights, "fixed standard error")
    dl_tau2, dl_tau2_raw = _der_simonian_laird_tau2(q, df, fixed_weights)
    if method == "fixed_effect":
        tau2 = 0.0
    elif method == "derSimonian_laird":
        tau2 = dl_tau2
    else:
        tau2 = _paule_mandel_tau2(effects, variances, df, q)
    selected_weights = _weights(variances, tau2)
    selected_sum_weights = _safe_sum(selected_weights, "selected weight sum")
    pooled_effect = _weighted_mean(effects, selected_weights)

    scale_estimate = 1.0
    if ci_method == "hksj":
        scale_estimate = _safe_sum(
            [
                _safe_product(weight, (effect - pooled_effect) ** 2, "HKSJ scale contribution")
                for effect, weight in zip(effects, selected_weights)
            ],
            "HKSJ scale numerator",
        ) / df
        if scale_estimate < 0.0 or not math.isfinite(scale_estimate):
            _reject("META_NUMERIC_OVERFLOW", "HKSJ scale is not finite")
    pooled_se = _safe_sqrt(scale_estimate / selected_sum_weights, "pooled standard error")
    critical, distribution = _critical_value(ci_method, alpha, df)
    ci_half_width = _safe_product(critical, pooled_se, "confidence interval half-width")
    ci = {"lower": pooled_effect - ci_half_width, "upper": pooled_effect + ci_half_width}

    prediction_se = _safe_sqrt(
        scale_estimate / selected_sum_weights + tau2,
        "prediction standard error",
    )
    prediction_half_width = _safe_product(
        critical, prediction_se, "prediction interval half-width"
    )
    prediction_interval = {
        "lower": pooled_effect - prediction_half_width,
        "upper": pooled_effect + prediction_half_width,
        "standard_error": prediction_se,
        "critical_value": critical,
        "distribution": distribution,
        "tau2_included": tau2,
    }

    relative_fixed = [weight / fixed_sum_weights for weight in fixed_weights]
    relative_selected = [weight / selected_sum_weights for weight in selected_weights]
    study_evidence = []
    for row, fixed_weight, selected_weight, fixed_relative, selected_relative in zip(
        normalized,
        fixed_weights,
        selected_weights,
        relative_fixed,
        relative_selected,
    ):
        study_evidence.append(
            {
                "study_id": row["study_id"],
                "effect_measure": effect_measure,
                "effect": row["effect"],
                "variance": row["variance"],
                "standard_error": row["standard_error"],
                "fixed_weight": fixed_weight,
                "random_weight": selected_weight,
                "fixed_relative_weight": fixed_relative,
                "relative_weight": selected_relative,
                "contribution": selected_relative * row["effect"],
            }
        )

    p_value = float(stats.chi2.sf(q, df))
    i2 = 0.0 if q <= 0.0 else max(0.0, (q - df) / q)
    h2 = q / df
    method_semantics = {
        "fixed_effect": "inverse_variance_fixed_effect",
        "derSimonian_laird": "inverse_variance_random_effects_dl",
        "paule_mandel": "inverse_variance_random_effects_pm",
    }[method]
    result: dict[str, Any] = {
        "effect_measure": effect_measure,
        "method": method,
        "method_semantics": method_semantics,
        "alpha": alpha,
        "ci_method": ci_method,
        "ci_semantics": {
            "method": ci_method,
            "distribution": distribution,
            "alpha": alpha,
            "confidence_level": 1.0 - alpha,
            "degrees_of_freedom": df if distribution == "student_t" else None,
            "scale_estimator": "hksj" if ci_method == "hksj" else "unit",
            "scale": scale_estimate,
        },
        "study_count": k,
        "studies": study_evidence,
        "weights": {
            "study_ids": study_ids,
            "fixed": fixed_weights,
            "random": selected_weights,
            "selected": selected_weights,
            "relative_fixed": relative_fixed,
            "relative_selected": relative_selected,
        },
        "pooled_effect": pooled_effect,
        "pooled_se": pooled_se,
        "pooled": {"effect": pooled_effect, "se": pooled_se, "ci": ci},
        "ci": ci,
        "ci_lower": ci["lower"],
        "ci_upper": ci["upper"],
        "q": q,
        "Q": q,
        "df": df,
        "p_value": p_value,
        "p": p_value,
        "tau2": tau2,
        "tau2_raw": dl_tau2_raw,
        "i2": i2,
        "I2": i2,
        "h2": h2,
        "H2": h2,
        "heterogeneity": {
            "Q": q,
            "q": q,
            "df": df,
            "p": p_value,
            "p_value": p_value,
            "tau2": tau2,
            "tau2_raw_dl": dl_tau2_raw,
            "I2": i2,
            "i2": i2,
            "H2": h2,
            "h2": h2,
        },
        "prediction_interval": prediction_interval,
        "conversion": dict(conversion),
    }
    return result


def _leave_one_out_evidence(
    normalized: Sequence[Mapping[str, Any]],
    *,
    effect_measure: str,
    method: str,
    alpha: float,
    ci_method: str,
    conversion: Mapping[str, Any],
    full_pooled_effect: float,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for excluded_index, excluded in enumerate(normalized):
        subset = [row for index, row in enumerate(normalized) if index != excluded_index]
        summary = _combine_core(
            subset,
            effect_measure=effect_measure,
            method=method,
            alpha=alpha,
            ci_method=ci_method,
            conversion=conversion,
        )
        evidence.append(
            {
                "excluded_study_id": excluded["study_id"],
                "effect_measure": effect_measure,
                "method": method,
                "ci_method": ci_method,
                "study_count": len(subset),
                "pooled_effect": summary["pooled_effect"],
                "pooled_se": summary["pooled_se"],
                "ci": summary["ci"],
                "q": summary["q"],
                "df": summary["df"],
                "p_value": summary["p_value"],
                "tau2": summary["tau2"],
                "i2": summary["i2"],
                "h2": summary["h2"],
                "prediction_interval": summary["prediction_interval"],
                "delta_pooled_effect": summary["pooled_effect"] - full_pooled_effect,
            }
        )
    return evidence


def _source_payload(studies: Any) -> tuple[Any, Mapping[str, Any] | None]:
    if isinstance(studies, Mapping) and "operation_id" in studies:
        try:
            envelope = MetaAnalysisResultEnvelope.from_dict(studies)
        except ContractError as exc:
            _reject("META_INVALID_INPUT_ENVELOPE", str(exc))
        if envelope.operation_id != "meta.effect_size":
            _reject("META_INVALID_INPUT_ENVELOPE", "combine accepts meta.effect_size evidence only")
        payload = envelope.to_dict()["result"]
        return payload["studies"], payload["conversion"]
    if isinstance(studies, Mapping) and "studies" in studies:
        return studies["studies"], None
    return studies, None


def _source_rows(studies: Any) -> Any:
    return _source_payload(studies)[0]


def _prepare_effects(
    studies: Any,
    *,
    effect_measure: str,
    continuity_correction: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_rows, source_conversion = _source_payload(studies)
    if source_conversion is not None:
        _validate_evidence_correction(
            source_conversion,
            effect_measure=effect_measure,
            correction=continuity_correction,
        )
        normalized = _evidence_rows(source_rows, effect_measure=effect_measure)
        conversion = dict(source_conversion)
        conversion["input"] = "meta.effect_size_evidence"
        return normalized, conversion
    return _converted_rows(
        source_rows,
        effect_measure=effect_measure,
        continuity_correction=continuity_correction,
    )


def convert_effect_size(
    studies: Any = None,
    *,
    effect_measure: str | None = None,
    alpha: float | int | None = None,
    continuity_correction: float | None = None,
    zero_correction: float | None = None,
) -> dict[str, Any]:
    """Convert study summaries into a declared effect/variance scale."""

    measure = _canonical_effect_measure(effect_measure)
    alpha_value = _validate_alpha(alpha)
    correction = _resolve_continuity_correction(continuity_correction, zero_correction)
    _validate_correction_applicability(measure, correction)
    source_rows, source_conversion = _source_payload(studies)
    if source_conversion is not None:
        _reject("META_INVALID_INPUT_ENVELOPE", "effect-size conversion cannot re-convert evidence")
    normalized, conversion = _converted_rows(
        source_rows,
        effect_measure=measure,
        continuity_correction=correction,
    )
    public_studies = [
        {**row, "yi": row["effect"], "vi": row["variance"]}
        for row in normalized
    ]
    result = {
        "effect_measure": measure,
        "alpha": alpha_value,
        "study_count": len(normalized),
        "studies": public_studies,
        "conversion": conversion,
    }
    return make_meta_analysis_envelope(
        operation_id="meta.effect_size",
        status="completed",
        reason_code=META_ANALYSIS_COMPLETED,
        result=result,
    )


def combine_effects(
    studies: Any = None,
    *,
    effect_measure: str | None = None,
    method: str | None = None,
    alpha: float | int | None = None,
    ci_method: str | None = None,
    use_t: bool | None = None,
    leave_one_out: bool = False,
    max_leave_one_out: int | None = None,
    continuity_correction: float | None = None,
    zero_correction: float | None = None,
    effects: Sequence[Any] | None = None,
    variances: Sequence[Any] | None = None,
    study_ids: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Combine study-level effects using one explicitly selected method."""

    measure = _canonical_effect_measure(effect_measure)
    method_value = _canonical_method(method)
    alpha_value = _validate_alpha(alpha)
    ci_method_value = _canonical_ci_method(ci_method, use_t=use_t)
    if type(leave_one_out) is not bool:
        _reject("META_INVALID_OPTION", "leave_one_out must be an explicit boolean")
    if max_leave_one_out is not None and (
        type(max_leave_one_out) is not int
        or isinstance(max_leave_one_out, bool)
        or not 1 <= max_leave_one_out <= MAX_OUTPUT_ROWS
    ):
        _reject(
            "META_OUTPUT_COUNT_EXCEEDED",
            f"max_leave_one_out must be an integer in [1, {MAX_OUTPUT_ROWS}]",
        )
    correction = _resolve_continuity_correction(continuity_correction, zero_correction)
    _validate_correction_applicability(measure, correction)

    supplied_vectors = any(value is not None for value in (effects, variances, study_ids))
    if supplied_vectors:
        if studies is not None or effects is None or variances is None or study_ids is None:
            _reject(
                "META_INVALID_STUDIES",
                "effects, variances, and study_ids must be supplied together",
            )
        if not (
            isinstance(effects, Sequence)
            and isinstance(variances, Sequence)
            and isinstance(study_ids, Sequence)
        ):
            _reject("META_INVALID_STUDIES", "effects, variances, and study_ids must be arrays")
        if not (len(effects) == len(variances) == len(study_ids)):
            _reject("META_INVALID_STUDIES", "effect arrays must have equal lengths")
        studies = [
            {"study_id": identifier, "yi": effect, "vi": variance}
            for identifier, effect, variance in zip(study_ids, effects, variances)
        ]
    elif studies is None:
        _reject("META_INVALID_STUDIES", "studies must be supplied")

    if supplied_vectors and measure != "direct":
        _reject("META_INVALID_STUDIES", "effect vectors are accepted only on the direct scale")
    normalized, conversion = _prepare_effects(
        studies,
        effect_measure=measure,
        continuity_correction=correction,
    )
    result = _combine_core(
        normalized,
        effect_measure=measure,
        method=method_value,
        alpha=alpha_value,
        ci_method=ci_method_value,
        conversion=conversion,
    )
    if leave_one_out:
        if len(normalized) <= 2:
            _reject(
                "META_LOO_TOO_FEW_STUDIES",
                "leave-one-out requires at least three input studies",
            )
        loo_limit = MAX_OUTPUT_ROWS if max_leave_one_out is None else max_leave_one_out
        if len(normalized) > loo_limit:
            _reject(
                "META_OUTPUT_COUNT_EXCEEDED",
                "leave-one-out output would exceed its explicit bound",
            )
        result["leave_one_out"] = _leave_one_out_evidence(
            normalized,
            effect_measure=measure,
            method=method_value,
            alpha=alpha_value,
            ci_method=ci_method_value,
            conversion=conversion,
            full_pooled_effect=result["pooled_effect"],
        )
        result["influence"] = {
            "kind": "leave_one_out",
            "bounded": True,
            "row_count": len(result["leave_one_out"]),
            "leave_one_out": result["leave_one_out"],
        }
    if len(result["studies"]) > MAX_OUTPUT_ROWS:
        _reject("META_OUTPUT_COUNT_EXCEEDED", "study evidence exceeds the output bound")
    return make_meta_analysis_envelope(
        operation_id="meta.combine",
        status="completed",
        reason_code=META_ANALYSIS_COMPLETED,
        result=result,
    )


combine_meta_analysis = combine_effects
convert_meta_effect_size = convert_effect_size


__all__ = [
    "MAX_NUMERIC_INPUT",
    "MAX_OUTPUT_ROWS",
    "MAX_STUDIES",
    "MetaAnalysisPackError",
    "combine_effects",
    "combine_meta_analysis",
    "convert_effect_size",
    "convert_meta_effect_size",
]
