"""Shared native operation admission, execution, and result projection."""

from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping

from .checks.ar_cancellation import check_cancellation
from .native_research_declarations import NATIVE_RESEARCH_OPERATIONS, _ARIMA_ORDER, _SEASONAL_ORDER


_MULTIVARIATE_FORECASTS = frozenset(("time_series.native_var", "time_series.native_vecm", "time_series.varma11_fixed_ma"))
_VARIANCE_FORECASTS = frozenset((
    "time_series.native_volatility", "time_series.native_egarch", "time_series.native_igarch", "time_series.figarch_fixed",
))
_RESULT_OPERATION_TOKENS = {operation.replace(".", "_"): operation for operation in NATIVE_RESEARCH_OPERATIONS}


def native_result_operation(artifact_id: str) -> str | None:
    prefix = "workflow_capability_"
    if artifact_id.startswith(prefix):
        return _RESULT_OPERATION_TOKENS.get(artifact_id[len(prefix):].rsplit("_", 2)[0])
    return None


def read_native_result_bytes(run_root: Path, entry: dict, path: Path, operation: str) -> bytes | None:
    """Read the bytes attested by both the artifact registry and its result node."""
    from .lineage.node_write_validation import _read_indexed_node_hash

    digest = entry.get("sha256")
    if (entry.get("artifact_type") != "workflow_capability_result" or entry.get("step") != operation
            or not isinstance(digest, str) or path.suffix != ".json"):
        return None
    try:
        if digest != _read_indexed_node_hash(run_root, f"native-result:{entry['artifact_id']}"):
            return None
        with path.open("rb") as stream:
            raw = stream.read(16_000_001)
    except (OSError, ValueError):
        return None
    return raw if len(raw) <= 16_000_000 and sha256(raw).hexdigest() == digest else None


