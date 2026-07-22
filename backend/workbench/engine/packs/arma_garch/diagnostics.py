"""Structured mean-model diagnostics with short-series-safe lags."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
import warnings as runtime_warnings

import numpy as np
from scipy import stats
from statsmodels.stats.diagnostic import het_arch
from statsmodels.stats.stattools import jarque_bera
from statsmodels.tools.sm_exceptions import MissingDataError
from statsmodels.tsa.stattools import acf, adfuller, pacf

from workbench.contracts.common.envelope import freeze_json
from workbench.engine.packs.arma_garch.statistics import ljung_box_results


@dataclass(frozen=True)
class MeanModelDiagnostics:
    max_plot_lag: int
    adf: Mapping[str, object]
    series_acf: tuple[Mapping[str, float | int | None], ...]
    series_pacf: tuple[Mapping[str, float | int | None], ...]
    residual_series: tuple[Mapping[str, float | int], ...]
    residual_acf: tuple[Mapping[str, float | int | None], ...]
    residual_pacf: tuple[Mapping[str, float | int | None], ...]
    ljung_box: tuple[Mapping[str, float | int | None], ...]
    squared_residual_acf: tuple[Mapping[str, float | int | None], ...]
    arch_lm: Mapping[str, object]
    normality: Mapping[str, object]
    residual_exceedance: Mapping[str, object]
    qq_data: tuple[Mapping[str, float], ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "adf",
            "series_acf",
            "series_pacf",
            "residual_series",
            "residual_acf",
            "residual_pacf",
            "ljung_box",
            "squared_residual_acf",
            "arch_lm",
            "normality",
            "residual_exceedance",
            "qq_data",
        ):
            object.__setattr__(
                self,
                field_name,
                freeze_json(getattr(self, field_name), f"mean_diagnostics.{field_name}"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "max_plot_lag": self.max_plot_lag,
            "adf": dict(self.adf),
            "series_acf": [dict(item) for item in self.series_acf],
            "series_pacf": [dict(item) for item in self.series_pacf],
            "residual_series": [dict(item) for item in self.residual_series],
            "residual_acf": [dict(item) for item in self.residual_acf],
            "residual_pacf": [dict(item) for item in self.residual_pacf],
            "ljung_box": [dict(item) for item in self.ljung_box],
            "squared_residual_acf": [
                dict(item) for item in self.squared_residual_acf
            ],
            "arch_lm": dict(self.arch_lm),
            "normality": dict(self.normality),
            "residual_exceedance": dict(self.residual_exceedance),
            "qq_data": [dict(item) for item in self.qq_data],
            "warnings": list(self.warnings),
        }


def build_mean_diagnostics(
    values: np.ndarray,
    residuals: np.ndarray,
    *,
    model_df: int = 0,
) -> MeanModelDiagnostics:
    """Build data artifacts for ARMA mean diagnostics without creating figures."""

    series, series_dropped = _finite_values(values)
    errors, residuals_dropped = _finite_values(residuals)
    max_plot_lag = min(40, min(len(series), len(errors)) // 4)
    warnings: list[str] = []
    if series_dropped:
        warnings.append("NONFINITE_SERIES_VALUES_DROPPED")
    if residuals_dropped:
        warnings.append("NONFINITE_RESIDUALS_DROPPED")

    adf_result = _adf_result(series)
    if adf_result["status"] != "ok":
        warnings.append("ADF_UNAVAILABLE")
    arch_result = _arch_lm_result(errors, model_df=model_df)
    if arch_result["status"] != "ok":
        warnings.append("ARCH_LM_UNAVAILABLE")

    return MeanModelDiagnostics(
        max_plot_lag=max_plot_lag,
        adf=adf_result,
        series_acf=_correlations(series, max_plot_lag, partial=False),
        series_pacf=_correlations(series, max_plot_lag, partial=True),
        residual_series=tuple(
            {"position": position, "value": float(value)}
            for position, value in enumerate(errors)
        ),
        residual_acf=_correlations(errors, max_plot_lag, partial=False),
        residual_pacf=_correlations(errors, max_plot_lag, partial=True),
        ljung_box=ljung_box_results(errors, model_df=model_df),
        squared_residual_acf=_correlations(
            np.square(_scale_for_numerics(errors)), max_plot_lag, partial=False
        ),
        arch_lm=arch_result,
        normality=_normality_result(errors),
        residual_exceedance=_residual_exceedance(errors),
        qq_data=_qq_data(errors),
        warnings=tuple(warnings),
    )


def _finite_values(values: np.ndarray) -> tuple[np.ndarray, int]:
    array = np.asarray(values, dtype=float).reshape(-1)
    finite = array[np.isfinite(array)]
    return finite, int(len(array) - len(finite))


def _adf_result(values: np.ndarray) -> dict[str, object]:
    unavailable = {
        "status": "unavailable",
        "statistic": None,
        "p_value": None,
        "used_lag": None,
        "nobs": int(len(values)),
    }
    values = _scale_for_numerics(values)
    if len(values) < 8 or float(np.ptp(values)) == 0.0:
        return unavailable
    try:
        with runtime_warnings.catch_warnings():
            runtime_warnings.simplefilter("ignore")
            statistic, p_value, used_lag, nobs, _, _ = adfuller(
                values,
                autolag="AIC",
            )
        statistic_value = _finite_or_none(statistic)
        p_value_value = _finite_or_none(p_value)
        if statistic_value is None or p_value_value is None:
            return unavailable
        return {
            "status": "ok",
            "statistic": statistic_value,
            "p_value": p_value_value,
            "used_lag": int(used_lag),
            "nobs": int(nobs),
        }
    except (ValueError, np.linalg.LinAlgError, MissingDataError):
        return unavailable


def _correlations(
    values: np.ndarray,
    requested_lag: int,
    *,
    partial: bool,
) -> tuple[Mapping[str, float | int | None], ...]:
    if len(values) == 0:
        return ()
    if not np.isfinite(values).all():
        return ()
    values = _scale_for_numerics(values)
    if float(np.ptp(values)) == 0.0:
        return ({"lag": 0, "value": 1.0},)
    max_lag = min(requested_lag, len(values) - 1)
    if partial:
        max_lag = min(max_lag, max(0, (len(values) - 1) // 2))
    try:
        with runtime_warnings.catch_warnings():
            runtime_warnings.simplefilter("ignore")
            coefficients = (
                pacf(values, nlags=max_lag, method="ywm")
                if partial
                else acf(values, nlags=max_lag, fft=False)
            )
    except (ValueError, np.linalg.LinAlgError, MissingDataError):
        return ({"lag": 0, "value": 1.0},)
    return tuple(
        {"lag": lag, "value": _finite_or_none(value)}
        for lag, value in enumerate(coefficients)
    )


def _arch_lm_result(values: np.ndarray, *, model_df: int) -> dict[str, object]:
    unavailable = {
        "status": "unavailable",
        "lag": None,
        "statistic": None,
        "p_value": None,
        "f_statistic": None,
        "f_p_value": None,
    }
    values = _scale_for_numerics(values)
    if len(values) < 8 or float(np.ptp(values)) == 0.0:
        return unavailable
    lag = min(10, max(1, len(values) // 5))
    try:
        with runtime_warnings.catch_warnings():
            runtime_warnings.simplefilter("ignore")
            statistic, p_value, f_statistic, f_p_value = het_arch(
                values,
                nlags=lag,
                ddof=model_df,
            )
    except (ValueError, np.linalg.LinAlgError, MissingDataError):
        return unavailable
    metrics = tuple(
        _finite_or_none(value)
        for value in (statistic, p_value, f_statistic, f_p_value)
    )
    if any(value is None for value in metrics):
        return unavailable
    return {
        "status": "ok",
        "lag": lag,
        "statistic": metrics[0],
        "p_value": metrics[1],
        "f_statistic": metrics[2],
        "f_p_value": metrics[3],
    }


def _shapiro_wilk(values: np.ndarray) -> dict[str, object]:
    """`swilk` equivalent. scipy's implementation is reliable for 3 <= n <= 5000."""

    if len(values) < 3:
        return {"status": "unavailable", "reason": "n < 3", "statistic": None, "p_value": None}
    if len(values) > 5000:
        return {
            "status": "unavailable",
            "reason": "n > 5000 exceeds the reliable range",
            "statistic": None,
            "p_value": None,
        }
    try:
        result = stats.shapiro(_scale_for_numerics(values))
    except ValueError as error:
        return {"status": "unavailable", "reason": str(error), "statistic": None, "p_value": None}
    statistic = _finite_or_none(float(result.statistic))
    p_value = _finite_or_none(float(result.pvalue))
    if statistic is None or p_value is None:
        return {"status": "unavailable", "reason": "non-finite", "statistic": None, "p_value": None}
    return {"status": "ok", "statistic": statistic, "p_value": p_value}


