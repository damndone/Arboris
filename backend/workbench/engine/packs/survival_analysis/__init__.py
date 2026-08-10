"""Bounded, non-parametric survival-analysis kernels.

The pack deliberately owns only Kaplan--Meier, log-rank, and restricted mean
survival-time calculations.  It consumes an explicit pandas frame and returns
small JSON-shaped evidence envelopes; it has no model registry or execution
side effects.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2, norm

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.survival_analysis import (
    SURVIVAL_ANALYSIS_CI_METHODS,
    SURVIVAL_ANALYSIS_OPERATION_IDS,
    SURVIVAL_ANALYSIS_TIE_POLICIES,
    SURVIVAL_ENTRY_AT_DURATION,
    SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS,
    SURVIVAL_NON_EXACT_TIME,
    SURVIVAL_NUMERIC_UNDERFLOW,
    SURVIVAL_RMST_NON_EXACT,
    SURVIVAL_REQUIRED_FIELD,
    SurvivalAnalysisRequest,
    make_result_envelope,
)


MAX_SURVIVAL_ROWS = 100_000
MAX_SURVIVAL_GROUPS = 32
MAX_SURVIVAL_TIME_POINTS = 10_000
MAX_SURVIVAL_EVENT_TIMES = 10_000
MAX_SURVIVAL_OUTPUT_POINTS = 100_000

_EPSILON = 1.0e-12
_MAX_EXACT_FLOAT_TIME = 2**53
_LOG_MIN_SUBNORMAL = math.log(float(np.nextafter(0.0, 1.0)))

_DISPATCH_FIELDS = frozenset(
    {
        "duration_column",
        "event_column",
        "entry_column",
        "group_column",
        "ci_method",
        "confidence_level",
        "tie_policy",
        "tau",
    }
)

_OPERATION_FIELDS = {
    "survival.kaplan_meier": frozenset(
        {"duration_column", "event_column", "entry_column", "group_column", "ci_method", "confidence_level", "tau"}
    ),
    "survival.log_rank": frozenset(
        {"duration_column", "event_column", "entry_column", "group_column", "tie_policy"}
    ),
    "survival.rmst": frozenset(
        {"duration_column", "event_column", "entry_column", "group_column", "ci_method", "confidence_level", "tau"}
    ),
}
_DISPATCH_DEFAULTS = {
    "ci_method": "log_log",
    "confidence_level": 0.95,
    "tie_policy": "hypergeometric",
    "tau": None,
}


class SurvivalAnalysisPackError(ValueError):
    """Stable, machine-readable validation or numerical failure."""

    def __init__(self, reason_code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.reason_code = reason_code
        self.code = reason_code
        self.details = dict(details or {})
        super().__init__(f"{reason_code}: {message}")


class _PreparedInput:
    def __init__(
        self,
        *,
        duration: np.ndarray,
        event: np.ndarray,
        entry: np.ndarray,
        group_index: np.ndarray,
        groups: list[Any],
        duration_column: str,
        event_column: str,
        entry_column: str | None,
        group_column: str | None,
    ) -> None:
        self.duration = duration
        self.event = event
        self.entry = entry
        self.group_index = group_index
        self.groups = groups
        self.duration_column = duration_column
        self.event_column = event_column
        self.entry_column = entry_column
        self.group_column = group_column


def _reject(reason_code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
    raise SurvivalAnalysisPackError(reason_code, message, details)


def _native_scalar(value: Any, field_name: str = "value") -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) is float and not math.isfinite(value):
        _reject("SURVIVAL_NONFINITE_INPUT", f"{field_name} must be finite")
    if type(value) in {str, int, bool, float} or value is None:
        return value
    _reject("SURVIVAL_GROUP_INVALID", f"{field_name} must be a JSON-safe scalar")


def _column_name(value: Any, field_name: str) -> str:
    if type(value) is not str or not value:
        _reject("SURVIVAL_BAD_INPUT", f"{field_name} must be a non-empty column name")
    return value


def _validate_options(
    *,
    ci_method: str,
    confidence_level: float,
    tie_policy: str,
) -> tuple[str, float, str]:
    if type(ci_method) is not str or ci_method not in SURVIVAL_ANALYSIS_CI_METHODS:
        _reject("SURVIVAL_INVALID_OPTION", "ci_method must be plain or log_log")
    if type(confidence_level) is bool or not isinstance(confidence_level, Real):
        _reject("SURVIVAL_CONFIDENCE_INVALID", "confidence_level must be a finite number strictly between 0 and 1")
    try:
        level = float(confidence_level)
    except (OverflowError, TypeError, ValueError) as exc:
        raise SurvivalAnalysisPackError(
            "SURVIVAL_CONFIDENCE_INVALID",
            "confidence_level must be a finite number strictly between 0 and 1",
        ) from exc
    if not math.isfinite(level) or not 0.0 < level < 1.0:
        _reject("SURVIVAL_CONFIDENCE_INVALID", "confidence_level must be a finite number strictly between 0 and 1")
    if type(tie_policy) is not str or tie_policy not in SURVIVAL_ANALYSIS_TIE_POLICIES:
        _reject("SURVIVAL_INVALID_OPTION", "tie_policy must be hypergeometric or breslow")
    return ci_method, level, tie_policy


def _validate_tau(tau: Any, *, required: bool) -> int | float | None:
    if tau is None:
        if required:
            _reject("SURVIVAL_TAU_REQUIRED", "tau must be explicitly declared")
        return None
    if type(tau) is bool or isinstance(tau, np.bool_) or not isinstance(tau, Real):
        _reject("SURVIVAL_TAU_INVALID", "tau must be a finite non-negative number")
    if isinstance(tau, (int, np.integer)):
        normalized_integer = int(tau)
        if normalized_integer < 0:
            _reject("SURVIVAL_TAU_NEGATIVE", "tau must be non-negative")
        return normalized_integer
    try:
        normalized = float(tau)
    except (OverflowError, TypeError, ValueError) as exc:
        raise SurvivalAnalysisPackError(
            "SURVIVAL_TAU_NONFINITE",
            "tau must be finite",
        ) from exc
    if not math.isfinite(normalized):
        _reject("SURVIVAL_TAU_NONFINITE", "tau must be finite")
    if normalized < 0.0:
        _reject("SURVIVAL_TAU_NEGATIVE", "tau must be non-negative")
    return normalized


def _numeric_column(frame: pd.DataFrame, name: str, *, field_name: str) -> np.ndarray:
    series = frame[name]
    if not pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype):
        _reject("SURVIVAL_NON_NUMERIC_INPUT", f"{field_name} must be numeric")
    if series.isna().any():
        _reject("SURVIVAL_NONFINITE_INPUT", f"{field_name} must be finite")
    try:
        if pd.api.types.is_integer_dtype(series.dtype):
            integer_dtype = getattr(series.dtype, "numpy_dtype", series.dtype)
            values = series.to_numpy(dtype=integer_dtype, copy=True)
        else:
            values = series.to_numpy(dtype=np.float64, na_value=np.nan)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SurvivalAnalysisPackError(
            "SURVIVAL_NON_NUMERIC_INPUT", f"{field_name} must be numeric"
        ) from exc
    if not np.isfinite(values).all():
        _reject("SURVIVAL_NONFINITE_INPUT", f"{field_name} must be finite")
    if values.dtype.kind == "f" and np.any(np.abs(values) >= _MAX_EXACT_FLOAT_TIME):
        _reject(
            SURVIVAL_NON_EXACT_TIME,
            f"{field_name} floating-point values at or above 2**53 cannot preserve adjacent integer times",
        )
    return values


def _label_key(value: Any) -> tuple[str, str]:
    return (type(value).__name__, repr(value))


def _group_values(frame: pd.DataFrame, name: str | None, n_rows: int) -> tuple[np.ndarray, list[Any]]:
    if name is None:
        return np.zeros(n_rows, dtype=np.int64), ["all"]
    series = frame[name]
    if series.isna().any():
        _reject("SURVIVAL_GROUP_MISSING", "group_column must not contain missing labels")
    normalized = [_native_scalar(value, "group label") for value in series.tolist()]
    by_key: dict[tuple[str, str], Any] = {}
    keys: list[tuple[str, str]] = []
    for value in normalized:
        key = _label_key(value)
        if key not in by_key:
            by_key[key] = value
        keys.append(key)
    ordered_keys = sorted(by_key)
    if len(ordered_keys) > MAX_SURVIVAL_GROUPS:
        _reject(
            "SURVIVAL_TOO_MANY_GROUPS",
            f"group count exceeds the bound of {MAX_SURVIVAL_GROUPS}",
        )
    positions = {key: position for position, key in enumerate(ordered_keys)}
    index = np.asarray([positions[key] for key in keys], dtype=np.int64)
    labels = [by_key[key] for key in ordered_keys]
    if any(np.count_nonzero(index == position) == 0 for position in range(len(labels))):
        _reject("SURVIVAL_GROUP_DEGENERATE", "each declared group must contain observations")
    return index, labels


def _prepare_input(
    frame: Any,
    *,
    duration_column: str,
    event_column: str,
    entry_column: str | None,
    group_column: str | None,
) -> _PreparedInput:
    if not isinstance(frame, pd.DataFrame):
        _reject("SURVIVAL_BAD_INPUT", "frame must be a pandas DataFrame")
    if len(frame) == 0:
        _reject("SURVIVAL_EMPTY_INPUT", "frame must contain at least one row")
    if len(frame) > MAX_SURVIVAL_ROWS:
        _reject("SURVIVAL_TOO_MANY_ROWS", f"rows exceed the bound of {MAX_SURVIVAL_ROWS}")
    duration_name = _column_name(duration_column, "duration_column")
    event_name = _column_name(event_column, "event_column")
    if duration_name == event_name:
        _reject("SURVIVAL_DUPLICATE_COLUMN", "duration_column and event_column must be distinct")
    optional_names = [name for name in (entry_column, group_column) if name is not None]
    optional_names = [_column_name(name, "optional column") for name in optional_names]
    selected_names = [duration_name, event_name, *optional_names]
    if len(set(selected_names)) != len(selected_names):
        _reject("SURVIVAL_DUPLICATE_COLUMN", "declared columns must be distinct")
    missing = [name for name in selected_names if name not in frame.columns]
    if missing:
        _reject("SURVIVAL_MISSING_COLUMN", "unknown column(s): " + ", ".join(missing))
    if frame.columns.duplicated().any():
        _reject("SURVIVAL_DUPLICATE_COLUMN", "frame must not contain duplicate column names")

    duration = _numeric_column(frame, duration_name, field_name="duration_column")
    if (duration < 0.0).any():
        _reject("SURVIVAL_DURATION_NEGATIVE", "duration_column must be non-negative")
    raw_event = frame[event_name]
    if pd.api.types.is_bool_dtype(raw_event.dtype) or not pd.api.types.is_numeric_dtype(raw_event.dtype):
        _reject("SURVIVAL_EVENT_NOT_BINARY", "event_column must contain strict numeric 0/1 values")
    try:
        event_float = raw_event.to_numpy(dtype=np.float64, na_value=np.nan)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SurvivalAnalysisPackError(
            "SURVIVAL_EVENT_NOT_BINARY", "event_column must contain strict numeric 0/1 values"
        ) from exc
    if not np.isfinite(event_float).all() or not np.isin(event_float, [0.0, 1.0]).all():
        _reject("SURVIVAL_EVENT_NOT_BINARY", "event_column must contain strict numeric 0/1 values")
    event = event_float.astype(bool)

    if entry_column is None:
        entry = np.zeros(len(frame), dtype=duration.dtype)
    else:
        entry = _numeric_column(frame, entry_column, field_name="entry_column")
        if (entry < 0.0).any():
            _reject("SURVIVAL_ENTRY_NEGATIVE", "entry_column must be non-negative")
        if (entry > duration).any():
            _reject("SURVIVAL_ENTRY_AFTER_DURATION", "entry_column must be less than or equal to duration_column")
        if (entry == duration).any():
            _reject(
                SURVIVAL_ENTRY_AT_DURATION,
                "entry_column must be strictly less than duration_column for delayed entry",
            )

    unique_times = np.unique(duration)
    unique_event_times = np.unique(duration[event])
    if len(unique_times) > MAX_SURVIVAL_TIME_POINTS or len(unique_event_times) > MAX_SURVIVAL_EVENT_TIMES:
        _reject(
            "SURVIVAL_TOO_MANY_TIME_POINTS",
            f"unique duration/event times exceed the configured bound",
        )
    group_index, groups = _group_values(frame, group_column, len(frame))
    return _PreparedInput(
        duration=duration,
        event=event,
        entry=entry,
        group_index=group_index,
        groups=groups,
        duration_column=duration_name,
        event_column=event_name,
        entry_column=entry_column,
        group_column=group_column,
    )


def _finite_output(value: Any, field_name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        _reject("SURVIVAL_NUMERIC_DEGENERACY", f"{field_name} is not finite")
    return normalized


def _confidence_intervals(
    survival: float,
    greenwood_se: float | None,
    *,
    z_value: float,
) -> dict[str, dict[str, float] | None]:
    if greenwood_se is None:
        return {"plain": None, "log_log": None}
    if survival <= 0.0:
        plain = {"lower": 0.0, "upper": 0.0}
        log_log = {"lower": 0.0, "upper": 0.0}
    elif survival >= 1.0:
        plain = {"lower": 1.0, "upper": 1.0}
        log_log = {"lower": 1.0, "upper": 1.0}
    else:
        plain = {
            "lower": max(0.0, min(1.0, survival - z_value * greenwood_se)),
            "upper": max(0.0, min(1.0, survival + z_value * greenwood_se)),
        }
        log_log_se = greenwood_se / (survival * abs(math.log(survival)))
        log_log_coordinate = math.log(-math.log(survival))
        lower_exponent = min(700.0, math.exp(log_log_coordinate + z_value * log_log_se))
        upper_exponent = min(700.0, math.exp(log_log_coordinate - z_value * log_log_se))
        log_log = {
            "lower": max(0.0, min(1.0, math.exp(-lower_exponent))),
            "upper": max(0.0, min(1.0, math.exp(-upper_exponent))),
        }
    return {"plain": plain, "log_log": log_log}


def _median_payload(event_table: list[dict[str, Any]]) -> dict[str, Any]:
    event_count = sum(int(row["events"]) for row in event_table)
    if event_count == 0:
        return {"estimate": None, "reason": "no_events"}
    for row in event_table:
        if row["events"] > 0 and row["survival"] <= 0.5:
            return {"estimate": _native_scalar(row["time"], "median time"), "reason": None}
    return {"estimate": None, "reason": "survival_above_half"}


def _preaggregate_event_table(
    duration: np.ndarray,
    event: np.ndarray,
    entry: np.ndarray,
    *,
    entry_inclusive: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build sorted time, risk, event, and censor tables without time scans."""

    times, inverse = np.unique(duration, return_inverse=True)
    row_counts = np.bincount(inverse, minlength=len(times)).astype(np.int64, copy=False)
    event_counts = np.zeros(len(times), dtype=np.int64)
    event_rows = np.flatnonzero(event)
    np.add.at(event_counts, inverse[event_rows], 1)
    censored_counts = row_counts - event_counts
    sorted_entry = np.sort(entry)
    sorted_duration = np.sort(duration)
    entry_side = "right" if entry_inclusive else "left"
    entered = np.searchsorted(sorted_entry, times, side=entry_side)
    ended_before = np.searchsorted(sorted_duration, times, side="left")
    risk_sets = entered - ended_before
    return times, risk_sets.astype(np.int64, copy=False), event_counts, censored_counts