def validate_native_research_size(operation_id: str, spec: Mapping[str, Any], rows: int) -> None:
    """Check row bounds on a validated step before touching data values or the engine."""
    declaration = NATIVE_RESEARCH_OPERATIONS[operation_id]
    options = spec["options"]
    if operation_id == "prediction.native_forest_apply":
        from .native_prediction_apply import validate_apply_size

        validate_apply_size(rows)
    elif operation_id == "time_series.correlogram":
        from .native_time_series import validate_correlogram_size

        validate_correlogram_size(rows, options.get("max_lag", declaration.options["max_lag"]["default"]))
    elif operation_id == "time_series.stationarity_statistic":
        from .native_stationarity import validate_stationarity_size

        validate_stationarity_size(rows, options["method"], options["lag"])
    elif operation_id in {"time_series.native_arima", "time_series.arima_residual_check"}:
        from .native_time_series import validate_arima_size

        names = ("ar_order", "differences", "ma_order", "deterministic", "holdout_periods")
        validate_arima_size(rows, *(options.get(name, declaration.options[name]["default"]) for name in names))
    elif operation_id == "time_series.native_sarima":
        from .native_time_series import validate_sarima_size

        names = ("ar_order", "differences", "ma_order", "seasonal_ar_order", "seasonal_differences",
                 "seasonal_ma_order", "seasonal_period", "deterministic", "holdout_periods")
        validate_sarima_size(rows, *(options.get(name, declaration.options[name].get("default")) for name in names))
    elif operation_id in {"time_series.native_arimax", "time_series.native_sarimax"}:
        from .native_time_series_xreg import validate_xreg_size

        order = tuple(options.get(name, declaration.options[name]["default"]) for name in _ARIMA_ORDER)
        seasonal = tuple(options.get(name, declaration.options[name].get("default")) for name in _SEASONAL_ORDER
                         ) if operation_id == "time_series.native_sarimax" else None
        validate_xreg_size(rows, len(spec["column_bindings"]["predictors"]), order, seasonal,
                           options.get("deterministic", "none"), options["forecast_periods"], options.get("holdout_periods", 0))
    elif operation_id == "time_series.native_var":
        from .native_var import validate_var_size

        validate_var_size(rows, len(spec["column_bindings"]["series_columns"]), options.get("lag_order", 1),
                          options.get("intercept", True), options.get("holdout_periods", 0))
    elif operation_id == "time_series.native_vecm":
        from .native_vecm import validate_vecm_size

        validate_vecm_size(rows, len(spec["column_bindings"]["series_columns"]),
                           options.get("difference_lags", 1), options.get("holdout_periods", 0))
    elif operation_id == "time_series.johansen_rank":
        from .native_johansen import validate_johansen_size

        validate_johansen_size(rows, len(spec["column_bindings"]["series_columns"]), options.get("difference_lags", 1))
    elif operation_id == "time_series.varma11_fixed_ma":
        from .native_varma import validate_varma11_size

        validate_varma11_size(rows, len(spec["column_bindings"]["series_columns"]),
                              options.get("intercept", True), options.get("holdout_periods", 0))
    elif operation_id == "time_series.native_arfima":
        from .native_arfima import validate_arfima_size

        validate_arfima_size(rows, options.get("difference"), options.get("holdout_periods", 0))
    elif operation_id == "time_series.markov_switching":
        from .native_markov import validate_markov_size

        validate_markov_size(rows, options.get("holdout_periods", 0))
    elif operation_id in {"time_series.holt_winters_additive", "time_series.holt_winters_fit_alpha"}:
        from .native_time_series_ets import validate_holt_winters_size

        validate_holt_winters_size(rows, options["season_period"], options.get("holdout_periods", 0))
    elif operation_id == "time_series.holt_winters_fit_joint":
        from .native_time_series_ets import validate_holt_winters_joint_size

        validate_holt_winters_joint_size(rows, options["season_period"], options.get("holdout_periods", 0))
    elif operation_id in {"time_series.ets_trend", "time_series.ets_trend_estimate"}:
        from .native_ets_trend import validate_ets_trend_size

        free_gains = sum(options.get(name) is None for name in ("alpha", "beta")) if operation_id.endswith("_estimate") else 0
        validate_ets_trend_size(rows, options.get("holdout_periods", 0), free_gains)
    elif operation_id == "time_series.figarch_fixed":
        from .native_figarch import validate_figarch_size

        validate_figarch_size(rows, options.get("holdout_periods", 0), options.get("forecast_periods", 1),
                              options.get("truncation", 1000))
    elif operation_id in _VARIANCE_FORECASTS:
        from .native_volatility import validate_volatility_size

        validate_volatility_size(rows, options.get("holdout_periods", declaration.options["holdout_periods"]["default"]))
    elif declaration.module == "time_series":
        from .native_time_series import validate_local_level_holdout, validate_local_level_rows

        holdout = options.get("holdout_periods", declaration.options["holdout_periods"]["default"])
        validate_local_level_rows(rows)
        validate_local_level_holdout(rows, holdout, fit_scale=operation_id == "time_series.local_level_fit")
    elif declaration.module == "ridge":
        from .native_ridge import nominal_training_rows, validate_prediction_size

        columns = len(spec["column_bindings"]["predictors"])
        holdout = options.get("holdout_fraction", declaration.options["holdout_fraction"]["default"])
        if operation_id == "prediction.native_ridge_selection":
            from .native_ridge_selection import validate_ridge_selection_size

            validate_ridge_selection_size(
                rows, columns, holdout_fraction=holdout,
                **{name: options.get(name, declaration.options[name]["default"])
                   for name in ("alpha_grid", "validation_fraction")},
            )
            return
        if operation_id in {"prediction.native_random_forest_regression", "prediction.native_random_forest_classification"}:
            from .native_random_forest import validate_random_forest_size

            names = ("n_trees", "max_depth", "min_samples_leaf", "max_features", "seed")
            validate_random_forest_size(
                rows, columns, training_rows=nominal_training_rows(rows, holdout),
                **{name: options.get(name, declaration.options[name]["default"]) for name in names},
            )
            return
        if operation_id in {"prediction.native_cart", "prediction.native_cart_regression"}:
            from .native_cart import validate_cart_size

            validate_cart_size(rows, columns, options.get("max_depth", 4), options.get("min_samples_leaf", 1),
                               nominal_training_rows(rows, holdout))
            return
        if operation_id == "prediction.native_logistic":
            from .native_ridge import validate_logistic_size

            validate_logistic_size(rows, columns)
        else:
            validate_prediction_size(rows, columns, elastic_net=operation_id == "prediction.native_elastic_net")
        nominal_training_rows(rows, holdout)
    elif operation_id in {"quant.replay", "quant.replay_fee_comparison"}:
        from .native_quant_replay import validate_replay_rows

        validate_replay_rows(rows)
        if operation_id == "quant.replay_fee_comparison":
            from .native_quant_fee_comparison import validate_replay_fee_comparison_options

            validate_replay_fee_comparison_options(
                options["base_transaction_cost_bps"], options["higher_transaction_cost_bps"], options["initial_equity"],
            )
    elif operation_id == "quant.rolling_risk":
        from .native_quant_replay import validate_risk_rows, validate_risk_window

        validate_risk_rows(rows)
        validate_risk_window(rows, options["window"])
    elif operation_id == "quant.replay_tail_risk":
        from .native_quant_replay import validate_tail_risk_window

        validate_tail_risk_window(rows, options["window"], options.get("end_period", 0))
    elif operation_id == "quant.min_variance":
        from .native_portfolio import validate_min_variance_window

        validate_min_variance_window(rows, options["window"], options.get("end_period", 0))
    elif operation_id == "quant.min_variance_walk_forward":
        from .native_walk_forward import validate_walk_forward_size

        validate_walk_forward_size(rows, options["window"], options.get("first_period", 0), options.get("end_period", 0))