def _shapiro_francia(values: np.ndarray) -> dict[str, object]:
    """`sfrancia` equivalent: the Weisberg-Bingham W' statistic.

    W' is the squared correlation between the ordered sample and the expected
    normal order statistics (Blom scores); significance uses the Royston
    log-normal approximation.
    """

    n = len(values)
    if n < 5:
        return {"status": "unavailable", "reason": "n < 5", "statistic": None, "p_value": None}
    ordered = np.sort(_scale_for_numerics(values))
    # Blom plotting positions -> expected normal order statistics.
    positions = (np.arange(1, n + 1) - 0.375) / (n + 0.25)
    scores = stats.norm.ppf(positions)
    correlation = np.corrcoef(ordered, scores)[0, 1]
    statistic = _finite_or_none(float(correlation**2))
    if statistic is None or statistic <= 0.0:
        return {"status": "unavailable", "reason": "degenerate", "statistic": None, "p_value": None}
    # Royston (1983) normalizing transform for W'.
    log_n = math.log(n)
    mu = -1.2725 + 1.0521 * (math.log(log_n) - log_n)
    sigma = 1.0308 - 0.26758 * (math.log(log_n) + 2.0 / log_n)
    if sigma <= 0.0:
        return {"status": "unavailable", "reason": "degenerate", "statistic": statistic, "p_value": None}
    z = (math.log(1.0 - statistic) - mu) / sigma
    p_value = _finite_or_none(float(stats.norm.sf(z)))
    if p_value is None:
        return {"status": "unavailable", "reason": "non-finite", "statistic": statistic, "p_value": None}
    return {"status": "ok", "statistic": statistic, "p_value": p_value}


