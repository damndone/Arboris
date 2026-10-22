"""OLS covariance plans: HAC time order, regular periods, weights and the covariance swap."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import numpy as np
import pandas as pd
from .ols_contract import _python_scalar


def _require_hac_time_order(
    frame: pd.DataFrame, time_order: str | None, y: str, x: list[str], weight_kind: str | None
) -> None:
    if not time_order:
        raise ValueError(
            "OLS_HAC_TIME_ORDER_MISSING: HAC (Newey-West) standard errors need the data's time "
            "order; set time_order to the column that orders the observations in time."
        )
    if time_order not in frame.columns:
        raise ValueError(f"OLS_HAC_TIME_ORDER_MISSING: time_order column {time_order!r} is not in the data.")
    if time_order == y or time_order in x:
        raise ValueError("OLS_HAC_TIME_ORDER_CONFLICT: time_order cannot be the outcome or a predictor.")
    if weight_kind is not None:
        raise ValueError(
            f"OLS_HAC_WEIGHTS_NOT_VALIDATED: HAC with {weight_kind} weights has not been checked "
            "against a reference implementation yet, so it is not offered."
        )


def _hac_plan(original: Any, model_frame: pd.DataFrame, time_order: str, lags: int | None) -> dict[str, Any]:
    """Check the estimation sample is one regular time series and fix the lag.

    The check runs on the rows the model used: a row dropped for a missing value
    leaves a gap exactly as a missing period does, and Newey-West would then
    treat observations two periods apart as neighbours (Stata's `newey`
    refuses gaps for the same reason).
    """
    from ..contracts.model.ols import HAC_DEFAULT_LAG_RULE, hac_default_lags

    labels = getattr(original.model.data, "row_labels", None)
    times = model_frame.loc[list(labels), time_order] if labels is not None else model_frame[time_order]
    if times.isna().any():
        raise ValueError(f"OLS_HAC_TIME_ORDER_MISSING_VALUES: {time_order} is missing on rows the model uses.")
    _require_regular_periods(times, time_order)
    nobs = int(original.nobs)
    if lags is None:
        lags, rule = hac_default_lags(nobs), HAC_DEFAULT_LAG_RULE
    else:
        rule = "specified"
    if lags >= nobs:
        raise ValueError(f"OLS_HAC_LAGS_INVALID: {lags} lags need more than {nobs} observations.")
    return {
        "kernel": "bartlett",
        "lags": int(lags),
        "lag_rule": rule,
        "time_order": time_order,
        "nobs": nobs,
        "first_period": _python_scalar(times.iloc[0]),
        "last_period": _python_scalar(times.iloc[-1]),
    }


def _require_regular_periods(times: pd.Series, column: str) -> None:
    """One observation per period, with no period missing between the first and last."""
    if pd.api.types.is_numeric_dtype(times):
        values = times.to_numpy(dtype=float)
        if not np.all(np.isclose(values, np.round(values))):
            raise ValueError(
                f"OLS_HAC_TIME_ORDER_INVALID: {column} must hold whole-number periods (such as years) "
                "or dates."
            )
        steps = np.diff(np.round(values))
        if (steps == 0).any():
            raise ValueError(_repeated_period_message(column))
        if (steps != 1).any():
            first_gap = int(np.flatnonzero(steps != 1)[0])
            raise ValueError(
                f"OLS_HAC_TIME_GAPS: {column} has gaps in the rows the model uses (first after "
                f"{_python_scalar(times.iloc[first_gap])}); missing periods, or rows dropped for missing "
                "values, would make observations two periods apart look adjacent. Fill or drop the "
                "gap explicitly first."
            )
        return
    stamps = pd.to_datetime(times, format="mixed", errors="coerce")
    if stamps.isna().any():
        raise ValueError(f"OLS_HAC_TIME_ORDER_INVALID: {column} must hold whole-number periods or dates.")
    if stamps.duplicated().any():
        raise ValueError(_repeated_period_message(column))
    index = pd.DatetimeIndex(stamps)
    frequency = pd.infer_freq(index) if len(index) >= 3 else None
    if frequency is None:
        raise ValueError(
            f"OLS_HAC_TIME_GAPS: the dates in {column} are not evenly spaced in the rows the model "
            "uses (a gap, or an irregular frequency); Newey-West needs one observation per period."
        )


def _repeated_period_message(column: str) -> str:
    return (
        f"OLS_HAC_REPEATED_PERIODS: {column} repeats a period in the rows the model uses. "
        "Newey-West here is for one time series; panel data need Driscoll-Kraay standard "
        "errors, which are not implemented yet."
    )


def apply_ols_covariance(original: Any, covariance: str, *, groups: Any = None, hac_lags: int | None = None) -> Any:
    """Return the fit carrying `covariance`, from a plain OLS fit.

    Single source for how a covariance estimator is applied to OLS, so a
    consumer that needs the fit itself -- rather than the normalized result --
    cannot drift from what `run_ols` reports. `run_ols` returns the *plain*
    fit, so post-estimation inference must apply the estimator itself or it
    silently answers under `nonrobust`.
    """

    if covariance == "clustered":
        if groups is None:
            raise ValueError("clustered covariance requires cluster groups")
        return original.get_robustcov_results(
            cov_type="cluster",
            groups=groups,
            use_correction=True,
            df_correction=True,
            # Inference engine v2 (v1.8.10): Stata's finite-sample rule,
            # t(G - 1) for coefficients and F(q, G - 1) for joint tests.
            use_t=True,
        )
    if covariance == "robust":
        # HC1 with t(N - K), as Stata's `regress, vce(robust)`.
        return original.get_robustcov_results(cov_type="HC1", use_t=True)
    if covariance == "hac":
        if hac_lags is None:
            raise ValueError("HAC covariance requires its lag truncation")
        # Newey-West: Bartlett kernel, N/(N-K) scaling, t(N - K) -- Stata's
        # `newey` and R's sandwich::NeweyWest(prewhite = FALSE, adjust = TRUE).
        # The fit's rows must already be in time order.
        return original.get_robustcov_results(
            cov_type="HAC", maxlags=hac_lags, kernel="bartlett", use_correction=True, use_t=True
        )
    if covariance == "unadjusted":
        return original
    raise ValueError(f"unsupported OLS covariance estimator: {covariance}")


_MAX_FREQUENCY_EXPANDED_ROWS = 5_000_000


def _normalize_ols_weight_spec(
    frame: pd.DataFrame, weights: Any
) -> tuple[str | None, str, Any]:
    """Validate a declared weight spec without deciding how to execute it."""

    if weights is None:
        return None, "", None
    if not isinstance(weights, Mapping):
        raise ValueError("OLS_WEIGHT_INVALID: weights must be an object with kind and column")
    kind = str(weights.get("kind") or "").strip().lower()
    column = str(weights.get("column") or "").strip()
    if kind not in {"frequency", "analysis", "sampling"}:
        raise ValueError(
            "OLS_WEIGHT_KIND_UNSUPPORTED: OLS supports frequency, analysis or "
            "sampling weights"
        )
    if not column:
        raise ValueError("OLS_WEIGHT_COLUMN_MISSING: weight column must be declared")
    if column not in frame.columns:
        raise ValueError(
            f"OLS_WEIGHT_COLUMN_MISSING: weight column {column!r} is not present in the dataset"
        )
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(
            f"OLS_WEIGHT_INVALID: weight column {column!r} must contain finite positive values"
        )
    if (values <= 0).any():
        raise ValueError(
            f"OLS_WEIGHT_INVALID: weight column {column!r} must contain finite positive values"
        )
    return kind, column, values


def _frequency_weight_counts(values: Any, column: str) -> Any:
    """Frequency weights are observation counts, so they must be whole numbers."""

    numeric = values.to_numpy(dtype=float)
    rounded = np.rint(numeric)
    if not np.allclose(numeric, rounded, rtol=0.0, atol=1e-9):
        raise ValueError(
            f"OLS_FREQUENCY_WEIGHT_NOT_INTEGER: frequency_weight column {column!r} must "
            "contain whole observation counts; declare analysis_weight for fractional "
            "weights"
        )
    counts = rounded.astype(np.int64)
    total = int(counts.sum())
    if total > _MAX_FREQUENCY_EXPANDED_ROWS:
        raise ValueError(
            f"OLS_FREQUENCY_WEIGHT_TOO_LARGE: frequency_weight column {column!r} expands "
            f"the analysis sample to {total} rows, above the {_MAX_FREQUENCY_EXPANDED_ROWS} "
            "row limit"
        )
    return counts


def _expand_rows_by_frequency(
    frame: pd.DataFrame,
    counts: Any,
    *,
    row_ids: list[str] | tuple[str, ...] | None,
    cluster_row_ids: list[str] | tuple[str, ...] | None,
) -> tuple[pd.DataFrame, Any, Any]:
    """Repeat each analysis row by its observation count, provenance included."""

    if (counts == 1).all():
        # Every row was observed once: expansion is the identity, so leave the
        # frame, its index and its row identifiers byte-for-byte untouched.
        return frame, row_ids, cluster_row_ids
    positions = np.repeat(np.arange(len(frame), dtype=np.int64), counts)
    occurrences = np.concatenate([np.arange(count, dtype=np.int64) for count in counts])
    expanded = frame.iloc[positions].reset_index(drop=True)

    def _expand_ids(values: Any) -> list[str]:
        # The repeated copies are distinct analysis rows, so they need distinct
        # identifiers; the first copy keeps the original id so provenance for an
        # unrepeated row never changes.
        expanded_ids: list[str] = []
        for position, occurrence in zip(positions, occurrences, strict=True):
            identifier = str(values[position])
            expanded_ids.append(
                identifier if occurrence == 0 else f"{identifier}#frequency:{occurrence}"
            )
        return expanded_ids

    if row_ids is not None:
        row_ids = _expand_ids(row_ids)
    if cluster_row_ids is not None:
        cluster_row_ids = _expand_ids(cluster_row_ids)
    return expanded, row_ids, cluster_row_ids