def compute_native_research(frame, request):
    """Invoke the named built-in adapter and separate locally displayed detail."""
    operation_id = request["operation_id"]
    declaration = NATIVE_RESEARCH_OPERATIONS[operation_id]
    bindings = request["column_bindings"]
    run = getattr(import_module(f".native_{declaration.adapter or declaration.module}", __package__), declaration.runner)
    check_cancellation()
    result = run(frame, **bindings, **request["options"])
    check_cancellation()
    local = None
    if operation_id == "time_series.correlogram":
        correlogram = {key: result.pop(key) for key in ("lags", "acf", "pacf")}
        local = {"correlogram": correlogram}
        result["metrics"] = {
            "lag_one_acf": correlogram["acf"][1],
            "lag_one_pacf": correlogram["pacf"][1],
            "at_max_lag": {"lag": correlogram["lags"][-1], "acf": correlogram["acf"][-1], "pacf": correlogram["pacf"][-1]},
        }
    elif operation_id == "time_series.johansen_rank":
        local = {"sample": result.pop("sample")}
    elif operation_id in _MULTIVARIATE_FORECASTS:
        local = result.pop("local")
        forecast = result.pop("forecast")
        local["series_forecasts"] = forecast
        if result["holdout"] is not None:
            holdout = result["holdout"]
            local["series_holdout_forecasts"] = holdout.pop("forecast")
            local["holdout_forecast_covariance"] = holdout.pop("forecast_covariance")
            local["holdout_origin_time"] = holdout.pop("origin_time")
        result["forecast"] = {
            "steps": request["options"]["forecast_periods"],
            "last_by_series": {
                str(i): {"series": name, **{key: curve[key][-1] for key in ("mean", "lower", "upper")}}
                for i, (name, curve) in enumerate(forecast.items())
            },
        }
    elif declaration.module == "time_series" and operation_id != "time_series.stationarity_statistic":
        fit = dict(result["fit"])
        forecast = result["forecast"]
        variance_only = operation_id in _VARIANCE_FORECASTS
        forecast_key = "variance_forecast" if variance_only else "forecast"
        local = {forecast_key: forecast}
        if operation_id in {"time_series.native_arima", "time_series.native_sarima", "time_series.arima_residual_check",
                            "time_series.native_arimax", "time_series.native_sarimax"}:
            diagnostics = fit["diagnostics"]
            local["innovation_lag_correlations"] = diagnostics["paired_lag_correlations"]
            fit["diagnostics"] = {
                "standardized_innovation_mean": diagnostics["standardized_innovation_mean"],
                "standardized_innovation_rms": diagnostics["standardized_innovation_rms"],
                "lag_one": local["innovation_lag_correlations"][0],
                **({"whiteness": diagnostics["whiteness"]} if "whiteness" in diagnostics else {}),
            }
        elif "trace" in fit:
            local["trace"] = fit.pop("trace")
        if operation_id == "time_series.holt_winters_fit_alpha":
            local["alpha_grid_sse"] = result["estimation"].pop("alpha_grid_sse")
        if operation_id == "time_series.figarch_fixed":
            local["lag_weights"] = result.pop("lag_weights")
        holdout = result["holdout"]
        if holdout is not None:
            local["holdout_variance" if variance_only else "holdout_forecast"] = holdout["forecast"]
            local["holdout_origin_time"] = holdout["origin_time"]
            holdout = {key: value for key, value in holdout.items() if key not in {"forecast", "origin_time"}}
        if variance_only:
            fields = ("variance", "log_variance") if operation_id == "time_series.native_egarch" else ("variance",)
        elif operation_id == "time_series.markov_switching":
            fields = ("mean", "lower", "upper", "probability_low", "probability_high", "observation_variance")
        else:
            fields = ("mean", "lower", "upper")
        result = {
            **result, "fit": fit, "holdout": holdout,
            "forecast": {
                "steps": request["options"]["forecast_periods"],
                "first": {key: forecast[key][0] for key in fields},
                "last": {key: forecast[key][-1] for key in fields},
            },
        }
    elif declaration.module == "ridge":
        split = dict(result["split"])
        local = {
            "split_times": {key: split.pop(key) for key in ("train_last_time", "test_first_time")},
            "prediction_basis": result.pop("prediction_basis"),
        }
        result["split"] = split
    elif operation_id == "quant.replay_fee_comparison":
        local = {"fee_comparison": result.pop("series")}
        result["policy"] = result.pop("assumptions")
    elif declaration.module == "quant_replay":
        local_fields = {
            "quant.rolling_risk": ("series", "latest_covariance"),
            "quant.replay": ("series",),
            "quant.replay_tail_risk": ("tail_window",),
            "quant.min_variance": ("sample_covariance", "objective_covariance", "cutoff"),
            "quant.min_variance_walk_forward": ("strategy_series", "benchmark_series", "decisions"),
        }[operation_id]
        local = {key: result[key] for key in local_fields}
        result = {**{key: value for key, value in result.items() if key not in (*local_fields, "assumptions")},
                  "policy": result["assumptions"]}
    return {**result, "operation_id": operation_id, "n_rows": len(frame),
            "assumptions": list(declaration.assumptions)}, local