def _normality_result(values: np.ndarray) -> dict[str, object]:
    # The three reference tests: sktest (omnibus), swilk, sfrancia. The omnibus
    # keys stay at the top level so existing readers are unaffected.
    subtests = {
        "shapiro_wilk": _shapiro_wilk(values),
        "shapiro_francia": _shapiro_francia(values),
    }
    unavailable = {
        "status": "unavailable",
        "statistic": None,
        "p_value": None,
        "skew": None,
        "kurtosis": None,
        **subtests,
    }
    if len(values) < 3:
        return unavailable
    statistic, p_value, skew, kurtosis = jarque_bera(
        _scale_for_numerics(values)
    )
    metrics = tuple(
        _finite_or_none(value) for value in (statistic, p_value, skew, kurtosis)
    )
    if any(value is None for value in metrics):
        return unavailable
    return {
        "status": "ok",
        "statistic": metrics[0],
        "p_value": metrics[1],
        "skew": metrics[2],
        "kurtosis": metrics[3],
        **subtests,
    }


def _residual_exceedance(values: np.ndarray, threshold: float = 1.96) -> dict[str, object]:
    """`gen fail = abs(z) > 1.96` — count and rate.

    For final-model diagnostics the input is the standardized residual, so this
    is the reference's in-sample failure rate.
    """

    finite = values[np.isfinite(values)]
    n = int(len(finite))
    if n == 0:
        return {"threshold": threshold, "count": None, "rate": None, "n": 0}
    count = int(np.sum(np.abs(finite) > threshold))
    return {"threshold": threshold, "count": count, "rate": count / n, "n": n}


def _qq_data(values: np.ndarray) -> tuple[Mapping[str, float], ...]:
    if len(values) == 0:
        return ()
    theoretical, observed = stats.probplot(values, dist="norm", fit=False)
    return tuple(
        {
            "theoretical_quantile": float(theoretical_value),
            "observed": float(observed_value),
        }
        for theoretical_value, observed_value in zip(
            theoretical,
            observed,
            strict=True,
        )
    )


def _finite_or_none(value: object) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _scale_for_numerics(values: np.ndarray) -> np.ndarray:
    """Bound magnitude for scale-invariant diagnostics before powers/products."""

    if len(values) == 0:
        return values
    scale = float(np.max(np.abs(values)))
    if not math.isfinite(scale) or scale == 0.0:
        return values
    return values / scale


__all__ = ["MeanModelDiagnostics", "build_mean_diagnostics"]