def _curve(
    duration: np.ndarray,
    event: np.ndarray,
    entry: np.ndarray,
    *,
    ci_method: str,
    confidence_level: float,
    entry_inclusive: bool,
) -> dict[str, Any]:
    z_value = _finite_output(norm.ppf(0.5 + confidence_level / 2.0), "confidence quantile")
    survival = 1.0
    log_survival = 0.0
    greenwood_sum = 0.0
    greenwood_undefined = False
    event_table: list[dict[str, Any]] = []
    times, risk_sets, event_counts, censored_counts = _preaggregate_event_table(
        duration,
        event,
        entry,
        entry_inclusive=entry_inclusive,
    )
    for index, time in enumerate(times):
        time_value = _native_scalar(time, "duration time")
        risk_set = int(risk_sets[index])
        events = int(event_counts[index])
        censored = int(censored_counts[index])
        if risk_set <= 0 or events + censored <= 0:
            _reject("SURVIVAL_NUMERIC_DEGENERACY", "risk-set construction produced an impossible time point")
        greenwood_reason: str | None = (
            SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS if greenwood_undefined else None
        )
        if events:
            remaining = risk_set - events
            if remaining > 0:
                if not greenwood_undefined:
                    log_survival += math.log(remaining / risk_set)
                    if log_survival < _LOG_MIN_SUBNORMAL:
                        _reject(
                            SURVIVAL_NUMERIC_UNDERFLOW,
                            "non-zero Kaplan-Meier survival probability is below the representable float range",
                            {"time": time_value, "log_survival": log_survival},
                        )
                    survival = math.exp(log_survival)
                    if survival == 0.0:
                        _reject(
                            SURVIVAL_NUMERIC_UNDERFLOW,
                            "non-zero Kaplan-Meier survival probability underflowed",
                            {"time": time_value, "log_survival": log_survival},
                        )
                    greenwood_sum += events / (risk_set * remaining)
            else:
                survival = 0.0
                log_survival = -math.inf
                greenwood_sum = math.inf
                greenwood_undefined = True
                greenwood_reason = SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS
        if greenwood_undefined or not math.isfinite(greenwood_sum):
            greenwood_se = None
            if greenwood_reason is None:
                greenwood_reason = SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS
        else:
            if greenwood_sum == 0.0:
                greenwood_se = 0.0
            else:
                log_greenwood_se = log_survival + 0.5 * math.log(greenwood_sum)
                if log_greenwood_se < _LOG_MIN_SUBNORMAL:
                    _reject(
                        SURVIVAL_NUMERIC_UNDERFLOW,
                        "non-zero Greenwood standard error is below the representable float range",
                        {"time": time_value, "log_greenwood_se": log_greenwood_se},
                    )
                greenwood_se = math.exp(log_greenwood_se)
                if greenwood_se == 0.0 and survival > 0.0:
                    _reject(
                        SURVIVAL_NUMERIC_UNDERFLOW,
                        "non-zero Greenwood standard error underflowed",
                        {"time": time_value, "log_greenwood_se": log_greenwood_se},
                    )
        intervals = _confidence_intervals(survival, greenwood_se, z_value=z_value)
        event_table.append(
            {
                "time": time_value,
                "risk_set": risk_set,
                "n_at_risk": risk_set,
                "events": events,
                "censored": censored,
                "survival": _finite_output(survival, "survival"),
                "greenwood_se": greenwood_se,
                "standard_error": greenwood_se,
                "confidence_intervals": intervals,
                "selected_confidence_interval": intervals[ci_method],
                "confidence_interval_reason": greenwood_reason,
            }
        )
        if len(event_table) > MAX_SURVIVAL_OUTPUT_POINTS:
            _reject("SURVIVAL_TOO_MANY_TIME_POINTS", "survival output exceeds the configured bound")
    return {
        "event_table": event_table,
        "risk_set": [row["risk_set"] for row in event_table],
        "events": [row["events"] for row in event_table],
        "censored": [row["censored"] for row in event_table],
        "survival": [row["survival"] for row in event_table],
        "greenwood_se": [row["greenwood_se"] for row in event_table],
        "confidence_intervals": [row["confidence_intervals"] for row in event_table],
        "median": _median_payload(event_table),
    }