def native_result_caption(result: dict[str, Any]) -> str:
    operation_id = result["operation_id"]
    if operation_id == "time_series.stationarity_statistic":
        return f"{result['method'].upper()} statistic {result['statistic']:.4g} · fixed lag {result['policy']['lag']} · {result['n_effective']:,} effective rows"
    if operation_id == "time_series.correlogram":
        return f"{result['policy']['outcome']} · {result['n_observations']:,} observed · {result['policy']['max_lag']} lags"
    if operation_id == "time_series.johansen_rank":
        return f"{len(result['ranks'])} rank hypotheses · {result['n_effective']:,} effective periods"
    if operation_id == "time_series.native_var":
        return f"{len(result['policy']['series_columns'])} series · lag {result['policy']['lag_order']} · {result['forecast']['steps']} forecast periods"
    if operation_id == "time_series.native_vecm":
        return f"2 series · rank 1 · {result['forecast']['steps']} forecast periods"
    if operation_id == "time_series.varma11_fixed_ma":
        return f"2 series · fixed MA {result['policy']['ma_coefficient']:.4g} · {result['forecast']['steps']} forecast periods"
    if operation_id.startswith("time_series."):
        return f"{result['policy']['outcome']} · {result['fit']['n_observed']:,} observed · {result['forecast']['steps']} forecast periods"
    if operation_id in {"prediction.native_logistic", "prediction.native_cart", "prediction.native_random_forest_classification"}:
        return f"{result['outcome']} · {result['split']['test_rows']:,} test rows · log loss {result['metrics']['log_loss']:.4g}"
    if operation_id.startswith("prediction."):
        return f"{result['outcome']} · {result['split']['test_rows']:,} test rows · RMSE {result['metrics']['rmse']:.4g}"
    if operation_id == "quant.replay":
        return f"{result['inputs']['asset_count']} assets · {result['n_rows']:,} periods · {result['metrics']['cumulative_net_return']:+.2%} net"
    if operation_id == "quant.replay_fee_comparison":
        difference = result["metrics"]["higher_minus_base"]["cumulative_net_return"]
        return f"{result['n_rows']:,} periods · higher-fee net return difference {100 * difference:+.2f} pp"
    if operation_id == "quant.replay_tail_risk":
        return f"{result['metrics']['window']:,} periods · VaR {result['metrics']['value_at_risk']:.2%} · ES {result['metrics']['expected_shortfall']:.2%}"
    if operation_id == "quant.min_variance":
        return f"{result['inputs']['asset_count']} assets · {result['inputs']['window']} periods · variance {result['metrics']['sample_variance']:.4g}"
    if operation_id == "quant.min_variance_walk_forward":
        periods = result["inputs"]["end_period"] - result["inputs"]["first_period"] + 1
        difference = result["metrics"]["cumulative_net_return_difference"]
        return f"{result['inputs']['asset_count']} assets · {periods} evaluated periods · net return difference {100 * difference:+.2f} pp"
    return f"{result['inputs']['asset_count']} assets · {result['metrics']['complete_windows']:,} complete risk windows"
