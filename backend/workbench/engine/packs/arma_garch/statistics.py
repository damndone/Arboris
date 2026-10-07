"""Small statistical helpers shared by ARMA fitting and diagnostics."""

from __future__ import annotations

import math
import warnings as runtime_warnings

import numpy as np
from statsmodels.stats.diagnostic import acorr_ljungbox


# Preserve the automatic-selection policy required by the v1.8.11 objective.
LJUNG_BOX_SIGNIFICANCE_LEVEL = 0.01


# Warnings about library upkeep, not about this model. statsmodels emits a
# NumPy shape-assignment DeprecationWarning on every ARIMA fit; captured
# verbatim it was repeated on each candidate, filled a large share of the
# Agent's tool-output budget, and read to a user as if the model itself had
# a problem. These belong in our own maintenance signal, not in a candidate
# record.
_LIBRARY_UPKEEP_WARNINGS = (
    DeprecationWarning,
    PendingDeprecationWarning,
    FutureWarning,
    ImportWarning,
    ResourceWarning,
)


def modelling_warnings(
    caught: "list[runtime_warnings.WarningMessage]",
) -> list[str]:
    """Keep model-relevant warnings, in order, without repeats."""

    messages: list[str] = []
    for item in caught:
        if issubclass(item.category, _LIBRARY_UPKEEP_WARNINGS):
            continue
        text = str(item.message)
        if text not in messages:
            messages.append(text)
    return messages


def calculate_aicc(
    *,
    aic: float,
    parameter_count: int,
    effective_sample: int,
) -> float | None:
    """Return finite-sample corrected AIC, or null when it is undefined."""

    denominator = effective_sample - parameter_count - 1
    if denominator <= 0 or not math.isfinite(aic):
        return None
    return aic + (2.0 * parameter_count * (parameter_count + 1)) / denominator


def ljung_box_results(
    values: np.ndarray,
    *,
    model_df: int = 0,
    requested_lags: tuple[int, ...] = (5, 10, 20),
) -> tuple[dict[str, object], ...]:
    """Return bounded, JSON-ready Ljung-Box results."""

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return ()
    scale = float(np.max(np.abs(finite)))
    if scale == 0.0:
        return ()
    finite = finite / scale
    if float(np.ptp(finite)) == 0.0:
        return ()
    lags = tuple(lag for lag in requested_lags if 0 < lag < len(finite))
    if not lags and len(finite) > 1:
        lags = (len(finite) - 1,)
    if not lags:
        return ()
    with runtime_warnings.catch_warnings():
        runtime_warnings.simplefilter("ignore")
        frame = acorr_ljungbox(
            finite,
            lags=list(lags),
            model_df=model_df,
            return_df=True,
        )
    return tuple(
        {
            "lag": int(lag),
            "statistic": _finite_or_none(frame.loc[lag, "lb_stat"]),
            "p_value": _finite_or_none(frame.loc[lag, "lb_pvalue"]),
            "df": int(lag - model_df) if lag > model_df else None,
            "status": "ok" if lag > model_df else "unavailable",
            "reason_code": None if lag > model_df else "LJUNG_BOX_NONPOSITIVE_DF",
            "reason": None if lag > model_df else (
                f"Adjusted Ljung-Box p-value is unavailable: lag {lag} <= model_df {model_df}."
            ),
        }
        for lag in lags
    )


def ljung_box_warnings(results: tuple[dict[str, object], ...]) -> list[str]:
    """Keep the test and lag visible when diagnostics cannot establish adequacy."""

    messages = []
    for row in results:
        if row.get("status") == "unavailable":
            messages.append(str(row["reason"]))
        elif row.get("p_value") is not None and float(row["p_value"]) < LJUNG_BOX_SIGNIFICANCE_LEVEL:
            messages.append(
                f"Ljung-Box residual autocorrelation at lag {row['lag']} "
                f"(p={float(row['p_value']):.6g}, threshold={LJUNG_BOX_SIGNIFICANCE_LEVEL:g})."
            )
    return messages


def _finite_or_none(value: float) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


__all__ = ["LJUNG_BOX_SIGNIFICANCE_LEVEL", "calculate_aicc", "ljung_box_results", "ljung_box_warnings"]