def _rmst_payload(curve: Mapping[str, Any], tau: int | float) -> dict[str, Any]:
    event_table = list(curve["event_table"])
    support_end = _native_scalar(event_table[-1]["time"], "support end")
    integer_time_domain = all(type(row["time"]) is int for row in event_table)
    exact_tau: Fraction | None = None
    if integer_time_domain:
        if type(tau) is int:
            exact_tau = Fraction(tau, 1)
        elif type(tau) is float:
            if abs(tau) >= _MAX_EXACT_FLOAT_TIME:
                _reject(
                    SURVIVAL_RMST_NON_EXACT,
                    "float tau cannot preserve integer duration precision at or above 2**53",
                    {"tau": tau},
                )
            exact_tau = Fraction.from_float(tau)
    tau_for_comparison: int | float | Fraction = exact_tau if exact_tau is not None else tau
    if tau_for_comparison > support_end:
        _reject(
            "SURVIVAL_TAU_OUT_OF_SUPPORT",
            "tau must not exceed the last observed duration for every declared group",
            {"tau": tau, "support_end": support_end},
        )
    if exact_tau is not None:
        exact_area = Fraction(0, 1)
        previous_time: int | Fraction = 0
        previous_survival = Fraction(1, 1)
        for row in event_table:
            time = int(row["time"])
            if time >= exact_tau:
                exact_area += (exact_tau - previous_time) * previous_survival
                previous_time = exact_tau
                break
            exact_area += (time - previous_time) * previous_survival
            previous_time = time
            events = int(row["events"])
            if events:
                risk_set = int(row["risk_set"])
                remaining = risk_set - events
                previous_survival = (
                    Fraction(remaining, risk_set) * previous_survival
                    if remaining > 0
                    else Fraction(0, 1)
                )
        if previous_time < exact_tau:
            exact_area += (exact_tau - previous_time) * previous_survival
        if exact_area.denominator == 1:
            area: int | float = exact_area.numerator
        else:
            candidate = float(exact_area)
            if not math.isfinite(candidate):
                _reject(SURVIVAL_RMST_NON_EXACT, "rmst cannot be represented as a finite number")
            if abs(candidate) >= _MAX_EXACT_FLOAT_TIME and Fraction.from_float(candidate) != exact_area:
                _reject(
                    SURVIVAL_RMST_NON_EXACT,
                    "rmst would lose integer-time precision when represented as float",
                    {"tau": tau},
                )
            area = candidate
    else:
        area_float = 0.0
        previous_time_float = 0.0
        previous_survival_float = 1.0
        for row in event_table:
            time_float = float(row["time"])
            if time_float >= tau:
                area_float += (float(tau) - previous_time_float) * previous_survival_float
                previous_time_float = float(tau)
                break
            area_float += (time_float - previous_time_float) * previous_survival_float
            previous_time_float = time_float
            previous_survival_float = float(row["survival"])
        if previous_time_float < tau:
            area_float += (float(tau) - previous_time_float) * previous_survival_float
        area = _finite_output(area_float, "rmst")
    return {
        "estimate": area,
        "rmst": area,
        "tau": _native_scalar(tau, "tau"),
        "support_start": 0.0,
        "support_end": support_end,
        "integrated_until": _native_scalar(tau, "tau"),
        "truncated_by_last_observation": False,
        "truncation_status": "at_support_boundary" if tau == support_end else "not_truncated",
        "tail_policy": "reject_beyond_last_observation",
    }


