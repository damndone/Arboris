"""Model options and fail-closed input preparation for the ETS pack.

Point 4 of the locked contract is implemented here: complete-case on the
modelled series is allowed only at the edges of the sample and is counted, while
any interior gap — a missing modelled value or a hole in the time index — is
blocking, because exponential smoothing over an implicit gap silently changes
the meaning of the time index.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from workbench.canonical import sha256_canonical
from workbench.contracts.model.ets import ETSContractError, ETSSpecification

from .errors import ETSInputError, diagnostic


_REQUIRED_OPTION_KEYS = frozenset(
    {"time_column", "value_column", "error", "trend", "seasonal"}
)
_OPTIONAL_OPTION_KEYS = frozenset({"seasonal_periods", "damped_trend"})

MIN_NON_SEASONAL_OBSERVATIONS = 10
SEASONAL_OBSERVATION_MARGIN = 5


@dataclass(frozen=True)
class ETSModelOptions:
    """The validated public options of one ETS estimation request."""

    time_column: str
    value_column: str
    specification: ETSSpecification

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ETSModelOptions":
        if not isinstance(value, Mapping):
            raise ETSContractError("ets model_options must be a mapping")
        keys = set(value)
        if any(type(key) is not str for key in keys):
            raise ETSContractError("ets model_options keys must be strings")
        missing = _REQUIRED_OPTION_KEYS - keys
        if missing:
            raise ETSContractError(
                "missing ets model_options field: " + ", ".join(sorted(missing))
            )
        unknown = keys - _REQUIRED_OPTION_KEYS - _OPTIONAL_OPTION_KEYS
        if unknown:
            raise ETSContractError(
                "unknown ets model_options field: " + ", ".join(sorted(unknown))
            )
        for column_key in ("time_column", "value_column"):
            column = value[column_key]
            if type(column) is not str or not column:
                raise ETSContractError(f"{column_key} must be a non-empty string")
        seasonal_periods = value.get("seasonal_periods")
        if seasonal_periods is not None:
            if type(seasonal_periods) is not int or seasonal_periods < 2:
                raise ETSContractError("seasonal_periods must be an int >= 2")
        damped_trend = value.get("damped_trend", False)
        if type(damped_trend) is not bool:
            raise ETSContractError("damped_trend must be a boolean")
        specification = ETSSpecification(
            error=value["error"],
            trend=value["trend"],
            seasonal=value["seasonal"],
            seasonal_periods=seasonal_periods,
            damped_trend=damped_trend,
        )
        if specification.seasonal is None and seasonal_periods is not None:
            raise ETSContractError(
                "seasonal_periods is only allowed with a seasonal component"
            )
        return cls(
            time_column=value["time_column"],
            value_column=value["value_column"],
            specification=specification,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.specification.to_dict()
        payload.pop("canonical")
        payload.update(
            {"time_column": self.time_column, "value_column": self.value_column}
        )
        return payload


@dataclass(frozen=True)
class ETSSampleAudit:
    """Counted, reportable facts about how the modelled sample was formed."""

    source_row_count: int
    n_obs: int
    n_excluded: int
    exclusion_reasons: Mapping[str, int]
    first_timestamp: str
    last_timestamp: str
    inferred_step_seconds: float


@dataclass(frozen=True)
class PreparedETSInput:
    """The modelled series plus every fact the estimator is allowed to use."""

    options: ETSModelOptions
    endog: np.ndarray = field(repr=False)
    audit: ETSSampleAudit
    sample_fingerprint: str


def _block(code: str, message: str, *, evidence: Mapping[str, object], impact: str):
    raise ETSInputError(
        diagnostic(code, message, evidence=evidence, impact=impact)
    )


def _parse_time(frame: pd.DataFrame, options: ETSModelOptions) -> pd.Series:
    raw = frame[options.time_column]
    parsed = pd.to_datetime(raw, errors="coerce", utc=False)
    invalid = int(parsed.isna().sum())
    if invalid:
        _block(
            "ETS_TIME_PARSE_FAILED",
            f"{invalid} row(s) of {options.time_column!r} are not parseable timestamps",
            evidence={"column": options.time_column, "invalid_count": invalid},
            impact="The time index cannot be established, so no ETS sample exists.",
        )
    return parsed


def prepare_ets_input(
    frame: pd.DataFrame, options: ETSModelOptions
) -> PreparedETSInput:
    """Validate the request and return an estimable, gap-free modelled series."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    absent = [
        column
        for column in (options.time_column, options.value_column)
        if column not in frame.columns
    ]
    if absent:
        _block(
            "ETS_INPUT_COLUMN_MISSING",
            f"required column {absent[0]!r} is absent",
            evidence={"column": absent[0]},
            impact="The requested time/value mapping cannot be read.",
        )

    source_row_count = int(len(frame))
    parsed_time = _parse_time(frame, options)
    duplicate_count = int(parsed_time.duplicated().sum())
    if duplicate_count:
        _block(
            "ETS_DUPLICATE_TIMESTAMP",
            f"{duplicate_count} duplicate timestamp(s) in {options.time_column!r}",
            evidence={
                "column": options.time_column,
                "duplicate_count": duplicate_count,
            },
            impact="A duplicated timestamp makes the smoothing recursion ambiguous.",
        )

    values = pd.to_numeric(frame[options.value_column], errors="coerce")
    ordered = (
        pd.DataFrame({"time": parsed_time.to_numpy(), "value": values.to_numpy()})
        .sort_values("time", kind="mergesort")
        .reset_index(drop=True)
    )
    non_finite_mask = ~np.isfinite(ordered["value"].to_numpy(dtype=float))
    present = np.flatnonzero(~non_finite_mask)
    if present.size == 0:
        _block(
            "ETS_NO_MODELLED_OBSERVATIONS",
            f"column {options.value_column!r} has no finite observation",
            evidence={"column": options.value_column, "source_rows": source_row_count},
            impact="There is nothing to smooth.",
        )
    first, last = int(present[0]), int(present[-1])
    interior_missing = [
        index for index in range(first, last + 1) if bool(non_finite_mask[index])
    ]
    if interior_missing:
        _block(
            "ETS_INTERIOR_MISSING_VALUE",
            f"{len(interior_missing)} interior missing value(s) in "
            f"{options.value_column!r}",
            evidence={
                "column": options.value_column,
                "interior_missing_count": len(interior_missing),
                "first_missing_timestamp": str(
                    ordered["time"].iloc[interior_missing[0]]
                ),
            },
            impact=(
                "Smoothing across an interior gap would silently change the time "
                "index; the sample must be repaired or truncated first."
            ),
        )

    exclusion_reasons: dict[str, int] = {}
    if first:
        exclusion_reasons["leading_missing_value"] = first
    trailing = len(ordered) - 1 - last
    if trailing:
        exclusion_reasons["trailing_missing_value"] = int(trailing)

    modelled = ordered.iloc[first : last + 1].reset_index(drop=True)
    times = pd.to_datetime(modelled["time"])
    deltas = times.diff().dropna()
    step_seconds = 0.0
    if len(deltas):
        unique_deltas = deltas.unique()
        step = deltas.mode().iloc[0]
        step_seconds = float(pd.Timedelta(step).total_seconds())
        if len(unique_deltas) > 1:
            multiples = all(
                float(pd.Timedelta(delta).total_seconds()) % step_seconds == 0.0
                for delta in unique_deltas
            ) if step_seconds else False
            _block(
                "ETS_INTERIOR_TIME_GAP" if multiples else "ETS_IRREGULAR_TIME_INDEX",
                "the modelled time index is not evenly spaced",
                evidence={
                    "column": options.time_column,
                    "modal_step_seconds": step_seconds,
                    "distinct_step_count": int(len(unique_deltas)),
                },
                impact=(
                    "An implicit hole in the time index would be smoothed over as "
                    "if the observations were adjacent."
                ),
            )

    endog = modelled["value"].to_numpy(dtype=float)
    n_obs = int(endog.size)
    specification = options.specification
    minimum = (
        2 * int(specification.seasonal_periods) + SEASONAL_OBSERVATION_MARGIN
        if specification.seasonal is not None
        else MIN_NON_SEASONAL_OBSERVATIONS
    )
    if n_obs < minimum:
        _block(
            "ETS_INSUFFICIENT_OBSERVATIONS",
            f"{n_obs} modelled observation(s) are fewer than the required {minimum}",
            evidence={
                "n_obs": n_obs,
                "required": minimum,
                "specification": specification.canonical,
            },
            impact="The specification has more freedom than the sample supports.",
        )
    multiplicative = {specification.error, specification.trend, specification.seasonal}
    if "mul" in multiplicative and float(np.min(endog)) <= 0.0:
        _block(
            "ETS_NONPOSITIVE_FOR_MULTIPLICATIVE",
            "a multiplicative component requires strictly positive observations",
            evidence={
                "specification": specification.canonical,
                "minimum_value": float(np.min(endog)),
            },
            impact="A multiplicative ETS recursion is undefined at or below zero.",
        )
    if float(np.std(endog)) == 0.0:
        _block(
            "ETS_CONSTANT_SERIES",
            "the modelled series is constant",
            evidence={"n_obs": n_obs, "value": float(endog[0])},
            impact="A constant series carries no smoothing information.",
        )

    audit = ETSSampleAudit(
        source_row_count=source_row_count,
        n_obs=n_obs,
        n_excluded=int(sum(exclusion_reasons.values())),
        exclusion_reasons=dict(exclusion_reasons),
        first_timestamp=str(times.iloc[0]),
        last_timestamp=str(times.iloc[-1]),
        inferred_step_seconds=step_seconds,
    )
    fingerprint = sha256_canonical(
        {
            "endog": options.value_column,
            "time": options.time_column,
            "first_timestamp": audit.first_timestamp,
            "last_timestamp": audit.last_timestamp,
            "n_obs": n_obs,
            "values": [float(value) for value in endog],
        }
    )
    return PreparedETSInput(
        options=options,
        endog=endog,
        audit=audit,
        sample_fingerprint=fingerprint,
    )


__all__ = [
    "ETSModelOptions",
    "ETSSampleAudit",
    "MIN_NON_SEASONAL_OBSERVATIONS",
    "PreparedETSInput",
    "prepare_ets_input",
]
