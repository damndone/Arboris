"""Immutable source audit and analysis-view preparation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
import math
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

from workbench.canonical import sha256_canonical
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.errors import (
    ArmaGarchDiagnostic,
    ArmaGarchInputError,
    diagnostic,
)


ROW_ID_COLUMN = "__wb_source_row_id__"
PARSED_TIME_COLUMN = "__wb_time__"
PARSED_VALUE_COLUMN = "__wb_value__"


@dataclass(frozen=True)
class TimeIndexAudit:
    original_row_count: int
    parsed_time_count: int
    invalid_time_count: int
    missing_time_count: int
    duplicate_timestamp_count: int
    already_sorted: bool
    minimum_time: object | None
    maximum_time: object | None
    adjacent_delta_distribution: Mapping[str, int]
    stable_frequency: bool
    inferred_frequency: str | None
    internal_gap_count: int
    timezone: str | None
    time_index_semantics: str
    lag_unit: str
    next_timestamp: str | None


@dataclass(frozen=True)
class DataQualityAudit:
    numeric_parse_failure_count: int
    missing_value_count: int
    nonfinite_value_count: int
    zero_value_count: int
    negative_value_count: int
    finite_value_count: int
    constant_series: bool
    near_constant_series: bool
    extreme_scale: bool
    estimated_candidate_count: int
    candidate_count_exceeds_sample: bool


@dataclass(frozen=True)
class AuditedAnalysisInput:
    _analysis_view: pd.DataFrame = field(repr=False)
    time_index: TimeIndexAudit
    data_quality: DataQualityAudit
    diagnostics: tuple[ArmaGarchDiagnostic, ...]
    source_hash_before: str
    source_hash_after: str
    source_unchanged: bool

    @property
    def analysis_view(self) -> pd.DataFrame:
        return self._analysis_view.copy(deep=True)


@dataclass(frozen=True)
class PreparedArmaGarchInput:
    contract: ArmaGarchAnalysisContract
    audited: AuditedAnalysisInput
    _analysis_view: pd.DataFrame = field(repr=False)
    _transformed_view: pd.DataFrame = field(repr=False)
    transform_profiles: Mapping[str, object]

    @property
    def analysis_view(self) -> pd.DataFrame:
        return self._analysis_view.copy(deep=True)

    @property
    def transformed_view(self) -> pd.DataFrame:
        return self._transformed_view.copy(deep=True)

    @property
    def selected_transform_profile(self) -> object:
        return self.transform_profiles[self.contract.transform]


def audit_time_value_input(
    source: pd.DataFrame, contract: ArmaGarchAnalysisContract
) -> AuditedAnalysisInput:
    """Audit a source frame and return a sorted copy with stable row lineage."""

    if not isinstance(source, pd.DataFrame):
        raise TypeError("source must be a pandas DataFrame")
    missing_columns = [
        column
        for column in (contract.time_column, contract.value_column)
        if column not in source.columns
    ]
    if missing_columns:
        raise ArmaGarchInputError(
            diagnostic(
                "TIME_PARSE_FAILED" if contract.time_column in missing_columns else "VALUE_PARSE_FAILED",
                f"required column {missing_columns[0]!r} is absent",
                evidence={"column": missing_columns[0]},
                impact="The requested time/value mapping cannot be audited.",
            )
        )
    collisions = {
        ROW_ID_COLUMN,
        PARSED_TIME_COLUMN,
        PARSED_VALUE_COLUMN,
    }.intersection(str(column) for column in source.columns)
    if collisions:
        raise ArmaGarchInputError(
            diagnostic(
                "VALUE_PARSE_FAILED",
                "source columns collide with reserved analysis-view columns",
                evidence={"columns": sorted(collisions)},
                impact="Stable internal lineage columns cannot be created safely.",
            )
        )

    source_hash_before = dataframe_canonical_hash(source)
    raw_time = source[contract.time_column]
    raw_value = source[contract.value_column]
    parsed_time, time_kind, timezone = _parse_time(
        raw_time, contract.time_index_semantics
    )
    parsed_value = pd.to_numeric(raw_value, errors="coerce")
    # Stable source-row identity is assigned before any exclusion so the
    # analysis view still traces back to the original rows.
    row_ids = pd.Series(
        [f"source-row:{position:010d}" for position in range(len(source))],
        index=source.index,
    )

    # Confirmed exclusion of missing observations (the Do-file's `drop if
    # missing`). This removes non-observations only; it never fills,
    # interpolates, back-fills a calendar, or aggregates.
    excluded_missing_count = 0
    if contract.missing_value_policy == "drop_missing_confirmed":
        keep = parsed_value.notna()
        excluded_missing_count = int((~keep).sum())
        if excluded_missing_count:
            raw_time = raw_time[keep]
            raw_value = raw_value[keep]
            parsed_time = parsed_time[keep]
            parsed_value = parsed_value[keep]
            row_ids = row_ids[keep]

    view = pd.DataFrame(index=parsed_value.index)
    view[contract.time_column] = parsed_time
    view[contract.value_column] = parsed_value.astype(float)
    view[ROW_ID_COLUMN] = row_ids
    view[PARSED_TIME_COLUMN] = parsed_time
    view[PARSED_VALUE_COLUMN] = parsed_value.astype(float)

    time_audit = _build_time_audit(
        raw_time, parsed_time, time_kind, timezone, contract
    )
    quality_audit = _build_quality_audit(raw_value, parsed_value, contract)
    diagnostics = _build_diagnostics(time_audit, quality_audit)
    if excluded_missing_count:
        diagnostics = (
            *diagnostics,
            diagnostic(
                "MISSING_OBSERVATIONS_EXCLUDED",
                "missing observations were excluded as confirmed by the analysis contract",
                evidence={
                    "excluded_missing_count": excluded_missing_count,
                    "policy": contract.missing_value_policy,
                },
                impact=(
                    "Excluded rows are not observations; no value was filled, "
                    "interpolated, or aggregated."
                ),
                severity="information",
            ),
        )
    view = view.sort_values(
        [PARSED_TIME_COLUMN, ROW_ID_COLUMN], kind="mergesort", na_position="last"
    ).reset_index(drop=True)
    source_hash_after = dataframe_canonical_hash(source)
    return AuditedAnalysisInput(
        _analysis_view=view,
        time_index=time_audit,
        data_quality=quality_audit,
        diagnostics=diagnostics,
        source_hash_before=source_hash_before,
        source_hash_after=source_hash_after,
        source_unchanged=source_hash_before == source_hash_after,
    )


def prepare_arma_garch_input(
    source: pd.DataFrame, contract: ArmaGarchAnalysisContract
) -> PreparedArmaGarchInput:
    """Apply all blocking gates, then materialize only the confirmed transform."""

    audited = audit_time_value_input(source, contract)
    blocking = next(
        (item for item in audited.diagnostics if item.severity == "blocking"), None
    )
    if blocking is not None:
        raise ArmaGarchInputError(blocking)

    from workbench.engine.packs.arma_garch.transforms import (
        apply_transform,
        build_transform_profiles,
    )

    profiles = build_transform_profiles(audited.analysis_view)
    selected = profiles[contract.transform]
    if not selected.eligible:
        raise ArmaGarchInputError(
            diagnostic(
                selected.ineligibility_code or "INSUFFICIENT_OBSERVATIONS",
                f"confirmed transform {contract.transform!r} is not eligible",
                evidence={
                    "transform": contract.transform,
                    "zero_value_count": audited.data_quality.zero_value_count,
                    "negative_value_count": audited.data_quality.negative_value_count,
                },
                impact="The confirmed transform cannot be computed without changing source values.",
                recommended_actions=(
                    {
                        "operation": "model.rerun",
                        "patch": {"transform": "level", "transform_confirmed": True},
                    },
                ),
            )
        )
    transformed_view = apply_transform(audited.analysis_view, contract.transform)
    return PreparedArmaGarchInput(
        contract=contract,
        audited=audited,
        _analysis_view=audited.analysis_view,
        _transformed_view=transformed_view,
        transform_profiles=MappingProxyType(dict(profiles)),
    )


def dataframe_canonical_hash(frame: pd.DataFrame) -> str:
    payload = {
        "columns": [_canonical_scalar(column) for column in frame.columns],
        "index": [_canonical_scalar(value) for value in frame.index],
        "rows": [
            [_canonical_scalar(value) for value in row]
            for row in frame.itertuples(index=False, name=None)
        ],
    }
    return sha256_canonical(payload)


def _canonical_scalar(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return {"type": "datetime", "value": pd.Timestamp(value).isoformat()}
    if type(value) is float:
        if math.isnan(value):
            return {"type": "missing"}
        if math.isinf(value):
            return {"type": "nonfinite", "value": "positive" if value > 0 else "negative"}
        return value
    if value is pd.NA or value is pd.NaT:
        return {"type": "missing"}
    if type(value) in {str, bool, int}:
        return value
    try:
        if bool(pd.isna(value)):
            return {"type": "missing"}
    except (TypeError, ValueError):
        pass
    return {"type": type(value).__name__, "value": str(value)}


def _parse_time(
    raw: pd.Series, semantics: str
) -> tuple[pd.Series, str, str | None]:
    if semantics == "observation_order":
        numeric = pd.to_numeric(raw, errors="coerce")
        if int(numeric.notna().sum()) == int(raw.notna().sum()):
            return numeric.astype(float), "numeric", None
    if pd.api.types.is_numeric_dtype(raw):
        return (
            pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns, UTC]"),
            "datetime",
            None,
        )
    parsed = pd.to_datetime(raw, errors="coerce", format="mixed", utc=True)
    return parsed, "datetime", _detect_timezone(raw)


def _detect_timezone(raw: pd.Series) -> str | None:
    dtype_tz = getattr(raw.dtype, "tz", None)
    if dtype_tz is not None:
        return str(dtype_tz)
    zones: set[str] = set()
    saw_naive = False
    for value in raw.dropna():
        tzinfo = getattr(value, "tzinfo", None)
        if tzinfo is None and isinstance(value, str):
            try:
                tzinfo = pd.Timestamp(value).tzinfo
            except (TypeError, ValueError):
                continue
        if tzinfo is not None:
            zones.add(str(tzinfo))
        else:
            saw_naive = True
    if not zones:
        return None
    if len(zones) == 1 and not saw_naive:
        return next(iter(zones))
    labels = sorted([*zones, *(["naive"] if saw_naive else [])])
    return "mixed[" + ",".join(labels) + "]"


def _build_time_audit(
    raw: pd.Series,
    parsed: pd.Series,
    time_kind: str,
    timezone: str | None,
    contract: ArmaGarchAnalysisContract,
) -> TimeIndexAudit:
    missing_count = int(raw.isna().sum())
    invalid_count = int((raw.notna() & parsed.isna()).sum())
    valid = parsed.dropna()
    duplicate_count = int(valid.duplicated(keep=False).sum())
    already_sorted = bool(valid.is_monotonic_increasing and len(valid) == len(parsed))
    ordered = valid.sort_values(kind="mergesort")
    deltas = ordered.diff().dropna()
    delta_distribution = Counter(_render_delta(value, time_kind) for value in deltas)
    inferred_frequency = _infer_frequency(ordered, time_kind)
    internal_gaps = (
        _regular_calendar_gap_count(ordered)
        if contract.time_index_semantics == "regular_calendar" and time_kind == "datetime"
        else 0
    )
    lag_unit = {
        "regular_calendar": "calendar interval",
        "business_or_trading_observations": "trading observation",
        "observation_order": "observation",
    }[contract.time_index_semantics]
    next_timestamp = _next_timestamp(
        ordered,
        inferred_frequency,
        time_kind,
        contract.time_index_semantics,
        internal_gaps,
    )
    return TimeIndexAudit(
        original_row_count=len(raw),
        parsed_time_count=int(parsed.notna().sum()),
        invalid_time_count=invalid_count,
        missing_time_count=missing_count,
        duplicate_timestamp_count=duplicate_count,
        already_sorted=already_sorted,
        minimum_time=_audit_time_value(ordered.iloc[0], time_kind) if len(ordered) else None,
        maximum_time=_audit_time_value(ordered.iloc[-1], time_kind) if len(ordered) else None,
        adjacent_delta_distribution=MappingProxyType(dict(sorted(delta_distribution.items()))),
        stable_frequency=inferred_frequency is not None and internal_gaps == 0,
        inferred_frequency=inferred_frequency if internal_gaps == 0 else None,
        internal_gap_count=internal_gaps,
        timezone=timezone,
        time_index_semantics=contract.time_index_semantics,
        lag_unit=lag_unit,
        next_timestamp=next_timestamp,
    )


def _build_quality_audit(
    raw: pd.Series, parsed: pd.Series, contract: ArmaGarchAnalysisContract
) -> DataQualityAudit:
    parse_failures = int((raw.notna() & parsed.isna()).sum())
    missing_values = int(raw.isna().sum())
    numeric = parsed.to_numpy(dtype=float, na_value=np.nan)
    nonfinite = int(np.isinf(numeric).sum())
    finite = numeric[np.isfinite(numeric)]
    zero_count = int(np.count_nonzero(finite == 0.0))
    negative_count = int(np.count_nonzero(finite < 0.0))
    constant = bool(len(finite) > 0 and np.ptp(finite) == 0.0)
    scale = max(1.0, abs(float(np.mean(finite)))) if len(finite) else 1.0
    near_constant = bool(
        len(finite) > 1 and not constant and float(np.ptp(finite)) <= scale * 1e-8
    )
    nonzero_abs = np.abs(finite[finite != 0.0])
    extreme_scale = bool(
        len(finite)
        and (
            float(np.max(np.abs(finite))) > 1e12
            or (len(nonzero_abs) and float(np.min(nonzero_abs)) < 1e-12)
        )
    )
    if contract.selection_mode == "manual":
        candidate_count = 1
    else:
        auto_mean_candidates = sum(
            1
            for p in range(contract.arma.auto_max_p + 1)
            for q in range(contract.arma.auto_max_q + 1)
            if p + q <= contract.arma.auto_max_total_order
        )
        constant_choices = 2 if contract.arma.constant_mode == "auto" else 1
        variance_candidates = (
            contract.variance.auto_arch_max_p
            + int(contract.variance.include_garch_1_1)
            + 1
        )
        candidate_count = auto_mean_candidates * constant_choices + variance_candidates
    return DataQualityAudit(
        numeric_parse_failure_count=parse_failures,
        missing_value_count=missing_values,
        nonfinite_value_count=nonfinite,
        zero_value_count=zero_count,
        negative_value_count=negative_count,
        finite_value_count=int(len(finite)),
        constant_series=constant,
        near_constant_series=near_constant,
        extreme_scale=extreme_scale,
        estimated_candidate_count=candidate_count,
        candidate_count_exceeds_sample=candidate_count > max(1, len(finite)),
    )


def _build_diagnostics(
    time: TimeIndexAudit, quality: DataQualityAudit
) -> tuple[ArmaGarchDiagnostic, ...]:
    items: list[ArmaGarchDiagnostic] = []
    if time.timezone is not None and time.timezone.startswith("mixed["):
        items.append(
            diagnostic(
                "MIXED_TIMEZONE_INPUT",
                "time column contains mixed timezone or offset semantics",
                evidence={"timezone": time.timezone},
                impact="UTC ordering is retained, but calendar interpretation requires caution.",
                severity="warning",
            )
        )
    if time.invalid_time_count or time.missing_time_count:
        items.append(
            diagnostic(
                "TIME_PARSE_FAILED",
                "time values contain missing or unparseable entries",
                evidence={
                    "invalid_time_count": time.invalid_time_count,
                    "missing_time_count": time.missing_time_count,
                },
                impact="A complete ordered analysis view cannot be created.",
            )
        )
    if quality.numeric_parse_failure_count:
        items.append(
            diagnostic(
                "VALUE_PARSE_FAILED",
                "value column contains entries that are not numeric",
                evidence={"numeric_parse_failure_count": quality.numeric_parse_failure_count},
                impact="The confirmed numeric series cannot be constructed.",
            )
        )
    if quality.missing_value_count:
        items.append(
            diagnostic(
                "VALUE_PARSE_FAILED",
                "value column contains missing entries",
                evidence={"missing_value_count": quality.missing_value_count},
                impact="v1.8 does not fill or interpolate source values.",
                recommended_actions=(
                    {
                        "operation": "model.rerun",
                        "patch": {"missing_value_policy": "drop_missing_confirmed"},
                        "reason": (
                            "Exclude the missing rows as non-observations "
                            "(no filling or interpolation)."
                        ),
                    },
                ),
            )
        )
    if time.duplicate_timestamp_count:
        items.append(
            diagnostic(
                "DUPLICATE_TIMESTAMP",
                "duplicate timestamps require an upstream data decision",
                evidence={"duplicate_timestamp_count": time.duplicate_timestamp_count},
                impact="v1.8 will not silently aggregate duplicate observations.",
            )
        )
    if quality.nonfinite_value_count:
        items.append(
            diagnostic(
                "NONFINITE_VALUES",
                "value column contains positive or negative infinity",
                evidence={"nonfinite_value_count": quality.nonfinite_value_count},
                impact="Non-finite values cannot enter transforms or estimation.",
            )
        )
    if quality.constant_series:
        items.append(
            diagnostic(
                "CONSTANT_SERIES",
                "all finite values are identical",
                evidence={"finite_value_count": quality.finite_value_count},
                impact="ARMA and conditional variance estimation are not identified.",
            )
        )
    if quality.finite_value_count < 3:
        items.append(
            diagnostic(
                "INSUFFICIENT_OBSERVATIONS",
                "at least three finite observations are required for transformation audit",
                evidence={"finite_value_count": quality.finite_value_count},
                impact="No supported transformed analysis view can be created.",
            )
        )
    if time.internal_gap_count:
        items.append(
            diagnostic(
                "INTERNAL_GAPS_UNCONFIRMED",
                "regular calendar index contains internal gaps",
                evidence={"internal_gap_count": time.internal_gap_count},
                impact="The Pack will not silently compress or fill a calendar index.",
            )
        )
    elif time.time_index_semantics == "regular_calendar" and not time.stable_frequency:
        items.append(
            diagnostic(
                "IRREGULAR_INDEX_UNCONFIRMED",
                "a stable regular-calendar frequency could not be inferred",
                evidence={"inferred_frequency": time.inferred_frequency},
                impact="A calendar lag and next timestamp cannot be stated safely.",
            )
        )
    if quality.near_constant_series:
        items.append(
            diagnostic(
                "NEAR_CONSTANT_SERIES",
                "series variation is extremely small relative to its level",
                evidence={"finite_value_count": quality.finite_value_count},
                impact="Optimization and diagnostics may be numerically fragile.",
                severity="warning",
            )
        )
    if quality.extreme_scale:
        items.append(
            diagnostic(
                "EXTREME_SCALE",
                "series has an extreme numeric scale",
                evidence={"finite_value_count": quality.finite_value_count},
                impact="Estimation may require an explicitly confirmed rescaling upstream.",
                severity="warning",
            )
        )
    if quality.candidate_count_exceeds_sample:
        items.append(
            diagnostic(
                "CANDIDATE_LIMIT_EXCEEDED",
                "the configured automatic candidate space is large relative to the sample",
                evidence={
                    "finite_value_count": quality.finite_value_count,
                    "estimated_candidate_count": quality.estimated_candidate_count,
                },
                impact="A later selection stage may shrink the candidate set or become inconclusive.",
                severity="warning",
            )
        )
    return tuple(items)


def _infer_frequency(ordered: pd.Series, time_kind: str) -> str | None:
    if len(ordered) < 3:
        return None
    if time_kind == "datetime":
        try:
            return pd.infer_freq(pd.DatetimeIndex(ordered))
        except ValueError:
            return None
    differences = np.diff(ordered.to_numpy(dtype=float))
    if len(differences) and np.allclose(differences, differences[0]):
        return "observation_step"
    return None


def _regular_calendar_gap_count(ordered: pd.Series) -> int:
    if len(ordered) < 3:
        return 0
    values = pd.DatetimeIndex(ordered).asi8
    differences = np.diff(values)
    positive = differences[differences > 0]
    if not len(positive):
        return 0
    base = int(np.min(positive))
    if base <= 0 or any(int(delta) % base for delta in positive):
        return 0
    return int(sum(max(0, int(delta) // base - 1) for delta in positive))


def _next_timestamp(
    ordered: pd.Series,
    inferred_frequency: str | None,
    time_kind: str,
    semantics: str,
    internal_gaps: int,
) -> str | None:
    if (
        not len(ordered)
        or time_kind != "datetime"
        or semantics == "observation_order"
        or inferred_frequency is None
        or internal_gaps
    ):
        return None
    try:
        next_value = pd.Timestamp(ordered.iloc[-1]) + pd.tseries.frequencies.to_offset(
            inferred_frequency
        )
    except (TypeError, ValueError):
        return None
    return _timestamp_text(next_value)


def _render_delta(value: object, time_kind: str) -> str:
    if time_kind == "datetime":
        return f"{pd.Timedelta(value).total_seconds():g}s"
    return f"{float(value):g}"


def _audit_time_value(value: object, time_kind: str) -> object:
    return _timestamp_text(pd.Timestamp(value)) if time_kind == "datetime" else float(value)


def _timestamp_text(value: pd.Timestamp) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


__all__ = [
    "AuditedAnalysisInput",
    "DataQualityAudit",
    "PARSED_TIME_COLUMN",
    "PARSED_VALUE_COLUMN",
    "PreparedArmaGarchInput",
    "ROW_ID_COLUMN",
    "TimeIndexAudit",
    "audit_time_value_input",
    "dataframe_canonical_hash",
    "prepare_arma_garch_input",
]
