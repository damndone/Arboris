"""Operation declarations shared by the manual and Agent catalogs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NativeResearchOperation:
    kind: str
    label: str
    summary: str
    module: str
    runner: str
    bindings: dict[str, dict[str, Any]]
    options: dict[str, dict[str, Any]]
    assumptions: tuple[str, ...]
    optional_bindings: tuple[str, ...] = ()
    adapter: str | None = None
    dataset_kind: str | None = None

    def schema(self) -> dict[str, Any]:
        return deepcopy({
            "type": "object",
            "required": ["operation_id", "input_mode", "column_bindings", "options"],
            "additionalProperties": False,
            "properties": {
                "operation_id": {"type": "string"},
                "input_mode": {"const": "frame"},
                "column_bindings": {
                    "type": "object", "properties": self.bindings, "additionalProperties": False,
                    "required": [name for name in self.bindings if name not in self.optional_bindings],
                },
                "options": {
                    "type": "object", "properties": self.options, "additionalProperties": False,
                    "required": [name for name, option in self.options.items() if "default" not in option],
                },
            },
        })


def _column(title: str) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "title": title}


def _columns(title: str, maximum: int, *, minimum: int = 1) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string", "minLength": 1},
            "minItems": minimum, "maxItems": maximum, "uniqueItems": True, "title": title}


_TIME_BINDINGS = {"time_col": _column("Time"), "outcome": _column("Observed series")}
_FORECAST_OPTIONS = {
    "forecast_periods": {"type": "integer", "minimum": 1, "maximum": 200, "default": 1},
    "holdout_periods": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0},
    "confidence_level": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.95,
                         "title": "Predictive interval level"},
}
_VOLATILITY_BINDINGS = {"time_col": _column("Time"), "outcome": _column("Zero-mean returns or residuals")}
_VOLATILITY_OPTIONS = {key: _FORECAST_OPTIONS[key] for key in ("forecast_periods", "holdout_periods")}
_ETS_SMOOTHING = {
    "alpha": {"type": "number", "minimum": 0.0001, "maximum": 0.9999, "title": "Level smoothing (alpha)"},
    "beta": {"type": "number", "minimum": 0.0001, "maximum": 0.9999, "title": "Trend smoothing (beta)"},
}
_ETS_DAMPING = {"type": "number", "minimum": 0.8, "maximum": 1, "default": 1.0, "title": "Damping (phi, 0.80–0.98 or 1)"}
_ARIMA_ORDER = {
    "ar_order": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1, "title": "AR order (p)"},
    "differences": {"type": "integer", "minimum": 0, "maximum": 2, "default": 0, "title": "Differences (d)"},
    "ma_order": {"type": "integer", "minimum": 0, "maximum": 5, "default": 0, "title": "MA order (q)"},
}
_ARIMA_DETERMINISTIC = {"type": "string", "enum": ["none", "mean", "drift"], "default": "none",
                        "title": "Deterministic term (mean for d=0, drift for d=1)"}
_BOUNDED_ARIMA_ORDER = {**_ARIMA_ORDER, **{key: {**_ARIMA_ORDER[key], "maximum": 3} for key in ("ar_order", "ma_order")}}
_SEASONAL_ORDER = {
    "seasonal_ar_order": {"type": "integer", "minimum": 0, "maximum": 1, "default": 0, "title": "Seasonal AR order (P)"},
    "seasonal_differences": {"type": "integer", "minimum": 0, "maximum": 1, "default": 1, "title": "Seasonal differences (D)"},
    "seasonal_ma_order": {"type": "integer", "minimum": 0, "maximum": 1, "default": 0, "title": "Seasonal MA order (Q)"},
    "seasonal_period": {"type": "integer", "enum": [*range(2, 13), 24], "title": "Season length (periods)"},
}
_PERIOD_24_ASSUMPTION = "At season length 24, seasonal differencing cannot be combined with seasonal AR or MA."
_SARIMA_DETERMINISTIC = {**_ARIMA_DETERMINISTIC, "title": "Deterministic term (mean for d+D=0, drift for d+D=1)"}
_XREG_BINDINGS = {**_TIME_BINDINGS, "predictors": _columns("Known predictor columns", 4)}
_XREG_FORECAST_OPTIONS = {**_FORECAST_OPTIONS, "forecast_periods": {
    "type": "integer", "minimum": 1, "maximum": 200, "title": "Known future rows at end of dataset",
}}
_XREG_ASSUMPTIONS = (
    "Use a single regular time grid with finite predictor values in every row. Leave outcomes blank on the declared future suffix.",
    "Fits use only historical outcomes and regressors. Gaussian prediction intervals condition on fitted parameters and supplied future predictors.",
    "Holdout scores condition on the supplied predictor values for held-out rows; they cannot establish real-time data availability.",
    "This model estimates regression with ARIMA errors; coefficients do not establish causal effects.",
)
_HOLT_WINTERS_OPTIONS = {
    "season_period": {"type": "integer", "minimum": 2, "maximum": 366, "title": "Season length (periods)"},
    "beta": {"type": "number", "minimum": 0, "maximum": 1, "title": "Trend smoothing (beta)"},
    "gamma": {"type": "number", "minimum": 0, "maximum": 1, "title": "Seasonal smoothing (gamma)"},
    "forecast_periods": _FORECAST_OPTIONS["forecast_periods"],
    "confidence_level": _FORECAST_OPTIONS["confidence_level"],
}
_HOLT_WINTERS_ASSUMPTIONS = (
    "Complete regular time grid with at least three full seasonal cycles.",
    "Additive trend and seasonality, with two warmup seasons and no damping.",
    "Normal prediction intervals use centered one-step innovation variance and condition on fitted states and smoothing.",
)
_PREDICTOR_BINDINGS = {
    "outcome": _column("Outcome"), "predictors": _columns("Predictors", 512),
    "time_col": _column("Time (optional)"),
}
_HOLDOUT_FRACTION = {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.2}
_FOREST_OPTIONS = {
    "n_trees": {"type": "integer", "minimum": 1, "maximum": 32, "default": 16, "title": "Number of trees"},
    "max_depth": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4, "title": "Maximum tree depth"},
    "min_samples_leaf": {"type": "integer", "minimum": 1, "maximum": 100_000, "default": 2,
                         "title": "Minimum training rows per leaf"},
    "max_features": {"type": "integer", "minimum": 0, "maximum": 64, "default": 0,
                     "title": "Predictors per split (0 uses square root)"},
    "seed": {"type": "integer", "minimum": 0, "maximum": 4_294_967_295, "default": 0,
             "title": "Reproducible seed"},
    "holdout_fraction": _HOLDOUT_FRACTION,
}
_PREDICTION_ASSUMPTIONS = (
    "The training prefix supplies all scaling and fit parameters. The test suffix supplies evaluation only.",
    "Specify time to evaluate a chronological split. An omitted time column uses the persisted row order.",
    "Predictive coefficients do not supply causal effects or inferential p-values.",
)
_REPLAY_BINDINGS = {
    "signal_time_col": _column("Signal time"), "execution_time_col": _column("Execution time"),
    "end_time_col": _column("Holding-period end time"),
    "return_columns": _columns("Asset return columns, in order", 32),
    "weight_columns": _columns("Target weight columns, in the same asset order", 32),
}
_REPLAY_OPTIONS = {
    "transaction_cost_bps": {"type": "number", "minimum": 0, "exclusiveMaximum": 10_000,
                             "title": "Linear trading cost (basis points)"},
    "initial_equity": {"type": "number", "exclusiveMinimum": 0, "title": "Initial portfolio equity"},
}
_REPLAY_ASSUMPTIONS = (
    "Replay assumes full simulated fills, long-only risky assets, and cash with zero return.",
    "Return columns are simple holding-period returns. Weights are fractions paired by column order.",
    "Contiguous intervals and signal times are checked. Input timestamps alone do not establish data vintage or trading feasibility.",
)


NATIVE_RESEARCH_OPERATIONS = {
    "prediction.native_forest_apply": NativeResearchOperation(
        kind="prediction_model", label="Apply saved forest", module="ridge", adapter="prediction_apply",
        runner="score_saved_forest", bindings={}, dataset_kind="derived_data",
        summary="Apply a saved C++ regression or binary forest to new data without refitting. Classifiers add probability and 0/1 labels at probability >= 0.5.",
        options={
            "model_run_id": {"type": "string", "minLength": 1, "maxLength": 256, "title": "Saved model run"},
            "model_artifact_id": {"type": "string", "minLength": 1, "maxLength": 512, "title": "Saved model artifact"},
            "model_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "title": "Saved model SHA256"},
            "prediction_column": {"type": "string", "minLength": 1, "maxLength": 256,
                                  "default": "prediction", "title": "New prediction column"},
            "probability_column": {"type": "string", "minLength": 1, "maxLength": 256,
                                   "default": "probability", "title": "New probability column (classification only)"},
        },
        assumptions=(
            "The saved forest is used unchanged. New data must contain its numeric predictor columns under their original names.",
            "Rows retain their input order. Outcomes are not required and predictions are not new holdout evaluation evidence.",
            "Predictions are offline research outputs, not trading instructions or causal effects.",
        ),
    ),
    "time_series.stationarity_statistic": NativeResearchOperation(
        kind="pack", label="Fixed-lag stationarity statistic", module="time_series", adapter="stationarity",
        runner="run_stationarity_statistic",
        summary="Compute a fixed-lag ADF unit root statistic or KPSS level stationarity statistic on one complete regular series.",
        bindings=_TIME_BINDINGS,
        options={
            "method": {"type": "string", "enum": ["adf", "kpss"], "title": "Diagnostic method"},
            "lag": {"type": "integer", "minimum": 0, "maximum": 20, "title": "Fixed lag (periods)"},
        },
        assumptions=(
            "ADF includes a constant and uses the declared number of lagged differences. Its null hypothesis is a unit root.",
            "KPSS tests level stationarity as the null and uses the declared Bartlett truncation lag.",
            "Result scope is the statistic. Inference requires a separately validated reference distribution.",
        ),
    ),
    "time_series.correlogram": NativeResearchOperation(
        kind="pack", label="ACF and PACF", module="time_series", runner="run_correlogram",
        summary="Inspect native sample autocorrelation and partial autocorrelation before choosing lag orders.",
        bindings=_TIME_BINDINGS,
        options={"max_lag": {"type": "integer", "minimum": 1, "maximum": 200, "default": 1,
                             "title": "Maximum lag (periods)"}},
        assumptions=(
            "Use a complete, regular time series. Treat lag patterns as descriptive under weak stationarity.",
            "ACF uses common-n autocovariances around the sample mean; PACF uses Yule–Walker recursion.",
            "No significance bands or stationarity test are computed by this operation.",
        ),
    ),
    "time_series.native_arima": NativeResearchOperation(
        kind="pack", label="ARIMA forecast (Rust)", module="time_series", runner="run_arima",
        summary="Fit a nonseasonal Gaussian AR, MA, ARMA or ARIMA and check forecasts against an optional held-out suffix.",
        bindings=_TIME_BINDINGS,
        options={**_ARIMA_ORDER, "deterministic": _ARIMA_DETERMINISTIC, **_FORECAST_OPTIONS},
        assumptions=(
            "Regular ordered time. Missing outcomes keep their time positions. Differencing uses diffuse level anchors.",
            "Gaussian innovations likelihood with stationary AR and invertible MA dynamics. The combined order p+q is at most six.",
            "Prediction intervals condition on fitted parameters.",
            "The holdout uses a fit to the training prefix; future forecasts use the full series.",
            "Paired correlations of standardized innovations are descriptive residual checks.",
        ),
    ),
    "time_series.arima_residual_check": NativeResearchOperation(
        kind="pack", label="ARIMA with residual check (Rust)", module="time_series", runner="run_arima_with_whiteness",
        bindings=_TIME_BINDINGS,
        summary="Fit nonseasonal ARIMA with an explicit Ljung–Box check on the full fit's standardized innovations.",
        options={
            **_ARIMA_ORDER, "deterministic": _ARIMA_DETERMINISTIC,
            "whiteness_lag": {"type": "integer", "minimum": 1, "maximum": 12, "title": "Ljung–Box lag"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Regular ordered time, nonseasonal Gaussian ARIMA, and forecasts conditional on the fitted model.",
            "The Ljung–Box statistic uses common-sample autocorrelations of standardized one-step innovations after diffuse anchors.",
            "The reference is asymptotic chi-square with lag minus p and q degrees of freedom.",
            "The test is unavailable with time gaps, insufficient or constant innovations, or nonpositive degrees of freedom.",
            "The holdout uses a separate training-prefix fit. A single residual check cannot establish model adequacy.",
        ),
    ),
    "time_series.native_sarima": NativeResearchOperation(
        kind="pack", label="Seasonal ARIMA forecast (Rust)", module="time_series", runner="run_sarima",
        summary="Fit a Gaussian multiplicative seasonal ARIMA with residual checks and an optional fixed-origin holdout.",
        bindings=_TIME_BINDINGS,
        options={**_BOUNDED_ARIMA_ORDER, **_SEASONAL_ORDER, "deterministic": _SARIMA_DETERMINISTIC, **_FORECAST_OPTIONS},
        assumptions=(
            "Regular ordered time. Seasonal differencing requires a complete initial block of d + D × season length rows.",
            "The Gaussian likelihood uses stationary AR and invertible MA factors. Combined dynamic order is at most four.",
            _PERIOD_24_ASSUMPTION,
            "Prediction intervals condition on fitted parameters.",
            "The holdout uses training data only and compares against the last observed training value for each seasonal phase.",
            "Paired correlations of standardized innovations are descriptive residual checks.",
        ),
    ),
    "time_series.native_arimax": NativeResearchOperation(
        kind="pack", label="ARIMAX scenario forecast (Rust)", module="time_series", adapter="time_series_xreg",
        runner="run_arimax", bindings=_XREG_BINDINGS,
        summary="Estimate regression with nonseasonal ARIMA errors and predict under supplied future predictors.",
        options={**_BOUNDED_ARIMA_ORDER, "deterministic": _ARIMA_DETERMINISTIC, **_XREG_FORECAST_OPTIONS},
        assumptions=_XREG_ASSUMPTIONS,
    ),
    "time_series.native_sarimax": NativeResearchOperation(
        kind="pack", label="SARIMAX scenario forecast (Rust)", module="time_series", adapter="time_series_xreg",
        runner="run_sarimax", bindings=_XREG_BINDINGS,
        summary="Estimate regression with seasonal ARIMA errors and predict under supplied future predictors.",
        options={**_BOUNDED_ARIMA_ORDER, **_SEASONAL_ORDER, "deterministic": _SARIMA_DETERMINISTIC, **_XREG_FORECAST_OPTIONS},
        assumptions=(*_XREG_ASSUMPTIONS, "Seasonal differencing requires a complete initial block of outcomes.",
                     _PERIOD_24_ASSUMPTION),
    ),
    "time_series.native_var": NativeResearchOperation(
        kind="pack", label="Vector autoregression (Rust)", module="time_series", adapter="var", runner="run_var",
        bindings={"time_col": _column("Time"), "series_columns": _columns("Observed series", 8, minimum=2),
                  "granger_effect": _column("Granger response (optional)"),
                  "granger_excluded": _columns("Excluded lagged series (optional)", 7)},
        optional_bindings=("granger_effect", "granger_excluded"),
        summary="Fit a joint VAR, predict each series and optionally inspect Granger tests or reduced-form innovation responses.",
        options={
            "lag_order": {"type": "integer", "minimum": 1, "maximum": 8, "default": 1, "title": "VAR lag order"},
            "intercept": {"type": "boolean", "default": True},
            "irf_periods": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0,
                            "title": "Innovation response periods (0 disables)"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "All series share a complete regular time grid and lag sample. Residual covariance divides by residual degrees of freedom.",
            "Marginal Gaussian prediction intervals condition on fitted parameters. The holdout uses a fixed training origin.",
            "The contraction bound is sufficient for stability when below one with a numerical margin. Other estimates are undetermined.",
            "Granger F tests are equation-specific predictive restrictions; reduced-form responses describe innovations, without causal identification.",
        ),
    ),
    "time_series.native_vecm": NativeResearchOperation(
        kind="pack", label="Rank-one VECM (Rust)", module="time_series", adapter="vecm", runner="run_vecm_rank1",
        bindings={"time_col": _column("Time"), "series_columns": _columns("Observed level series", 2, minimum=2)},
        summary="Fit a bivariate Johansen VECM at a declared cointegration rank of one and forecast both levels.",
        options={
            "difference_lags": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1, "title": "Lagged differences"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Two complete level series on a regular grid. The specified rank is one, with a constant restricted to the cointegrating relation.",
            "The cointegrating vector is normalized on the first bound series. Canonical eigenvalues are diagnostics, not a rank test.",
            "Forecasts are in levels with marginal Gaussian intervals conditional on the fit. Holdout forecasts use a fixed training origin.",
        ),
    ),
    "time_series.johansen_rank": NativeResearchOperation(
        kind="pack", label="Johansen rank diagnostics (Rust)", module="time_series", adapter="johansen",
        runner="run_johansen_rank",
        bindings={"time_col": _column("Time"), "series_columns": _columns("Observed level series", 4, minimum=3)},
        options={"difference_lags": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1,
                                    "title": "Lagged differences"}},
        summary="Compute Johansen trace and maximum-eigenvalue statistics for each candidate rank.",
        assumptions=(
            "Three or four complete level series on a regular grid; constant restricted to the cointegrating space.",
            "The levels VAR order is one greater than the selected number of lagged differences.",
            "The result contains uncalibrated statistics. It supplies no critical values, p-values or selected rank.",
        ),
    ),
    "time_series.varma11_fixed_ma": NativeResearchOperation(
        kind="pack", label="VARMA(1,1) with fixed MA (Rust)", module="time_series", adapter="varma",
        runner="run_varma11_fixed_ma",
        bindings={"time_col": _column("Time"), "series_columns": _columns("Observed series", 2, minimum=2)},
        summary="Estimate the bivariate AR matrix with a supplied shared diagonal MA coefficient.",
        options={
            "ma_coefficient": {"type": "number", "minimum": -0.95, "maximum": 0.95, "title": "Fixed diagonal MA coefficient"},
            "intercept": {"type": "boolean", "default": True},
            "irf_periods": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0,
                            "title": "Innovation response periods (0 disables)"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Two complete regular series. The moving-average matrix equals the supplied scalar times the identity.",
            "Conditional likelihood fixes the first observation and uses a zero initial innovation.",
            "Forecast covariance uses the likelihood divisor. Marginal intervals condition on the fitted model.",
            "The holdout uses an independent training prefix. Optional responses describe reduced-form innovations.",
        ),
    ),
    "time_series.markov_switching": NativeResearchOperation(
        kind="pack", label="Markov switching mean (Rust)", module="time_series", adapter="markov", runner="run_markov_switching",
        bindings=_TIME_BINDINGS, options=_FORECAST_OPTIONS,
        summary="Estimate two Gaussian mean regimes with a shared variance and forecast their mixture distribution.",
        assumptions=(
            "A regular time grid with time-invariant transitions estimated from the data and stationary initial probabilities.",
            "Regimes are ordered by their fitted means. The innovation variance is shared.",
            "Filtered probabilities use observations through each time. Smoothed probabilities use the entire fitted sample.",
            "Forecasts start from the final filtered state. Intervals are conditional quantiles of the two-normal mixture.",
        ),
    ),
    "time_series.native_arfima": NativeResearchOperation(
        kind="pack", label="ARFIMA(0,d,0) forecast (Rust)", module="time_series", adapter="arfima", runner="run_arfima",
        bindings=_TIME_BINDINGS,
        summary="Fit or fix fractional differencing in an exact finite-sample Gaussian model.",
        options={
            "difference": {
                "oneOf": [
                    {"type": "null", "title": "Estimate d from the data"},
                    {"type": "number", "minimum": -0.45, "maximum": 0.45, "title": "Enter fixed d"},
                ],
                "default": None, "title": "Fractional difference (d)",
            },
            "deterministic": {"type": "string", "enum": ["none", "mean"], "default": "mean",
                              "title": "Level term"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Complete regular observations. Stationary fractional Gaussian noise with no ordinary AR or MA terms.",
            "Fractional differencing d is fixed or estimated in [-0.45, 0.45]. Estimated d needs an identified interior optimum.",
            "Forecasts use exact finite-sample conditional moments. Gaussian intervals condition on fitted parameters.",
            "Holdout forecasts are fixed-origin predictions from a separately fitted training prefix.",
        ),
    ),
    "time_series.holt_winters_additive": NativeResearchOperation(
        kind="pack", label="Additive Holt-Winters (Rust)", module="time_series", adapter="time_series_ets",
        runner="run_holt_winters", bindings=_TIME_BINDINGS,
        summary="Forecast a regular seasonal series with additive Holt-Winters at supplied smoothing parameters.",
        options={**_HOLT_WINTERS_OPTIONS,
                 "alpha": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "title": "Level smoothing (alpha)"}},
        assumptions=_HOLT_WINTERS_ASSUMPTIONS,
    ),
    "time_series.holt_winters_fit_alpha": NativeResearchOperation(
        kind="pack", label="Holt-Winters with holdout (Rust)", module="time_series", adapter="time_series_ets",
        runner="run_holt_winters_fit_alpha", bindings=_TIME_BINDINGS,
        summary="Select additive Holt-Winters level smoothing on the training prefix, then score the untouched holdout.",
        options={**_HOLT_WINTERS_OPTIONS, "holdout_periods": {
            "type": "integer", "minimum": 1, "maximum": 200, "title": "Holdout periods",
        }},
        assumptions=(*_HOLT_WINTERS_ASSUMPTIONS,
                     "Alpha minimizes training SSE over 0.05 through 1.00 in increments of 0.05; beta and gamma are fixed.",
                     "Future forecasts update states with the observed suffix at the selected alpha, without retuning it."),
    ),
    "time_series.holt_winters_fit_joint": NativeResearchOperation(
        kind="pack", label="Holt-Winters joint fit (Rust)", module="time_series", adapter="time_series_ets",
        runner="run_holt_winters_fit_joint", bindings=_TIME_BINDINGS,
        summary="Jointly fit the level, trend and seasonal smoothing coefficients for an additive seasonal forecast.",
        options={"season_period": {"type": "integer", "minimum": 2, "maximum": 24, "title": "Season length"},
                 **_FORECAST_OPTIONS},
        assumptions=(
            "Complete regular observations. The first two cycles initialize the level, trend and seasonality.",
            "The fit jointly minimizes training one-step squared errors. Unidentified or boundary fits are refused.",
            "Gaussian prediction intervals condition on the fitted state and smoothing parameters.",
            "An optional holdout is forecast from a separate training-prefix fit and compared with the seasonal baseline.",
        ),
    ),
    "time_series.ets_trend": NativeResearchOperation(
        kind="pack", label="Additive ETS trend (Rust)", module="time_series", adapter="ets_trend", runner="run_ets_trend",
        bindings=_TIME_BINDINGS,
        summary="Forecast additive errors and trend with optional damping at supplied smoothing coefficients.",
        options={**_ETS_SMOOTHING, "phi": _ETS_DAMPING, **_FORECAST_OPTIONS},
        assumptions=(
            "Complete regular observations, additive errors and trend, and no seasonality.",
            "Smoothing is supplied with beta at most alpha. A damping coefficient of one leaves the trend undamped.",
            "Conditional Gaussian likelihood estimates the initial level, initial slope and innovation variance.",
            "Prediction intervals condition on the fitted parameters. Holdout forecasts use a separately fitted training prefix.",
        ),
    ),
    "time_series.ets_trend_estimate": NativeResearchOperation(
        kind="pack", label="Estimated ETS trend (Rust)", module="time_series", adapter="ets_trend", runner="run_ets_trend_auto",
        bindings=_TIME_BINDINGS,
        summary="Estimate one or both additive trend smoothing coefficients at a declared damping factor.",
        options={
            **{name: {"title": option["title"], "default": None, "oneOf": [
                {"type": "null", "title": f"Estimate {name}"},
                {**option, "title": f"Enter fixed {name}"},
            ]} for name, option in _ETS_SMOOTHING.items()},
            "phi": _ETS_DAMPING,
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Complete regular observations, additive errors and trend, and no seasonality.",
            "Leave one or both smoothing coefficients unset to estimate them. Damping is supplied or defaults to one.",
            "Returns a verified interior solution for a bounded profile search. Boundary, ambiguous and failed fits are reported.",
            "Holdout forecasts use a separately fitted training prefix and intervals condition on the fitted parameters.",
        ),
    ),
    "time_series.native_volatility": NativeResearchOperation(
        kind="pack", label="ARCH and GARCH volatility (Rust)", module="time_series", adapter="volatility",
        runner="run_volatility", bindings=_VOLATILITY_BINDINGS,
        summary="Fit ARCH(1), GARCH(1,1), or GJR-GARCH(1,1,1) and forecast conditional innovation variance.",
        options={
            "family": {"type": "string", "enum": ["arch_1", "garch_1_1", "gjr_garch_1_1_1"],
                       "default": "garch_1_1", "title": "Volatility model"},
            **_VOLATILITY_OPTIONS,
        },
        assumptions=(
            "Complete regular return or residual series with mean fixed at zero.",
            "Conditional Gaussian maximum likelihood with constrained persistence. Active boundaries are reported.",
            "Holdout forecasts are one-step ahead and update with the previous observed shock using training-only parameters.",
            "Future values are conditional variances in squared input units.",
        ),
    ),
    "time_series.native_egarch": NativeResearchOperation(
        kind="pack", label="EGARCH one-step volatility (Rust)", module="time_series", adapter="egarch", runner="run_egarch",
        bindings=_VOLATILITY_BINDINGS,
        summary="Fit asymmetric Gaussian log variance with a single future conditional variance forecast.",
        options={
            "forecast_periods": {"type": "integer", "minimum": 1, "maximum": 1, "default": 1},
            "holdout_periods": _FORECAST_OPTIONS["holdout_periods"],
        },
        assumptions=(
            "Complete regular zero-mean return or residual series. The fit uses training-only conditional Gaussian likelihood.",
            "The signed standardized innovation coefficient makes negative and positive shocks potentially asymmetric.",
            "The holdout is rolling one-step at fixed parameters. Future variance conditions on the last observed innovation.",
            "Reported variance uses squared input units. Log variance is the natural logarithm of that quantity.",
        ),
    ),
    "time_series.native_igarch": NativeResearchOperation(
        kind="pack", label="IGARCH(1,1) volatility (Rust)", module="time_series", adapter="igarch", runner="run_igarch",
        bindings=_VOLATILITY_BINDINGS, options=_VOLATILITY_OPTIONS,
        summary="Fit an integrated Gaussian variance model and report finite-horizon conditional variances.",
        assumptions=(
            "Complete regular zero-mean returns or residuals. The shock and previous variance coefficients sum to one.",
            "Conditional Gaussian likelihood uses the training prefix. Holdout variances are rolling one-step at fixed parameters.",
            "Positive intercept and persistence of one imply no finite long-run variance. Each later expected variance adds the intercept.",
        ),
    ),
    "time_series.local_level": NativeResearchOperation(
        kind="pack", label="Local-level forecast", module="time_series", runner="run_local_level",
        summary="Filter a regular series and forecast with a Rust local-level Gaussian model.",
        bindings=_TIME_BINDINGS,
        options={
            "process_variance": {"type": "number", "minimum": 0, "title": "Level innovation variance (Q)"},
            "observation_variance": {"type": "number", "exclusiveMinimum": 0, "title": "Observation noise variance (R)"},
            "initial_mean": {"type": "number", "title": "Prior level mean"},
            "initial_variance": {"type": "number", "minimum": 0, "title": "Prior level variance"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Equally spaced observations of a scalar random-walk level with independent Gaussian errors.",
            "Parameters and initialization are fixed by the request. Intervals are conditional on these choices.",
            "An enabled holdout is predicted from a fixed training origin. Missing measurements still advance time.",
        ),
    ),
    "time_series.local_level_fit": NativeResearchOperation(
        kind="pack", label="Local-level fit", module="time_series", runner="run_local_level_fit",
        summary="Estimate the common noise scale of a local-level Gaussian model in Rust at a declared Q/R ratio.",
        bindings=_TIME_BINDINGS,
        options={
            "variance_ratio": {"type": "number", "minimum": 0, "title": "Process to observation variance ratio (Q/R)"},
            "initial_mean": {"type": "number", "title": "Prior level mean"},
            "relative_initial_variance": {"type": "number", "minimum": 0, "title": "Prior variance relative to observation variance"},
            **_FORECAST_OPTIONS,
        },
        assumptions=(
            "Equally spaced observations of a scalar random-walk level with independent Gaussian errors.",
            "The common scale is estimated by Gaussian likelihood on training data at the declared fixed variance ratios.",
            "Predictive intervals are conditional on the fitted parameters and exclude parameter uncertainty.",
        ),
    ),
    "time_series.figarch_fixed": NativeResearchOperation(
        kind="pack", label="FIGARCH with fixed coefficients (Rust)", module="time_series", adapter="figarch", runner="run_figarch",
        bindings=_VOLATILITY_BINDINGS,
        summary="Filter fractional conditional variance and forecast with supplied coefficients and a finite lag window.",
        options={
            "omega": {"type": "number", "exclusiveMinimum": 0, "title": "Variance intercept parameter (omega)"},
            "phi": {"type": "number", "minimum": 0, "maximum": 0.475, "title": "ARCH term (phi)"},
            "d": {"type": "number", "minimum": 0.05, "maximum": 0.95, "title": "Fractional difference (d)"},
            "beta": {"type": "number", "minimum": 0, "maximum": 0.975, "title": "GARCH term (beta)"},
            "truncation": {"type": "integer", "minimum": 32, "maximum": 2048, "default": 1000, "title": "Retained lag count"},
            **_VOLATILITY_OPTIONS,
        },
        assumptions=(
            "Complete regular zero-mean innovations with supplied coefficients. The operation does not estimate those coefficients.",
            "The finite filter retains the declared number of lags. Retained and omitted weight mass are reported.",
            "The underlying infinite-lag model has no finite unconditional variance. Reported variances use squared input units.",
            "Holdout uses rolling one-step variance. Multi-step forecasts propagate conditional expected squared innovations.",
        ),
    ),
    "prediction.native_ridge": NativeResearchOperation(
        kind="prediction_model", label="Ridge with holdout", module="ridge", runner="run_ridge",
        summary="Fit C++ Ridge with an unpenalized intercept and evaluate a reserved suffix against a mean baseline.",
        bindings=_PREDICTOR_BINDINGS,
        optional_bindings=("time_col",),
        options={
            "alpha": {"type": "number", "exclusiveMinimum": 0, "default": 1.0},
            "holdout_fraction": _HOLDOUT_FRACTION,
        },
        assumptions=_PREDICTION_ASSUMPTIONS,
    ),
    "prediction.native_ridge_selection": NativeResearchOperation(
        kind="prediction_model", label="Ridge with validation and holdout", module="ridge", adapter="ridge_selection",
        runner="run_ridge_selection", bindings={**_PREDICTOR_BINDINGS, "predictors": _columns("Predictors", 64)},
        optional_bindings=("time_col",),
        summary="Choose the ridge penalty on a validation block, then refit and score on a separate holdout.",
        options={
            "alpha_grid": {"type": "array", "items": {"type": "number", "exclusiveMinimum": 0},
                           "uniqueItems": True, "minItems": 2, "maxItems": 16, "default": [0.01, 0.1, 1, 10, 100],
                           "title": "Candidate ridge penalties"},
            "validation_fraction": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.25,
                                    "title": "Validation fraction of pre-holdout rows"},
            "holdout_fraction": {**_HOLDOUT_FRACTION, "title": "Final holdout fraction"},
        },
        assumptions=(*_PREDICTION_ASSUMPTIONS,
                     "Candidates fit the earliest block and are compared on later validation rows. Ties choose the larger penalty.",
                     "The selected penalty is refit on all pre-holdout rows. Final holdout outcomes are used only to score predictions."),
    ),
    "prediction.native_elastic_net": NativeResearchOperation(
        kind="prediction_model", label="Elastic Net with holdout", module="ridge", runner="run_elastic_net",
        summary="Fit C++ Elastic Net with a certified first-order convergence check and a reserved test suffix.",
        bindings={**_PREDICTOR_BINDINGS, "predictors": _columns("Predictors", 128)},
        optional_bindings=("time_col",),
        options={
            "alpha": {"type": "number", "exclusiveMinimum": 0, "title": "Penalty scale (mean squared loss)"},
            "l1_ratio": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1,
                         "title": "L1 penalty share"},
            "holdout_fraction": _HOLDOUT_FRACTION,
        },
        assumptions=(*_PREDICTION_ASSUMPTIONS, "The penalty combines L1 and L2 with both components strictly positive."),
    ),
    "prediction.native_logistic": NativeResearchOperation(
        kind="prediction_model", label="Logistic classification with holdout", module="ridge", runner="run_logistic",
        summary="Fit native L2-penalized binary probabilities and evaluate them against the training prevalence.",
        bindings={**_PREDICTOR_BINDINGS, "outcome": _column("Binary outcome (0 or 1)"),
                  "predictors": _columns("Predictors", 64)},
        optional_bindings=("time_col",),
        options={
            "alpha": {"type": "number", "minimum": 1e-6, "maximum": 1e6, "default": 1.0,
                      "title": "L2 penalty scale (mean log loss)"},
            "holdout_fraction": _HOLDOUT_FRACTION,
        },
        assumptions=(*_PREDICTION_ASSUMPTIONS,
                     "Numeric labels are 0 or 1. The training set must contain both classes.",
                     "Accuracy uses a 0.5 probability threshold. ROC AUC requires both holdout classes."),
    ),
    "prediction.native_cart": NativeResearchOperation(
        kind="prediction_model", label="Classification tree with holdout", module="ridge", adapter="cart", runner="run_cart",
        bindings={**_PREDICTOR_BINDINGS, "outcome": _column("Binary outcome (0 or 1)"),
                  "predictors": _columns("Predictors", 64)},
        optional_bindings=("time_col",),
        summary="Fit a bounded C++ CART classifier and compare held-out probabilities with training prevalence.",
        options={
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4, "title": "Maximum tree depth"},
            "min_samples_leaf": {"type": "integer", "minimum": 1, "maximum": 100_000, "default": 1,
                                 "title": "Minimum training rows per leaf"},
            "holdout_fraction": _HOLDOUT_FRACTION,
        },
        assumptions=(*_PREDICTION_ASSUMPTIONS, "Numeric labels are 0 or 1. The training set must contain both classes.",
                     "Splits minimize training Gini impurity; ties use predictor order and then the lower cut.",
                     "Leaf probabilities are Laplace-smoothed. Accuracy uses a 0.5 threshold."),
    ),
    "prediction.native_cart_regression": NativeResearchOperation(
        kind="prediction_model", label="Regression tree with holdout", module="ridge", adapter="cart_regression",
        runner="run_cart_regression",
        bindings={**_PREDICTOR_BINDINGS, "outcome": _column("Numeric outcome"), "predictors": _columns("Predictors", 64)},
        optional_bindings=("time_col",),
        summary="Fit a C++ squared-error CART tree and score its held-out predictions against the training mean.",
        options={
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4, "title": "Maximum tree depth"},
            "min_samples_leaf": {"type": "integer", "minimum": 1, "maximum": 100_000, "default": 1,
                                 "title": "Minimum training rows per leaf"},
            "holdout_fraction": _HOLDOUT_FRACTION,
        },
        assumptions=(*_PREDICTION_ASSUMPTIONS,
                     "Each leaf predicts its training mean. Splits minimize weighted child mean squared error.",
                     "Equal predictor values stay together. Near-ties use predictor order and the lower cut.",
                     "Holdout metrics measure prediction errors on the reserved suffix."),
    ),
    "prediction.native_random_forest_regression": NativeResearchOperation(
        kind="prediction_model", label="Random forest regression with holdout", module="ridge", adapter="random_forest",
        runner="run_random_forest_regression",
        bindings={**_PREDICTOR_BINDINGS, "outcome": _column("Numeric outcome"), "predictors": _columns("Predictors", 64)},
        optional_bindings=("time_col",),
        summary="Fit a seeded C++ regression forest and compare held-out predictions with the training mean.",
        options=_FOREST_OPTIONS,
        assumptions=(*_PREDICTION_ASSUMPTIONS,
                     "Each tree uses a training bootstrap and independent predictor subsets at its splits.",
                     "Predictions average the training leaf means across trees. The comparison baseline uses the original training mean.",
                     "The held-out errors describe the reserved sample; intervals and out-of-bag metrics are outside this operation."),
    ),
    "prediction.native_random_forest_classification": NativeResearchOperation(
        kind="prediction_model", label="Random forest classification with holdout", module="ridge",
        adapter="random_forest_classification", runner="run_random_forest_classification",
        bindings={**_PREDICTOR_BINDINGS, "outcome": _column("Binary outcome (0 or 1)"),
                  "predictors": _columns("Predictors", 64)},
        optional_bindings=("time_col",),
        summary="Fit a seeded C++ binary classification forest and evaluate held-out probabilities.",
        options=_FOREST_OPTIONS,
        assumptions=(*_PREDICTION_ASSUMPTIONS,
                     "Numeric labels are 0 or 1, and the training prefix must contain both classes.",
                     "Trees use training bootstraps and predictor subsets per split. The forest averages smoothed leaf probabilities.",
                     "Holdout scores use the training prevalence as a baseline. ROC AUC requires both holdout classes."),
    ),
    "quant.rolling_risk": NativeResearchOperation(
        kind="pack", label="Rolling asset risk", module="quant_replay", runner="run_rolling_risk",
        summary="Calculate native rolling volatility and latest-window covariance from aligned dated returns.",
        bindings={"time_col": _column("Return availability time"), "return_columns": _columns("Asset returns", 32)},
        options={"window": {"type": "integer", "minimum": 2, "maximum": 2048, "title": "Window observations"}},
        assumptions=(
            "Rows are ordered by the supplied availability time, with complete aligned observations.",
            "Volatility and sample covariance use n−1 and are reported in the input return frequency.",
            "Input timestamps alone do not verify data vintages.",
        ),
    ),
    "quant.replay": NativeResearchOperation(
        kind="pack", label="Portfolio replay", module="quant_replay", runner="run_replay",
        summary="Replay a simulated long-only allocation in Rust with explicit signal timing and trading costs.",
        bindings=_REPLAY_BINDINGS,
        options=_REPLAY_OPTIONS,
        assumptions=_REPLAY_ASSUMPTIONS,
    ),
    "quant.replay_fee_comparison": NativeResearchOperation(
        kind="pack", label="Portfolio replay fee comparison (Rust)", module="quant_replay", adapter="quant_fee_comparison",
        runner="run_replay_fee_comparison", bindings=_REPLAY_BINDINGS,
        summary="Compare two one-way fees on identical simulated targets, returns, and execution times.",
        options={
            "base_transaction_cost_bps": {**_REPLAY_OPTIONS["transaction_cost_bps"], "title": "Base fee (basis points)"},
            "higher_transaction_cost_bps": {**_REPLAY_OPTIONS["transaction_cost_bps"], "title": "Higher fee (basis points)"},
            "initial_equity": _REPLAY_OPTIONS["initial_equity"],
        },
        assumptions=(*_REPLAY_ASSUMPTIONS,
                     "Both paths begin with the same equity and use the same weights, returns, and clock.",
                     "The comparison subtracts base-fee metrics from higher-fee metrics."),
    ),
    "quant.replay_tail_risk": NativeResearchOperation(
        kind="pack", label="Historical portfolio tail risk", module="quant_replay", runner="run_replay_tail_risk",
        summary="Measure realized historical VaR and expected shortfall from fee-inclusive simulated returns.",
        bindings=_REPLAY_BINDINGS,
        options={
            **_REPLAY_OPTIONS,
            "window": {"type": "integer", "minimum": 2, "maximum": 2048, "title": "Trailing window (periods)"},
            "confidence_bps": {"type": "integer", "minimum": 1, "maximum": 9999, "default": 9500,
                               "title": "Confidence level (basis points)"},
            "end_period": {"type": "integer", "minimum": 0, "maximum": 10_000, "default": 0,
                           "title": "Last completed period (0 uses the final row)"},
        },
        assumptions=(*_REPLAY_ASSUMPTIONS,
                     "The window ends at the selected completed period. Positive values denote losses.",
                     "VaR is the inverse empirical loss CDF. Expected shortfall averages the worst tail with fractional boundary weighting.",
                     "This is a descriptive, per-period estimate from the simulated history."),
    ),
    "quant.min_variance": NativeResearchOperation(
        kind="pack", label="Long-only minimum variance (Rust)", module="quant_replay", adapter="portfolio",
        runner="run_min_variance", bindings={"time_col": _column("Return availability time"),
                                             "return_columns": _columns("Asset returns", 32, minimum=2)},
        summary="Estimate historical long-only weights using a completed trailing covariance window and an explicit shrinkage choice.",
        options={
            "window": {"type": "integer", "minimum": 2, "maximum": 2048, "title": "Completed window observations"},
            "end_period": {"type": "integer", "minimum": 0, "maximum": 10_000, "default": 0,
                           "title": "Last completed period (0 uses the final row)"},
            "shrinkage_bps": {"type": "integer", "minimum": 0, "maximum": 10_000, "default": 0,
                             "title": "Covariance shrinkage toward equal variances (basis points)"},
        },
        assumptions=(
            "Uses aligned returns in the selected completed window only. The timestamp column records supplied availability order.",
            "Weights are nonnegative and sum to one. Covariance uses the sample n−1 divisor; shrinkage is explicit.",
            "Both original and objective covariance are saved. Variance is per period in squared input units.",
            "Historical allocation analysis does not simulate trades or establish future returns.",
        ),
    ),
    "quant.min_variance_walk_forward": NativeResearchOperation(
        kind="pack", label="Walk-forward minimum variance (Rust)", module="quant_replay", adapter="walk_forward",
        runner="run_walk_forward",
        bindings={"time_col": _column("Period end"), "return_columns": _columns("Asset returns", 16, minimum=2)},
        summary="Evaluate a fixed rolling minimum-variance policy and an equal-weight benchmark with the same fees.",
        options={
            "window": {"type": "integer", "minimum": 2, "maximum": 512, "title": "Completed training periods"},
            "first_period": {"type": "integer", "minimum": 0, "maximum": 10_000, "default": 0,
                             "title": "First evaluation period (0 uses window + 2)"},
            "end_period": {"type": "integer", "minimum": 0, "maximum": 10_000, "default": 0,
                           "title": "Last evaluation period (0 uses the final row)"},
            "shrinkage_bps": {"type": "integer", "minimum": 0, "maximum": 10_000, "default": 0,
                             "title": "Covariance shrinkage (basis points)"},
            "transaction_cost_bps": {"type": "integer", "minimum": 0, "maximum": 9999, "default": 0,
                                     "title": "Trading fee (basis points)"},
            "initial_equity": {"type": "number", "exclusiveMinimum": 0, "default": 1.0, "title": "Initial equity"},
        },
        assumptions=(
            "Rows contain aligned simple asset returns with strictly ordered period ends. Period numbers start at one.",
            "For evaluation period t, the training window ends at t−2. Both portfolios rebalance at the end of t−1 before earning period t returns.",
            "Both portfolios start in cash, use the same fees and evaluate the same periods. Risk is per period.",
            "An infeasible allocation or insolvent portfolio stops the simulation. These historical results do not establish future performance.",
        ),
    ),
}