def _common_result(
    *,
    estimator: str,
    prepared: _PreparedInput,
    event_count: int,
    groups: list[Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "status": "completed",
        "reason_code": "ANALYSIS_COMPLETED",
        "estimator": estimator,
        "nobs": int(len(prepared.duration)),
        "event_count": int(event_count),
        "groups": list(groups),
        "duration_column": prepared.duration_column,
        "event_column": prepared.event_column,
        "entry_column": prepared.entry_column,
        "group_column": prepared.group_column,
        "policy": dict(policy),
        "provenance": {
            "runtime": "python",
            "libraries": ["numpy", "pandas", "scipy"],
            "raw_rows_returned": False,
        },
    }


def _group_curve(
    prepared: _PreparedInput,
    group_position: int,
    *,
    ci_method: str,
    confidence_level: float,
) -> dict[str, Any]:
    mask = prepared.group_index == group_position
    curve = _curve(
        prepared.duration[mask],
        prepared.event[mask],
        prepared.entry[mask],
        ci_method=ci_method,
        confidence_level=confidence_level,
        entry_inclusive=prepared.entry_column is None,
    )
    curve.update(
        {
            "group": prepared.groups[group_position],
            "nobs": int(np.count_nonzero(mask)),
            "event_count": int(np.count_nonzero(prepared.event[mask])),
        }
    )
    return curve


def _entry_policy(prepared: _PreparedInput) -> dict[str, str]:
    if prepared.entry_column is None:
        return {
            "entry_semantics": "entry_le_duration_inclusive_risk",
            "risk_set_semantics": "entry_le_time_and_duration_ge_time",
        }
    return {
        "entry_semantics": "left_truncation_entry_before_time_r_compatible",
        "risk_set_semantics": "entry_lt_time_and_duration_ge_time",
    }


def fit_kaplan_meier(
    frame: pd.DataFrame,
    *,
    duration_column: str,
    event_column: str,
    entry_column: str | None = None,
    group_column: str | None = None,
    ci_method: str = "log_log",
    confidence_level: float = 0.95,
    tau: float | None = None,
) -> dict[str, Any]:
    """Compute bounded Kaplan--Meier curves, with optional declared RMST."""

    ci_method, confidence_level, _ = _validate_options(
        ci_method=ci_method,
        confidence_level=confidence_level,
        tie_policy="hypergeometric",
    )
    tau_value = _validate_tau(tau, required=False)
    prepared = _prepare_input(
        frame,
        duration_column=duration_column,
        event_column=event_column,
        entry_column=entry_column,
        group_column=group_column,
    )
    curves: list[dict[str, Any]] = []
    for group_position, _ in enumerate(prepared.groups):
        curve = _group_curve(
            prepared,
            group_position,
            ci_method=ci_method,
            confidence_level=confidence_level,
        )
        curve["rmst"] = _rmst_payload(curve, tau_value) if tau_value is not None else None
        curve["rmst_status"] = "computed" if tau_value is not None else "not_requested"
        curves.append(curve)
    policy = {
        "ci_method": ci_method,
        "confidence_level": confidence_level,
        "tie_policy": "event_time",
        **_entry_policy(prepared),
        "median_semantics": "first_event_time_with_survival_at_or_below_half",
        "complexity": "preaggregated_event_table_sorted_risk_sweep",
        "tau": tau_value,
    }
    payload = _common_result(
        estimator="kaplan_meier",
        prepared=prepared,
        event_count=int(np.count_nonzero(prepared.event)),
        groups=prepared.groups,
        policy=policy,
    )
    payload["curves"] = curves
    if group_column is None:
        primary = curves[0]
        for field_name in (
            "event_table",
            "risk_set",
            "events",
            "censored",
            "survival",
            "greenwood_se",
            "confidence_intervals",
            "median",
            "rmst",
        ):
            payload[field_name] = primary[field_name]
    return make_result_envelope(operation_id="survival.kaplan_meier", result=payload)


def fit_rmst(
    frame: pd.DataFrame,
    *,
    duration_column: str,
    event_column: str,
    tau: float | None = None,
    entry_column: str | None = None,
    group_column: str | None = None,
    ci_method: str = "log_log",
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Integrate declared KM curves to an explicit, in-support tau."""

    ci_method, confidence_level, _ = _validate_options(
        ci_method=ci_method,
        confidence_level=confidence_level,
        tie_policy="hypergeometric",
    )
    tau_value = _validate_tau(tau, required=True)
    assert tau_value is not None
    prepared = _prepare_input(
        frame,
        duration_column=duration_column,
        event_column=event_column,
        entry_column=entry_column,
        group_column=group_column,
    )
    curves: list[dict[str, Any]] = []
    group_results: list[dict[str, Any]] = []
    for group_position, group in enumerate(prepared.groups):
        curve = _group_curve(
            prepared,
            group_position,
            ci_method=ci_method,
            confidence_level=confidence_level,
        )
        rmst = _rmst_payload(curve, tau_value)
        curve["rmst"] = rmst
        curve["rmst_status"] = "computed"
        curves.append(curve)
        group_results.append({"group": group, **rmst})
    payload = _common_result(
        estimator="restricted_mean_survival_time",
        prepared=prepared,
        event_count=int(np.count_nonzero(prepared.event)),
        groups=prepared.groups,
        policy={
            "integration": "right_continuous_kaplan_meier_step_curve",
            **_entry_policy(prepared),
            "tail_policy": "reject_beyond_last_observation",
            "complexity": "preaggregated_event_table_sorted_risk_sweep",
            "ci_method": ci_method,
            "confidence_level": confidence_level,
        },
    )
    payload.update(
        {
            "tau": tau_value,
            "group_results": group_results,
            "rmst_by_group": group_results,
            "curves": curves,
        }
    )
    if len(group_results) == 1:
        payload["rmst"] = group_results[0]["estimate"]
        payload["support"] = {
            "support_start": group_results[0]["support_start"],
            "support_end": group_results[0]["support_end"],
            "integrated_until": group_results[0]["integrated_until"],
            "truncated_by_last_observation": group_results[0]["truncated_by_last_observation"],
        }
    return make_result_envelope(operation_id="survival.rmst", result=payload)


def _preaggregate_log_rank_tables(
    prepared: _PreparedInput,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build group risk/event tables with one row sweep per declared group."""

    times, inverse = np.unique(prepared.duration, return_inverse=True)
    n_times = len(times)
    n_groups = len(prepared.groups)
    group_risk = np.zeros((n_times, n_groups), dtype=np.float64)
    group_events = np.zeros((n_times, n_groups), dtype=np.float64)
    event_rows = np.flatnonzero(prepared.event)
    np.add.at(
        group_events,
        (inverse[event_rows], prepared.group_index[event_rows]),
        1.0,
    )
    for group_position in range(n_groups):
        mask = prepared.group_index == group_position
        group_entry = np.sort(prepared.entry[mask])
        group_duration = np.sort(prepared.duration[mask])
        entry_side = "right" if prepared.entry_column is None else "left"
        entered = np.searchsorted(group_entry, times, side=entry_side)
        ended_before = np.searchsorted(group_duration, times, side="left")
        group_risk[:, group_position] = entered - ended_before
    return times, group_risk, group_events


def fit_log_rank(
    frame: pd.DataFrame,
    *,
    duration_column: str,
    event_column: str,
    group_column: str | None = None,
    entry_column: str | None = None,
    tie_policy: str = "hypergeometric",
) -> dict[str, Any]:
    """Compute a two- or bounded multi-group log-rank comparison."""

    _, _, tie_policy = _validate_options(
        ci_method="log_log",
        confidence_level=0.95,
        tie_policy=tie_policy,
    )
    if group_column is None:
        _reject("SURVIVAL_GROUP_REQUIRED", "log-rank requires an explicit group_column")
    prepared = _prepare_input(
        frame,
        duration_column=duration_column,
        event_column=event_column,
        entry_column=entry_column,
        group_column=group_column,
    )
    if len(prepared.groups) < 2:
        _reject("SURVIVAL_GROUP_DEGENERATE", "log-rank requires at least two non-empty groups")
    total_events = int(np.count_nonzero(prepared.event))
    if total_events == 0:
        _reject("SURVIVAL_NO_EVENTS", "log-rank requires at least one observed event")

    n_groups = len(prepared.groups)
    observed = np.zeros(n_groups, dtype=np.float64)
    expected = np.zeros(n_groups, dtype=np.float64)
    covariance = np.zeros((n_groups, n_groups), dtype=np.float64)
    risk_set_records: list[dict[str, Any]] = []
    times, group_risk_table, group_event_table = _preaggregate_log_rank_tables(prepared)
    for index, time in enumerate(times):
        time_value = _native_scalar(time, "duration time")
        group_risk = group_risk_table[index]
        group_events = group_event_table[index]
        total_at_risk = float(group_risk.sum())
        total_at_time = float(group_events.sum())
        if total_at_time == 0.0:
            continue
        if total_at_risk <= 0.0:
            _reject("SURVIVAL_NUMERIC_DEGENERACY", "log-rank encountered an empty risk set")
        probabilities = group_risk / total_at_risk
        expected_at_time = probabilities * total_at_time
        observed += group_events
        expected += expected_at_time
        if total_at_risk > 1.0:
            if tie_policy == "hypergeometric":
                finite_population = total_at_time * (total_at_risk - total_at_time) / (total_at_risk - 1.0)
            else:
                finite_population = total_at_time
            covariance += finite_population * (
                np.diag(probabilities) - np.outer(probabilities, probabilities)
            )
        risk_set_records.append(
            {
                "time": time_value,
                "risk_set": int(total_at_risk),
                "events": int(total_at_time),
                "observed": group_events.astype(int).tolist(),
                "expected": expected_at_time.tolist(),
            }
        )

    degrees_of_freedom = n_groups - 1
    contrast = observed[:-1] - expected[:-1]
    reduced_covariance = covariance[:-1, :-1]
    if np.linalg.matrix_rank(reduced_covariance, tol=1.0e-12) < degrees_of_freedom:
        _reject(
            "SURVIVAL_GROUP_DEGENERATE",
            "log-rank covariance is singular for the declared groups",
        )
    try:
        chi_square = float(contrast @ np.linalg.solve(reduced_covariance, contrast))
    except (np.linalg.LinAlgError, ValueError, FloatingPointError) as exc:
        raise SurvivalAnalysisPackError(
            "SURVIVAL_GROUP_DEGENERATE", "log-rank covariance could not be solved"
        ) from exc
    if not math.isfinite(chi_square):
        _reject("SURVIVAL_NUMERIC_DEGENERACY", "log-rank chi-square is not finite")
    chi_square = max(0.0, chi_square)
    p_value = float(chi2.sf(chi_square, degrees_of_freedom))
    if not math.isfinite(p_value):
        _reject("SURVIVAL_NUMERIC_DEGENERACY", "log-rank p-value is not finite")
    payload = _common_result(
        estimator="log_rank",
        prepared=prepared,
        event_count=total_events,
        groups=prepared.groups,
        policy={
            "ties": "hypergeometric_at_event_time" if tie_policy == "hypergeometric" else "breslow_event_time",
            **_entry_policy(prepared),
            "complexity": "preaggregated_group_event_table_sorted_risk_sweep",
        },
    )
    payload.update(
        {
            "tie_policy": tie_policy,
            "observed": observed.tolist(),
            "expected": expected.tolist(),
            "observed_events": observed.tolist(),
            "expected_events": expected.tolist(),
            "covariance": covariance.tolist(),
            "risk_sets": risk_set_records,
            "chi_square": chi_square,
            "degrees_of_freedom": degrees_of_freedom,
            "df": degrees_of_freedom,
            "p_value": p_value,
            "p": p_value,
        }
    )
    return make_result_envelope(operation_id="survival.log_rank", result=payload)


def run_survival_operation(
    operation_id: str,
    frame: pd.DataFrame,
    request: SurvivalAnalysisRequest | Mapping[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Dispatch only declared operation fields; typed schema defaults are neutral."""

    if type(operation_id) is not str or operation_id not in SURVIVAL_ANALYSIS_OPERATION_IDS:
        _reject("SURVIVAL_INVALID_OPTION", f"operation_id is not declared: {operation_id}")
    operation_fields = _OPERATION_FIELDS[operation_id]
    parameters: dict[str, Any] = {}
    if request is not None:
        if isinstance(request, Mapping):
            missing_request_fields = [
                field_name
                for field_name in ("duration_column", "event_column")
                if field_name not in request
            ]
            if missing_request_fields:
                _reject(
                    SURVIVAL_REQUIRED_FIELD,
                    "missing required field(s): " + ", ".join(missing_request_fields),
                )
        try:
            typed_request = request if isinstance(request, SurvivalAnalysisRequest) else SurvivalAnalysisRequest.from_mapping(request)
        except ContractError as exc:
            raise SurvivalAnalysisPackError("SURVIVAL_INVALID_OPTION", str(exc)) from exc
        request_values = typed_request.to_dict()
        inapplicable_request_fields = sorted(
            field_name
            for field_name in _DISPATCH_FIELDS - operation_fields
            if request_values.get(field_name) != _DISPATCH_DEFAULTS.get(field_name)
        )
        if inapplicable_request_fields:
            _reject(
                "SURVIVAL_INVALID_OPTION",
                "option(s) not applicable to " + operation_id + ": " + ", ".join(inapplicable_request_fields),
            )
        parameters.update({key: request_values[key] for key in operation_fields if key in request_values})
    direct_unknown = sorted(key for key in overrides if key not in _DISPATCH_FIELDS)
    if direct_unknown:
        _reject("SURVIVAL_INVALID_OPTION", "unknown option(s): " + ", ".join(direct_unknown))
    direct_inapplicable = sorted(key for key in overrides if key in _DISPATCH_FIELDS and key not in operation_fields)
    if direct_inapplicable:
        _reject(
            "SURVIVAL_INVALID_OPTION",
            "option(s) not applicable to " + operation_id + ": " + ", ".join(direct_inapplicable),
        )
    parameters.update(overrides)
    missing = [field_name for field_name in ("duration_column", "event_column") if field_name not in parameters]
    if missing:
        _reject(
            SURVIVAL_REQUIRED_FIELD,
            "missing required field(s): " + ", ".join(missing),
        )
    if operation_id == "survival.kaplan_meier":
        return fit_kaplan_meier(frame, **{key: parameters[key] for key in operation_fields if key in parameters})
    if operation_id == "survival.log_rank":
        return fit_log_rank(frame, **{key: parameters[key] for key in operation_fields if key in parameters})
    return fit_rmst(frame, **{key: parameters[key] for key in operation_fields if key in parameters})


kaplan_meier = fit_kaplan_meier
log_rank = fit_log_rank
rmst = fit_rmst
restricted_mean_survival_time = fit_rmst
run = run_survival_operation


__all__ = [
    "MAX_SURVIVAL_EVENT_TIMES",
    "MAX_SURVIVAL_GROUPS",
    "MAX_SURVIVAL_OUTPUT_POINTS",
    "MAX_SURVIVAL_ROWS",
    "MAX_SURVIVAL_TIME_POINTS",
    "SurvivalAnalysisPackError",
    "fit_kaplan_meier",
    "fit_log_rank",
    "fit_rmst",
    "kaplan_meier",
    "log_rank",
    "restricted_mean_survival_time",
    "rmst",
    "run",
    "run_survival_operation",
]
