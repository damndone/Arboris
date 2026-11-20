"""The same native research operation contracts serve manual and Agent workflows."""

from copy import deepcopy
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationRegistry
from workbench.agent.workflow_capability_registry import workflow_capability_registry
from workbench.artifacts import sha256_file
from workbench.native_build import default_output, manifest_path
from workbench.services.operation_catalog import operation_catalog


CASES = {
    "time_series.correlogram": (
        {"time_col": "t", "outcome": "y"}, {"max_lag": 4},
    ),
    "time_series.stationarity_statistic": (
        {"time_col": "t", "outcome": "y"}, {"method": "adf", "lag": 2},
    ),
    "time_series.native_arima": (
        {"time_col": "t", "outcome": "y"},
        {"ar_order": 0, "differences": 1, "forecast_periods": 4, "holdout_periods": 3},
    ),
    "time_series.arima_residual_check": (
        {"time_col": "time", "outcome": "y"},
        {"ar_order": 1, "ma_order": 1, "whiteness_lag": 6, "forecast_periods": 4},
    ),
    "time_series.native_sarima": (
        {"time_col": "t", "outcome": "y"},
        {"ar_order": 0, "seasonal_differences": 1, "seasonal_period": 4, "forecast_periods": 5, "holdout_periods": 3},
    ),
    "time_series.native_arimax": (
        {"time_col": "t", "outcome": "y", "predictors": ["x"]},
        {"ar_order": 0, "forecast_periods": 4, "holdout_periods": 8},
    ),
    "time_series.native_sarimax": (
        {"time_col": "t", "outcome": "y", "predictors": ["x"]},
        {"ar_order": 0, "seasonal_differences": 1, "seasonal_period": 4, "forecast_periods": 4, "holdout_periods": 8},
    ),
    "time_series.native_var": (
        {"time_col": "t", "series_columns": ["a", "b"], "granger_effect": "a", "granger_excluded": ["b"]},
        {"lag_order": 2, "forecast_periods": 5, "holdout_periods": 7, "irf_periods": 5},
    ),
    "time_series.native_vecm": (
        {"time_col": "t", "series_columns": ["a", "b"]},
        {"difference_lags": 2, "forecast_periods": 5, "holdout_periods": 7},
    ),
    "time_series.johansen_rank": (
        {"time_col": "t", "series_columns": ["a", "b", "c"]}, {"difference_lags": 1},
    ),
    "time_series.varma11_fixed_ma": (
        {"time_col": "t", "series_columns": ["a", "b"]},
        {"ma_coefficient": 0.4, "forecast_periods": 5, "holdout_periods": 7, "irf_periods": 5},
    ),
    "time_series.markov_switching": (
        {"time_col": "t", "outcome": "y"},
        {"forecast_periods": 4, "holdout_periods": 8},
    ),
    "time_series.native_arfima": (
        {"time_col": "t", "outcome": "y"},
        {"difference": 0.25, "forecast_periods": 4, "holdout_periods": 3},
    ),
    "time_series.holt_winters_additive": (
        {"time_col": "t", "outcome": "y"},
        {"season_period": 3, "alpha": 0.4, "beta": 0.2, "gamma": 0.15, "forecast_periods": 4},
    ),
    "time_series.holt_winters_fit_alpha": (
        {"time_col": "t", "outcome": "y"},
        {"season_period": 3, "beta": 0.2, "gamma": 0.15, "forecast_periods": 4, "holdout_periods": 3},
    ),
    "time_series.holt_winters_fit_joint": (
        {"time_col": "t", "outcome": "y"},
        {"season_period": 4, "forecast_periods": 2, "holdout_periods": 8, "confidence_level": 0.99},
    ),
    "time_series.ets_trend": (
        {"time_col": "t", "outcome": "y"},
        {"alpha": 0.4, "beta": 0.12, "phi": 0.8, "forecast_periods": 4, "holdout_periods": 3},
    ),
    "time_series.ets_trend_estimate": (
        {"time_col": "t", "outcome": "y"},
        {"phi": 1.0, "forecast_periods": 6, "holdout_periods": 12},
    ),
    "time_series.native_volatility": (
        {"time_col": "t", "outcome": "y"},
        {"family": "gjr_garch_1_1_1", "forecast_periods": 4, "holdout_periods": 20},
    ),
    "time_series.native_egarch": (
        {"time_col": "t", "outcome": "y"}, {"holdout_periods": 20},
    ),
    "time_series.native_igarch": (
        {"time_col": "t", "outcome": "y"},
        {"forecast_periods": 4, "holdout_periods": 20},
    ),
    "time_series.figarch_fixed": (
        {"time_col": "t", "outcome": "y"},
        {"omega": 0.15, "phi": 0.2, "d": 0.35, "beta": 0.4, "truncation": 64,
         "forecast_periods": 4, "holdout_periods": 3},
    ),
    "time_series.local_level": (
        {"time_col": "t", "outcome": "y"},
        {"process_variance": 0.1, "observation_variance": 0.5,
         "initial_mean": 0.0, "initial_variance": 1.0, "forecast_periods": 4, "holdout_periods": 3},
    ),
    "time_series.local_level_fit": (
        {"time_col": "t", "outcome": "y"},
        {"variance_ratio": 0.3, "initial_mean": 0.0, "relative_initial_variance": 2.0,
         "forecast_periods": 4, "holdout_periods": 3},
    ),
    "prediction.native_ridge": (
        {"outcome": "y", "predictors": ["x"], "time_col": "t"},
        {"alpha": 0.2, "holdout_fraction": 0.25},
    ),
    "prediction.native_ridge_selection": (
        {"outcome": "y", "predictors": ["x"], "time_col": "t"},
        {"alpha_grid": [0.1, 1, 6, 24], "validation_fraction": 0.25, "holdout_fraction": 0.2},
    ),
    "prediction.native_elastic_net": (
        {"outcome": "y", "predictors": ["x"], "time_col": "t"},
        {"alpha": 0.2, "l1_ratio": 0.5, "holdout_fraction": 0.25},
    ),
    "prediction.native_logistic": (
        {"outcome": "binary", "predictors": ["x"], "time_col": "t"},
        {"alpha": 0.2, "holdout_fraction": 0.25},
    ),
    "prediction.native_cart": (
        {"outcome": "binary", "predictors": ["x"], "time_col": "t"},
        {"max_depth": 2, "min_samples_leaf": 2, "holdout_fraction": 0.25},
    ),
    "prediction.native_cart_regression": (
        {"outcome": "y", "predictors": ["x"], "time_col": "t"},
        {"max_depth": 2, "min_samples_leaf": 2, "holdout_fraction": 0.25},
    ),
    "prediction.native_random_forest_regression": (
        {"outcome": "y", "predictors": ["x", "z"], "time_col": "t"},
        {"n_trees": 5, "max_depth": 3, "min_samples_leaf": 2, "max_features": 1, "seed": 731, "holdout_fraction": 0.2},
    ),
    "prediction.native_random_forest_classification": (
        {"outcome": "binary", "predictors": ["x", "z"], "time_col": "t"},
        {"n_trees": 9, "max_depth": 3, "min_samples_leaf": 2, "max_features": 1, "seed": 731, "holdout_fraction": 1 / 3},
    ),
    "quant.replay": (
        {"signal_time_col": "signal", "execution_time_col": "start", "end_time_col": "end",
         "return_columns": ["ret"], "weight_columns": ["weight"]},
        {"transaction_cost_bps": 5.0, "initial_equity": 1_000.0},
    ),
    "quant.replay_fee_comparison": (
        {"signal_time_col": "signal", "execution_time_col": "start", "end_time_col": "end",
         "return_columns": ["a", "b"], "weight_columns": ["wa", "wb"]},
        {"base_transaction_cost_bps": 0.0, "higher_transaction_cost_bps": 156.25, "initial_equity": 100.0},
    ),
    "quant.replay_tail_risk": (
        {"signal_time_col": "signal", "execution_time_col": "start", "end_time_col": "end",
         "return_columns": ["ret"], "weight_columns": ["weight"]},
        {"transaction_cost_bps": 5.0, "initial_equity": 1_000.0,
         "window": 4, "confidence_bps": 9500, "end_period": 9},
    ),
    "quant.rolling_risk": (
        {"time_col": "t", "return_columns": ["ret"]},
        {"window": 4},
    ),
    "quant.min_variance": (
        {"time_col": "t", "return_columns": ["ret", "ret2"]},
        {"window": 5, "end_period": 9, "shrinkage_bps": 600},
    ),
    "quant.min_variance_walk_forward": (
        {"time_col": "t", "return_columns": ["ret", "ret2"]},
        {"window": 4, "end_period": 10, "shrinkage_bps": 1000, "transaction_cost_bps": 10},
    ),
}


@pytest.fixture(params=[
    ("time_series.correlogram", "time_series"),
    ("time_series.stationarity_statistic", "time_series"),
    ("time_series.native_arima", "time_series"),
    ("time_series.arima_residual_check", "time_series"),
    ("time_series.native_sarima", "time_series"),
    ("time_series.native_sarima", "time_series", 24),
    ("time_series.native_arimax", "time_series"),
    ("time_series.native_sarimax", "time_series"),
    ("time_series.native_sarimax", "time_series", 24),
    ("time_series.native_var", "time_series"),
    ("time_series.native_vecm", "time_series"),
    ("time_series.johansen_rank", "time_series"),
    ("time_series.varma11_fixed_ma", "time_series"),
    ("time_series.markov_switching", "time_series"),
    ("time_series.native_arfima", "time_series"),
    ("time_series.holt_winters_additive", "time_series"),
    ("time_series.holt_winters_fit_alpha", "time_series"),
    ("time_series.holt_winters_fit_joint", "time_series"),
    ("time_series.ets_trend", "time_series"),
    ("time_series.ets_trend_estimate", "time_series"),
    ("time_series.native_volatility", "time_series"),
    ("time_series.native_egarch", "time_series"),
    ("time_series.native_igarch", "time_series"),
    ("time_series.figarch_fixed", "time_series"),
    ("time_series.local_level", "time_series"),
    ("time_series.local_level_fit", "time_series"),
    ("prediction.native_ridge", "ridge"),
    ("prediction.native_ridge_selection", "ridge"),
    ("prediction.native_elastic_net", "ridge"),
    ("prediction.native_logistic", "ridge"),
    ("prediction.native_cart", "ridge"),
    ("prediction.native_cart_regression", "ridge"),
    ("prediction.native_random_forest_regression", "ridge"),
    ("prediction.native_random_forest_classification", "ridge"),
    ("quant.replay", "quant_replay"),
    ("quant.replay_fee_comparison", "quant_replay"),
    ("quant.replay_tail_risk", "quant_replay"),
    ("quant.rolling_risk", "quant_replay"),
    ("quant.min_variance", "quant_replay"),
    ("quant.min_variance_walk_forward", "quant_replay"),
], ids=["correlogram", "stationarity", "arima", "arima_residual", "sarima", "sarima_hourly", "arimax", "sarimax", "sarimax_hourly",
        "var", "vecm", "johansen", "varma", "markov", "arfima",
        "holt_winters", "holt_winters_fit", "holt_winters_joint", "ets_trend", "estimated_ets", "volatility", "egarch", "igarch", "figarch",
        "local_level", "local_level_fit", "ridge", "ridge_selection", "elastic_net", "logistic", "cart", "cart_regression",
        "random_forest", "classification_forest", "quant_replay", "fee_comparison", "tail_risk", "rolling_risk",
        "minimum_variance", "walk_forward"])
def native_case(request):
    operation_id, module, *season = request.param
    native = Path(__file__).resolve().parents[1] / "native" / module
    if not manifest_path(default_output(native)).is_file():
        pytest.skip(f"Explicit native build required for {module}")
    bindings, options = CASES[operation_id]
    frame = pd.DataFrame({
        "t": list(range(12)), "y": [i / 2 + i % 3 for i in range(12)],
        "x": [i + i % 2 for i in range(12)], "binary": [0, 1] * 6, "signal": list(range(-1, 11)),
        "start": list(range(12)), "end": list(range(1, 13)),
        "ret": [0.01, -0.005] * 6, "ret2": [0.005, 0.002, -0.009] * 4, "weight": [0.4, 0.5] * 6,
    })
    if season:
        from tests.test_native_sarima_period24 import HISTORY, HORIZON, hourly_exogenous_frame, hourly_frame

        bindings = {"time_col": "time", "outcome": "y"}
        options = {"ar_order": 0, "seasonal_period": season[0], "forecast_periods": HORIZON, "holdout_periods": 12}
        if operation_id == "time_series.native_sarimax":
            bindings["predictors"] = ["promotion", "load"]
            frame = hourly_exogenous_frame()
        else:
            frame = hourly_frame().iloc[:HISTORY]
    elif operation_id == "time_series.stationarity_statistic":
        values = np.random.default_rng(5408).standard_normal(40)
        frame = pd.DataFrame({"t": range(len(values)), "y": values})
    elif operation_id == "time_series.arima_residual_check":
        frame = pd.read_csv(Path(__file__).with_name("fixtures") / "arima_whiteness_r_case.csv", float_precision="round_trip")
    elif operation_id == "time_series.ets_trend_estimate":
        from tests.native_ets_reference import trend_fixture

        observed = trend_fixture()
        frame = pd.DataFrame({"t": range(len(observed)), "y": observed})
    elif operation_id == "prediction.native_random_forest_regression":
        frame = pd.DataFrame({
            "t": range(10), "x": [0, 1, 2, 3, 4, 5, 6, 7, 1.5, 6.5], "z": [0, 1] * 5,
            "y": [0, 0, 1, 1, 8, 8, 9, 9, 3, 7],
        })
    elif operation_id == "prediction.native_random_forest_classification":
        frame = pd.DataFrame({
            "t": range(12), "x": [*range(8), 0.5, 2.5, 4.5, 6.5], "z": [0, 1] * 6,
            "binary": [0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 1, 0],
        })
    elif operation_id == "prediction.native_ridge_selection":
        frame = pd.DataFrame({"t": range(10), "x": [-1, 1] * 5,
                              "y": [-2, 2] * 3 + [-1, 1, -1.5, 1.5]})
    elif operation_id == "quant.replay_fee_comparison":
        frame = pd.DataFrame({"signal": range(4), "start": range(1, 5), "end": range(2, 6),
                              "a": [0.125] * 4, "b": [-0.0625] * 4,
                              "wa": [0.5] * 4, "wb": [0.25] * 4})
    elif operation_id == "time_series.native_sarima":
        values = [10., 20., 30., 40., 12., 17., 31., 38., 13., 20., 32., 39., 14.]
        frame = pd.DataFrame({"t": range(len(values)), "y": values})
    elif operation_id == "time_series.holt_winters_fit_joint":
        from tests.test_native_holt_winters_joint import portable_simulation

        values = portable_simulation()
        frame = pd.DataFrame({"t": np.arange(1, len(values) + 1), "y": values})
    elif operation_id.startswith("time_series.holt_winters_"):
        frame["y"] += 0.15 * np.sin(0.7 * frame["t"])
    elif operation_id in {"time_series.native_arimax", "time_series.native_sarimax", "time_series.native_var"}:
        from tests.test_native_research_extensions import var_frame, xreg_frame

        frame = var_frame() if operation_id == "time_series.native_var" else xreg_frame(operation_id == "time_series.native_sarimax")
    elif operation_id == "time_series.native_vecm":
        from tests.vecm_fixed_rank_reference import fixture

        values = fixture(547)
        frame = pd.DataFrame({"t": np.arange(len(values)), "a": values[:, 0], "b": values[:, 1]})
    elif operation_id == "time_series.johansen_rank":
        levels = np.random.default_rng(382).normal(size=(80, 3)).cumsum(axis=0)
        frame = pd.DataFrame(levels, columns=["a", "b", "c"]).assign(t=np.arange(80))
    elif operation_id == "time_series.varma11_fixed_ma":
        from tests.varma11_fixed_ma_reference import fixture

        values = fixture(711, 0.4, True)
        frame = pd.DataFrame({"t": np.arange(len(values)), "a": values[:, 0], "b": values[:, 1]})
    elif operation_id == "time_series.markov_switching":
        from tests.test_native_markov import regime_frame

        frame = regime_frame()
    elif operation_id == "time_series.native_egarch":
        from tests.test_native_egarch import CASES as EGARCH_CASES, synthetic

        values = synthetic(EGARCH_CASES[0], rows=320)
        frame = pd.DataFrame({"t": np.arange(len(values)), "y": values})
    elif operation_id == "time_series.native_igarch":
        from tests.test_native_igarch import synthetic

        values = synthetic(rows=500)
        frame = pd.DataFrame({"t": np.arange(len(values)), "y": values})
    elif operation_id == "time_series.native_volatility":
        rng = np.random.default_rng(401)
        innovations = rng.standard_normal(800)
        variance = 1.0
        observed = np.empty_like(innovations)
        for index, innovation in enumerate(innovations):
            shock = innovation * np.sqrt(variance)
            observed[index] = shock
            variance = 0.05 + (0.07 + 0.14 * (shock < 0)) * shock**2 + 0.78 * variance
        frame = pd.DataFrame({"t": range(len(observed)), "y": observed})
    return operation_id, frame, {"input_mode": "frame", "column_bindings": bindings, "options": options}


@pytest.mark.parametrize("operation_id", CASES)
def test_native_contract_is_discoverable_and_closed(operation_id):
    bindings, options = CASES[operation_id]
    operations = {entry["id"]: entry for entry in operation_catalog()["operations"]}
    assert operations[operation_id]["execution"]["path"] == "/operations/run"
    assert operation_id in OperationRegistry().operation_ids()
    operation = workflow_capability_registry().require(operation_id)
    request = {"operation_id": operation_id, "input_mode": "frame",
               "column_bindings": bindings, "options": options}
    normalized = operation.validate(request)
    assert normalized["column_bindings"] == bindings
    assert normalized["options"] | options == normalized["options"]
    for field, unknown in (("column_bindings", "extra"), ("options", "code")):
        invalid = deepcopy(request)
        invalid[field][unknown] = "not part of this contract"
        with pytest.raises(ValueError, match=unknown):
            operation.validate(invalid)


@pytest.mark.parametrize(
    "operation_id, field, value",
    [("time_series.local_level", "forecast_periods", 201),
     ("time_series.local_level", "forecast_periods", 4.0),
     ("time_series.correlogram", "max_lag", 0),
     ("time_series.correlogram", "max_lag", 4.0),
     ("prediction.native_ridge", "holdout_fraction", 1.0),
     ("prediction.native_logistic", "alpha", 1e-7),
     ("quant.replay", "transaction_cost_bps", 10_000)],
)
def test_invalid_native_options_fail_before_execution(operation_id, field, value):
    bindings, options = CASES[operation_id]
    operation = workflow_capability_registry().require(operation_id)
    with pytest.raises(ValueError, match=field):
        operation.validate({"operation_id": operation_id, "input_mode": "frame",
                            "column_bindings": bindings, "options": {**options, field: value}})


@pytest.mark.parametrize("operation_id", ["time_series.native_sarima", "time_series.native_sarimax"])
def test_hourly_daily_period_uses_the_shared_seasonal_contract(operation_id):
    operation = workflow_capability_registry().require(operation_id)
    bindings, options = CASES[operation_id]
    request = {"operation_id": operation_id, "input_mode": "frame", "column_bindings": bindings,
               "options": {**options, "seasonal_period": 24, "holdout_periods": 0}}
    assert operation.validate(request)["options"]["seasonal_period"] == 24
    with pytest.raises(ValueError, match="seasonal_period"):
        operation.validate({**request, "options": {**request["options"], "seasonal_period": 25}})


@pytest.mark.parametrize("operation_id", ["time_series.native_sarima", "time_series.native_sarimax"])
def test_hourly_preview_refuses_a_specification_with_insufficient_search_budget(tmp_path, operation_id):
    from workbench.app import app

    rng = np.random.default_rng(25)
    frame = pd.DataFrame({"t": range(100), "y": rng.normal(size=100), "x": rng.normal(size=100)})
    root, run_id, source_id = _source_project(tmp_path, frame)
    bindings, _ = CASES[operation_id]
    response = TestClient(app).post("/operations/run", params={"project_root": str(root)}, json={
        "mode": "preview", "request_id": "hourly-budget",
        "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": source_id},
        "steps": [{"step_id": "native", "operation_id": operation_id, "spec": {
            "input_mode": "frame", "column_bindings": bindings,
            "options": {"seasonal_period": 24, "ar_order": 2, "seasonal_ar_order": 1,
                        "seasonal_differences": 0, "forecast_periods": 4},
        }}],
    })
    assert response.status_code == 422, response.text
    assert "budget" in response.json()["error"]["message"]
    assert not (root / "workbench" / "proposals").exists()


@pytest.mark.parametrize("operation_id, rows, override, message", [
    ("time_series.local_level", 4, {"holdout_periods": 4}, "holdout_periods"),
    ("time_series.local_level_fit", 4, {"holdout_periods": 3}, "at least two training"),
    ("time_series.correlogram", 3, {}, "max_lag"),
    ("time_series.native_arima", 4, {"holdout_periods": 0, "differences": 0, "deterministic": "drift"}, "drift"),
    ("time_series.native_arima", 4, {"holdout_periods": 3}, "training"),
    ("time_series.native_arima", 4, {"ar_order": 5, "ma_order": 2}, "combined"),
    ("time_series.native_sarima", 4, {"holdout_periods": 0}, "training"),
    ("time_series.holt_winters_additive", 4, {}, "season"),
    ("time_series.holt_winters_fit_alpha", 4, {}, "training"),
    ("time_series.native_volatility", 4, {"holdout_periods": 0}, "training"),
    ("prediction.native_ridge", 4, {"holdout_fraction": 0.75}, "two training rows"),
    ("prediction.native_elastic_net", 4, {"holdout_fraction": 0.75}, "two training rows"),
    ("quant.replay", 0, {}, "Replay requires a table with 1 to"),
    ("quant.replay_tail_risk", 4, {"end_period": 3}, "window"),
    ("quant.rolling_risk", 4, {"window": 5}, "window must be an integer from 2 to 4"),
])
def test_manual_preview_checks_rows_on_the_selected_frame(tmp_path, operation_id, rows, override, message):
    from workbench.app import app

    frame = pd.DataFrame({"t": range(4), "y": [2., 3., 4., 5.], "x": [1., 4., 2., 5.],
                          "signal": range(-1, 3), "start": range(4), "end": range(1, 5),
                          "ret": [.01] * 4, "weight": [.5] * 4}).iloc[:rows]
    root, run_id, source_id = _source_project(tmp_path, frame)
    bindings, options = CASES[operation_id]
    response = TestClient(app).post("/operations/run", params={"project_root": str(root)}, json={
        "mode": "preview", "request_id": "native-size-check",
        "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": source_id},
        "steps": [{"step_id": "native", "operation_id": operation_id, "spec": {
            "input_mode": "frame", "column_bindings": bindings, "options": {**options, **override},
        }}],
    })
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "OPERATION_INVALID"
    assert operation_id in error["message"] and message in error["message"]
    assert not (root / "workbench" / "proposals").exists()


def test_manual_preview_defers_row_bounds_for_an_unmaterialized_dataset(tmp_path, monkeypatch):
    from workbench.app import app

    def no_compute(*args, **kwargs):
        pytest.fail("Preview must not compute a native result")

    monkeypatch.setattr("workbench.agent.workflow_capability_adapters.compute_native_research", no_compute)
    root, run_id, source_id = _source_project(tmp_path, pd.DataFrame({"t": [1, 2], "a": [.01, .02], "b": [.03, .04]}))
    steps = [
        {"step_id": "reshape", "operation_id": "data.reshape", "spec": {
            "direction": "wide_to_long", "id_columns": ["t"], "value_columns": ["a", "b"],
            "var_name": "asset", "value_name": "ret",
        }},
        {"step_id": "index", "operation_id": "data.row_index", "depends_on": ["reshape"], "spec": {"output": "period"}},
        {"step_id": "risk", "operation_id": "quant.rolling_risk", "depends_on": ["index"], "spec": {
            "input_mode": "frame", "column_bindings": {"time_col": "period", "return_columns": ["ret"]},
            "options": {"window": 3},
        }},
    ]
    response = TestClient(app).post("/operations/run", params={"project_root": str(root)}, json={
        "mode": "preview", "request_id": "native-produced-size",
        "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": source_id},
        "steps": steps,
    })
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "awaiting_confirmation"
    assert any("after it is produced" in note for note in preview["risks"])
    assert not (root / "workbench" / "workflows").exists()


def test_native_moving_average_order_reaches_the_same_runtime():
    module = Path(__file__).resolve().parents[1] / "native" / "time_series"
    if not manifest_path(default_output(module)).is_file():
        pytest.skip("Explicit time-series build required")
    rng = np.random.default_rng(20261105)
    noise = rng.normal(size=321)
    frame = pd.DataFrame({"t": range(320), "y": noise[1:] + 0.65 * noise[:-1]})
    operation_id = "time_series.native_arima"
    _, execution = workflow_capability_registry().require(operation_id).execute_with_context(frame, {
        "operation_id": operation_id, "input_mode": "frame", "column_bindings": {"time_col": "t", "outcome": "y"},
        "options": {"ar_order": 0, "ma_order": 1, "forecast_periods": 3},
    })
    assert execution.payload["policy"]["order"] == [0, 0, 1]
    assert execution.payload["parameters"]["ma1"] == pytest.approx(0.65, abs=0.12)
    forecast = execution.local_detail["forecast"]
    assert forecast["mean"][1:] == [0, 0]
    assert forecast["observation_variance"][1] > forecast["observation_variance"][0]


def test_native_agent_result_prioritizes_holdout_and_build_over_wide_coefficients():
    from workbench.agent.context_tools_support.summaries_public import _public_operation_artifact_result

    result = {
        "operation_id": "prediction.native_ridge",
        "coefficients": {f"x{i}-" + "d" * 90: i / 20 for i in range(32)},
        "metrics": {"rmse": 0.2, "mae": 0.1, "r2": 0.9},
        "mean_baseline": {"rmse": 0.7}, "split": {"train_rows": 80, "test_rows": 20},
        "native_build": {"build_identity_sha256": "a" * 64},
    }
    projected, omitted = _public_operation_artifact_result(
        "workflow_capability_result", {"result": result, "local_detail": {"secret": [12345]}},
    )
    for field in ("operation_id", "metrics", "mean_baseline", "split", "native_build"):
        assert projected[field] == result[field]
    assert 0 < len(projected["coefficients"]) < len(result["coefficients"])
    assert "local_detail" in omitted and "secret" not in json.dumps(projected)


def test_manual_confirmation_publishes_an_exact_download_and_agent_readable_lineage(
    tmp_path, monkeypatch, native_case,
):
    from workbench.agent.context_tools import InspectArtifactPreviewRequest, NodeOperationContextProvider
    from workbench.app import app
    from workbench.graph_store import GraphStore

    def forbidden(*args, **kwargs):
        pytest.fail("Manual native research must not construct a model provider")

    monkeypatch.setattr("workbench.agent.model.OpenAICompatibleModelAdapter.__init__", forbidden)
    operation_id, frame, spec = native_case
    root, run_id, source_id = _source_project(tmp_path, frame)
    run = root / "runs" / run_id
    source_sha = sha256_file(run / "data.csv")
    client = TestClient(app, base_url="http://127.0.0.1")
    params = {"project_root": str(root)}
    body = {
        "mode": "preview", "request_id": "native-product-path",
        "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": source_id},
        "steps": [{"step_id": "analyze", "operation_id": operation_id,
                   "spec": spec}],
    }
    response = client.post("/operations/run", params=params, json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "awaiting_confirmation"
    confirm = {"mode": "confirm", **{key: preview[key] for key in ("request_id", "preview_id", "fingerprint")}}
    response = client.post("/operations/run", params=params, json=confirm)
    assert response.status_code == 200, response.text
    outcome = response.json()
    assert outcome["status"] == "completed", outcome
    step = outcome["steps"][0]
    artifact_id = step["artifact_refs"][0]["artifact_id"]
    node_id = step["node_refs"][0]["node_id"]
    graph = GraphStore(root / "runs").read(run_id)
    assert graph.nodes[node_id].parent_stage_id == "stage:source"
    assert any(edge.source_id == "stage:source" and edge.target_id == node_id for edge in graph.edges.values())
    downloaded = client.get(f"/runs/{run_id}/artifacts/{artifact_id}", params=params)
    assert downloaded.status_code == 200, downloaded.text
    saved = downloaded.json()
    assert saved["source"]["sha256"] == source_sha
    assert saved["source"]["operation_id"] == operation_id
    assert saved["request"]["column_bindings"] == spec["column_bindings"]
    assert sha256_file(run / "data.csv") == source_sha
    if operation_id == "time_series.stationarity_statistic":
        assert saved.get("local_detail") is None
        result = saved["result"]
        assert result["n_effective"] == 37
        assert result["adf_regression"]["residual_df"] == 33
        assert result["null_hypothesis"] == "unit_root"
        assert result["evidence_scope"] == "statistic_only" and "p_value" not in result
    else:
        assert saved["local_detail"]
    if operation_id == "time_series.correlogram":
        correlogram = saved["local_detail"]["correlogram"]
        assert correlogram["lags"] == [0, 1, 2, 3, 4]
        assert correlogram["acf"][0] == 1 and correlogram["pacf"][0] is None
        assert saved["result"]["metrics"]["lag_one_acf"] == correlogram["acf"][1]
        assert saved["result"]["metrics"]["at_max_lag"] == {
            "lag": correlogram["lags"][-1], "acf": correlogram["acf"][-1], "pacf": correlogram["pacf"][-1],
        }
    if operation_id == "time_series.native_arima":
        assert saved["result"]["policy"]["order"] == [0, 1, 0]
        assert saved["result"]["fit"]["n_effective"] == 11
        assert saved["local_detail"]["forecast"]["mean"] == [7.5] * 4
        assert saved["local_detail"]["holdout_forecast"]["mean"] == [6.0] * 3
        assert saved["local_detail"]["forecast"]["upper"][-1] > saved["local_detail"]["forecast"]["upper"][0]
    if operation_id in {"time_series.native_sarima", "time_series.native_sarimax"} and spec["options"]["seasonal_period"] == 24:
        result = saved["result"]
        assert result["policy"]["seasonal_order"] == [0, 1, 0, 24]
        assert result["forecast"]["steps"] == 30
        assert result["holdout"]["training_steps"] == 98
        expected = -68.685303501556945 if operation_id == "time_series.native_sarima" else -75.106336087327222
        assert result["fit"]["log_likelihood"] == pytest.approx(expected, abs=3e-11)
    if operation_id == "time_series.native_sarima" and spec["options"]["seasonal_period"] != 24:
        assert saved["result"]["policy"]["seasonal_order"] == [0, 1, 0, 4]
        assert saved["local_detail"]["forecast"]["mean"][:4] == pytest.approx([20, 32, 39, 14])
        holdout = saved["result"]["holdout"]
        assert holdout["training_steps"] == 10
        assert holdout["metrics"]["naive_mae"] == 1
        assert holdout["metrics"]["mae"] == pytest.approx(1)
    if operation_id == "time_series.arima_residual_check":
        check = saved["result"]["fit"]["diagnostics"]["whiteness"]
        assert check["status"] == "computed" and check["n_effective"] == 90
        assert check["fit_df"] == 2 and check["df"] == 4
        assert check["statistic"] == pytest.approx(2.04190896498115, abs=1e-10)
        assert check["p_value"] == pytest.approx(0.728050717298245, abs=1e-10)
    if operation_id in {"time_series.native_arimax", "time_series.native_sarimax"} and spec["options"].get("seasonal_period") != 24:
        assert saved["result"]["policy"]["future_regressors"] == "supplied_in_aligned_suffix"
        assert saved["result"]["fit"]["n_observed"] == 100
        assert saved["local_detail"]["forecast"]["time"] == [100, 101, 102, 103]
        assert saved["result"]["parameters"]["exogenous"]["x"] == pytest.approx(2.5, abs=0.09)
    if operation_id == "time_series.native_var":
        assert saved["result"]["fit"]["n_effective"] == 98
        assert saved["result"]["diagnostics"]["granger"]["df_num"] == 2
        assert set(saved["local_detail"]["series_forecasts"]) == {"a", "b"}
        assert len(saved["local_detail"]["forecast_covariance"]) == 5
    if operation_id == "time_series.native_vecm":
        assert saved["result"]["fit"]["rank"] == 1
        assert saved["result"]["policy"]["rank_policy"] == "fixed_rank_one"
        assert set(saved["local_detail"]["series_forecasts"]) == {"a", "b"}
        assert len(saved["local_detail"]["forecast_covariance"]) == 5
    if operation_id == "time_series.varma11_fixed_ma":
        assert saved["result"]["policy"]["ma_coefficient"] == 0.4
        assert saved["local_detail"]["moving_average_matrix"]["matrix"] == [[0.4, 0.0], [0.0, 0.4]]
        assert len(saved["local_detail"]["forecast_covariance"]) == 5
    if operation_id == "time_series.native_arfima":
        assert saved["result"]["parameters"]["order"] == [0, 0.25, 0]
        assert saved["result"]["policy"]["difference_mode"] == "fixed"
        assert saved["result"]["holdout"]["training_steps"] == 9
    if operation_id == "time_series.markov_switching":
        forecast = saved["result"]["forecast"]["first"]
        assert forecast["probability_low"] + forecast["probability_high"] == pytest.approx(1)
        assert saved["result"]["fit"]["mean_low"] < saved["result"]["fit"]["mean_high"]
        assert "trace" not in saved["result"]["fit"]
        assert len(saved["local_detail"]["trace"]["filtered_low"]) == 360
    if operation_id == "time_series.holt_winters_fit_alpha":
        assert saved["result"]["estimation"]["training_steps"] == 9
        assert saved["local_detail"]["holdout_forecast"]["time"] == [9, 10, 11]
        assert len(saved["local_detail"]["alpha_grid_sse"]) == 20
        assert saved["result"]["parameters"]["alpha"] == (np.argmin(saved["local_detail"]["alpha_grid_sse"]) + 1) / 20
    if operation_id == "time_series.holt_winters_fit_joint":
        result = saved["result"]
        assert result["policy"]["confidence_level"] == 0.99
        assert set(result["parameters"]) == {"alpha", "beta", "gamma"}
        assert result["estimation"]["training_steps"] == 160
        assert result["holdout"]["training_steps"] == 152
        assert result["holdout"]["training_parameters"] != result["parameters"]
        assert "trace" not in result["fit"] and "trace" not in result["holdout"]["training_fit"]
        assert saved["local_detail"]["holdout_forecast"]["time"] == list(range(153, 161))
    if operation_id == "time_series.johansen_rank":
        result = saved["result"]
        assert result["ranks"] == [0, 1, 2]
        assert result["n_effective"] == 78
        assert result["rank_criterion"] == "uncalibrated"
        assert "p_value" not in result and "selected_rank" not in result
        assert result["trace_statistics"][0] == pytest.approx(sum(result["max_eigenvalue_statistics"]))
        assert saved["local_detail"]["sample"] == {"start_time": "2", "end_time": "79"}
    if operation_id == "time_series.ets_trend":
        assert saved["result"]["model_name"] == "ETS(A,Ad,N)"
        assert saved["result"]["policy"]["smoothing_parameters"] == "fixed_innovations_coefficients"
        assert saved["result"]["holdout"]["training_steps"] == 9
        assert saved["local_detail"]["forecast"]["time"] == [12, 13, 14, 15]
        assert all(value > 0 for value in saved["local_detail"]["forecast"]["observation_variance"])
    if operation_id == "time_series.ets_trend_estimate":
        fit = saved["result"]["fit"]
        assert fit["estimated_parameter_count"] == 5
        assert fit["optimizer_diagnostics"]["agreeing_searches"] > 0
        assert saved["result"]["policy"]["smoothing_modes"] == {"alpha": "estimate", "beta": "estimate", "phi": "fixed"}
        assert saved["result"]["holdout"]["training_steps"] == 168
        assert saved["result"]["holdout"]["training_parameters"] != saved["result"]["parameters"]
    if operation_id == "time_series.native_volatility":
        assert saved["result"]["policy"]["family"] == "gjr_garch_1_1_1"
        assert saved["result"]["fit"]["n_observed"] == 780
        assert all(variance > 0 for variance in saved["local_detail"]["variance_forecast"]["variance"])
        assert "mean" not in saved["result"]["forecast"]["first"]
    if operation_id == "time_series.native_egarch":
        last = saved["result"]["forecast"]["last"]
        assert saved["result"]["forecast"]["steps"] == 1
        assert last["variance"] == pytest.approx(np.exp(last["log_variance"]))
    if operation_id == "time_series.native_igarch":
        assert saved["result"]["fit"]["long_run_variance"] is None
        assert saved["result"]["policy"]["persistence"] == 1
        forecast = saved["local_detail"]["variance_forecast"]["variance"]
        assert np.diff(forecast) == pytest.approx([saved["result"]["parameters"]["omega"]] * 3)
    if operation_id == "time_series.figarch_fixed":
        assert saved["result"]["policy"]["estimation"] == "fixed_parameters"
        fit = saved["result"]["fit"]
        assert fit["n_observed"] == 9 and fit["long_run_variance"] is None
        assert fit["retained_weight_mass"] + fit["omitted_weight_mass"] == 1
        assert "lag_weights" not in saved["result"]
        assert len(saved["local_detail"]["lag_weights"]["values"]) == 64
        assert len(saved["local_detail"]["holdout_variance"]["variance"]) == 3
    if operation_id == "prediction.native_logistic":
        assert saved["result"]["split"]["test_rows"] == 3
        assert 0 < saved["result"]["prevalence_baseline"]["probability"] < 1
        assert 0 <= saved["result"]["metrics"]["roc_auc"] <= 1
        assert "rmse" not in saved["result"]["metrics"]
    if operation_id == "prediction.native_cart":
        assert saved["result"]["model_structure"]["node_count"] == len(saved["local_detail"]["prediction_basis"]["nodes"])
        assert saved["result"]["split"]["test_rows"] == 3
        assert "coefficients" not in saved["result"]
    if operation_id == "prediction.native_cart_regression":
        result = saved["result"]
        tree = saved["local_detail"]["prediction_basis"]
        assert tree["kind"] == "regression"
        assert result["model_structure"]["node_count"] == len(tree["nodes"])
        assert result["split"]["test_rows"] == 3
        assert result["metrics"]["mse"] == pytest.approx(result["metrics"]["rmse"] ** 2)
        assert result["mean_baseline"]["prediction"] == pytest.approx(frame["y"].iloc[:9].mean())
        assert "coefficients" not in result
    if operation_id == "prediction.native_random_forest_regression":
        result = saved["result"]
        basis = saved["local_detail"]["prediction_basis"]
        assert basis["kind"] == "random_forest_regression"
        assert len(basis["trees"]) == result["model_structure"]["tree_count"] == 5
        assert result["split"]["train_rows"] == 8 and result["split"]["test_rows"] == 2
        assert result["options"]["seed"] == 731 and result["options"]["max_features"] == 1
        assert result["metrics"]["mse"] == pytest.approx(0.3044444444444439, abs=1e-14)
        assert result["mean_baseline"]["mse"] == pytest.approx(4.25, abs=1e-14)
        assert "trees" not in result
    if operation_id == "prediction.native_random_forest_classification":
        result = saved["result"]
        basis = saved["local_detail"]["prediction_basis"]
        assert basis["kind"] == "random_forest_classification"
        assert len(basis["trees"]) == result["model_structure"]["tree_count"] == 9
        assert result["split"]["train_rows"] == 8 and result["split"]["test_rows"] == 4
        assert result["metrics"]["log_loss"] == pytest.approx(0.5305614831166794, abs=1e-14)
        assert result["prevalence_baseline"]["log_loss"] == pytest.approx(0.6931471805599453, abs=1e-14)
        assert "trees" not in result
    if operation_id == "prediction.native_ridge_selection":
        result = saved["result"]
        selection = result["selection"]
        assert (selection["fit_rows"], selection["validation_rows"], result["split"]["test_rows"]) == (6, 2, 2)
        assert selection["selected_alpha"] == result["alpha"] == 6
        assert result["metrics"]["rmse"] == pytest.approx(0.5)
        assert result["mean_baseline"]["rmse"] == pytest.approx(1.5)
        assert "selection_times" not in result
    if operation_id == "quant.replay_fee_comparison":
        result = saved["result"]
        metrics = result["metrics"]
        assert metrics["base"]["total_fees"] == 0 < metrics["higher"]["total_fees"]
        assert metrics["higher_minus_base"]["final_equity"] == pytest.approx(
            metrics["higher"]["final_equity"] - metrics["base"]["final_equity"],
        )
        assert metrics["higher"]["final_equity"] < metrics["base"]["final_equity"]
        paths = saved["local_detail"]["fee_comparison"]
        assert [row["end_time"] for row in paths["base"]["rows"]] == [
            row["end_time"] for row in paths["higher"]["rows"]
        ]
        assert "series" not in result
    if operation_id == "quant.replay_tail_risk":
        assert saved["local_detail"]["tail_window"]["as_of_end_time"] == "9"
        assert saved["result"]["inputs"]["end_period"] == 9
        assert saved["result"]["metrics"]["expected_shortfall"] >= saved["result"]["metrics"]["value_at_risk"]
        assert saved["result"]["policy"]["annualized"] is False
    if operation_id == "quant.min_variance":
        assert sum(saved["result"]["allocation"].values()) == pytest.approx(1)
        assert saved["local_detail"]["cutoff"]["last_period"] == 9
        assert saved["result"]["metrics"]["normalized_kkt_residual"] <= 1e-9
    if operation_id == "quant.min_variance_walk_forward":
        local = saved["local_detail"]
        decisions = local["decisions"]["rows"]
        assert [row["period"] for row in decisions] == [6, 7, 8, 9, 10]
        assert decisions[0]["last_training_period"] == 4
        assert [row["end_time"] for row in local["strategy_series"]["rows"]] == [
            row["end_time"] for row in local["benchmark_series"]["rows"]
        ]
        assert "strategy_series" not in saved["result"] and "decisions" not in saved["result"]
        metrics = saved["result"]["metrics"]
        assert metrics["cumulative_net_return_difference"] == (
            metrics["strategy"]["cumulative_net_return"] - metrics["benchmark"]["cumulative_net_return"]
        )
    assert "rows" not in json.dumps(saved["result"].get("series", {}))
    assert "train_last_time" not in saved["result"].get("split", {})
    assert "origin_time" not in (saved["result"].get("holdout") or {})
    with monkeypatch.context() as local_policy:
        from workbench.api_errors import WorkbenchAPIError

        def deny_export(*args):
            raise WorkbenchAPIError(403, "EXPORT_DENIED", "Exports are disabled")

        local_policy.setattr("workbench.http.runs_routes.authorize_export", deny_export)
        assert client.get(f"/runs/{run_id}/artifacts/{artifact_id}", params=params).status_code == 403
        inline = client.get(f"/runs/{run_id}/artifacts/{artifact_id}", params={**params, "view": "local"})
        assert inline.content == downloaded.content and "content-disposition" not in inline.headers
    assert client.post("/operations/run", params=params, json=confirm).json() == outcome

    evidence = NodeOperationContextProvider(root).inspect_artifact_preview(
        InspectArtifactPreviewRequest(request_id="native-result", owner_run_id=run_id,
                                      op_node_id=node_id, active_head_run_id=run_id)
    )["artifact_preview"]["public_result_evidence"]
    assert [item["artifact_id"] for item in evidence] == [artifact_id]
    assert evidence[0]["result"]["operation_id"] == operation_id
    assert "local_detail" not in json.dumps(evidence)
    if operation_id in {"time_series.johansen_rank", "time_series.holt_winters_fit_joint",
                        "prediction.native_random_forest_classification", "prediction.native_ridge_selection"}:
        from workbench.agent.research_review import _computed_summary

        review, complete = _computed_summary(saved)
        assert complete, review
        assert "local_detail" not in json.dumps(review)

    artifact_path = run / graph.nodes[node_id].payload_ref
    index_path = run / "artifacts_index.json"
    original_index = index_path.read_bytes()
    index = json.loads(original_index)
    entries = index["artifacts"]
    entry = next(item for item in entries if item["artifact_id"] == artifact_id)
    entries.append(dict(entry))
    index_path.write_text(json.dumps(index), encoding="utf-8")
    assert client.get(f"/runs/{run_id}/artifacts/{artifact_id}", params={**params, "view": "local"}).status_code == 409
    entries.pop()
    index_path.write_bytes(original_index)
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
    changed = client.get(f"/runs/{run_id}/artifacts/{artifact_id}", params=params)
    assert changed.status_code == 409
    entry["sha256"] = sha256_file(artifact_path)
    index_path.write_text(json.dumps(index), encoding="utf-8")
    assert client.get(f"/runs/{run_id}/artifacts/{artifact_id}", params=params).status_code == 409
    evidence = NodeOperationContextProvider(root).inspect_artifact_preview(
        InspectArtifactPreviewRequest(request_id="changed-native-result", owner_run_id=run_id,
                                      op_node_id=node_id, active_head_run_id=run_id)
    )["artifact_preview"]["public_result_evidence"]
    assert evidence == []
    from workbench.agent.context_compiler import resolve_registered_artifact

    assert resolve_registered_artifact(run, artifact_id) is None


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_offline_agent_executes_the_same_native_operation_and_only_receives_aggregate(
    native_case, mode, tmp_path, monkeypatch,
):
    from tests.test_agent_routes import _config
    from workbench.agent.context_tools import InspectNodeContextRequest, NodeOperationContextProvider
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.operations import OperationRecordStore
    from workbench.agent.runtime_adapter import headless_runtime_scope
    from workbench.app import app
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    operation_id, frame, spec = native_case
    csv = tmp_path / "data.csv"
    frame.to_csv(csv, index=False)
    root = create_project(tmp_path, "offline-native").root
    run = run_workflow(root, [csv], mode="import", y="", x=[])
    run_id = run["run_id"]
    node_id = "stage:cleaned"
    source_id = "cleaned_dataset"
    context = NodeOperationContextProvider(root).inspect_node_context(
        InspectNodeContextRequest(request_id="native-source", owner_run_id=run_id,
                                  op_node_id=node_id, active_head_run_id=run_id)
    )
    requests = []
    question = "Run the specified method on this imported table."

    class ScriptedModel:
        async def stream(self, request):
            requests.append(request)
            if mode == "auto" and len(requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "draft-native", "tool_id": "update_plan",
                    "arguments": {
                        "question": question, "criteria": ["Save the requested computed result."],
                        "steps": [{"step_id": "native", "title": "Compute the selected method",
                                   "operation_ids": [operation_id]}],
                    },
                })
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            elif len(requests) == (2 if mode == "auto" else 1):
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "native-analysis", "tool_id": "run_operation",
                    "arguments": {
                        "operation_id": "operation.multi_step", "operation_version": "v1",
                        "target": {"run_id": run_id, "node_ref": node_id, "artifact_id": source_id},
                        "preconditions": {key: context[key] for key in (
                            "context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")},
                        "changes": {"steps": [{"step_id": "native", "operation_id": operation_id, "spec": spec}]},
                        "evidence_refs": ["verified source"], "expected_effect": ["Calculate and save the selected result."],
                        "risks": [],
                    },
                })
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "The saved result is available for review.")
                yield ModelStreamEvent.done(request.request_id)

    def forbidden(*args, **kwargs):
        pytest.fail("An offline Agent replay attempted to open a connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    with headless_runtime_scope(adapter_factory=lambda config: ScriptedModel(), config=_config()):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            params = {"project_root": str(root)}
            response = client.post("/agent/sessions", params=params, json={
                "role": "chain", "chain_id": f"run:{run_id}", "run_id": run_id, "context_packet": {},
                "focus": {"kind": "node", "id": node_id, "run_id": run_id, "label": "Imported data"},
            })
            assert response.status_code == 200, response.text
            session = response.json()["session_id"]
            path = f"/agent/sessions/{session}"
            response = client.post(path + "/turns", params=params, json={
                "question": question, "execution_policy": "proposal_only", "execution_mode": mode,
            })
            assert response.status_code == 200, response.text
            if mode == "auto":
                plan = client.get(path + "/plan", params=params).json()["plan"]
                assert plan["status"] == "draft"
                approved = client.post(path + "/plan/approve", params=params, json={"version": plan["version"]})
                assert approved.status_code == 200, approved.text
            else:
                listed = client.get(path + "/proposals", params=params).json()["proposals"]
                [proposal] = [item for item in listed if item["status"] == "pending"]
                confirmed = client.post(path + f"/proposals/{proposal['proposal_id']}/confirm", params=params, json={
                    "revision": proposal["revision"], "fingerprint": proposal["fingerprint"], "active_head_run_id": run_id,
                })
                assert confirmed.status_code == 200, confirmed.text
                assert confirmed.json()["operation"]["status"] == "completed", confirmed.json()
            continued = client.post(path + "/continue", params=params, json={"execution_mode": mode})
            assert continued.status_code == 200, continued.text

    [record] = [item for item in OperationRecordStore(root / "workbench", create=False).list_records()
                if item.operation_id == "operation.multi_step"]
    assert record.status == "completed" and record.actor_type == ("user" if mode == "ask" else "approved_plan")
    [result] = record.outputs["post_estimation_results"]
    assert result["result"]["operation_id"] == operation_id
    assert result["result"]["n_rows"] == len(frame)
    if operation_id == "time_series.correlogram":
        assert result["result"]["metrics"]["at_max_lag"]["lag"] == spec["options"]["max_lag"]
    if operation_id == "time_series.johansen_rank":
        assert result["result"]["rank_criterion"] == "uncalibrated"
        assert len(result["result"]["max_eigenvalue_statistics"]) == 3
        assert "sample" not in result["result"]
    if operation_id == "time_series.holt_winters_fit_joint":
        assert set(result["result"]["parameters"]) == {"alpha", "beta", "gamma"}
        assert "trace" not in result["result"]["fit"]
    if operation_id == "prediction.native_random_forest_classification":
        assert result["result"]["metrics"]["log_loss"] == pytest.approx(0.5305614831166794)
    if operation_id == "prediction.native_ridge_selection":
        assert result["result"]["selection"]["selected_alpha"] == 6
    if operation_id == "quant.replay_fee_comparison":
        assert result["result"]["metrics"]["higher_minus_base"]["cumulative_net_return"] < 0
        assert "series" not in result["result"]
    assert "local_detail" not in json.dumps(record.outputs)
    assert "prediction_basis" not in json.dumps(record.outputs)
    assert all("local_detail" not in json.dumps(request.messages) for request in requests)


def test_quant_replay_saves_every_period_without_changing_primary_or_default_source(tmp_path, monkeypatch):
    import math

    from tests.test_native_quant_replay import _frame, OPTIONS
    from workbench import native_quant_replay as replay
    from workbench.agent.context_tools_support.summaries_public import _public_operation_artifact_result
    from workbench.app import app
    from workbench.artifacts import read_json
    from workbench.graph_store import GraphStore
    from workbench.native_research import compute_native_research

    if not manifest_path(default_output(Path("native/quant_replay"))).exists():
        pytest.skip("Explicit quant build required")
    frame = _frame(replay.MAX_SERIES_POINTS + 13)
    bindings = {name: OPTIONS[name] for name in CASES["quant.replay"][0]}
    options = {name: OPTIONS[name] for name in ("transaction_cost_bps", "initial_equity")}
    spec = {"input_mode": "frame", "column_bindings": bindings, "options": options}
    expected, local = compute_native_research(frame, {"operation_id": "quant.replay", **spec})
    assert local["series"]["truncated"] and len(local["series"]["rows"]) == 256
    assert not workflow_capability_registry().require("quant.replay").produces_dataset
    native_outputs = []
    actual_call = replay._native_call

    def capture(*args):
        output = actual_call(*args)
        native_outputs.append(output.copy())
        return output

    monkeypatch.setattr(replay, "_native_call", capture)
    root, run_id, source_id = _source_project(tmp_path, frame)
    params = {"project_root": str(root)}
    client = TestClient(app, base_url="http://127.0.0.1")
    body = {"mode": "preview", "request_id": "full-replay-ledger",
            "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": source_id},
            "steps": [{"step_id": "replay", "operation_id": "quant.replay", "spec": spec},
                      {"step_id": "summary", "operation_id": "statistical.explore", "depends_on": ["replay"],
                       "spec": {"operation": "summarize", "selected_columns": ["return_a"]}}]}
    response = client.post("/operations/run", params=params, json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert "source" not in preview["steps"][1]["spec"]
    confirm = {"mode": "confirm", **{key: preview[key] for key in ("request_id", "preview_id", "fingerprint")}}
    response = client.post("/operations/run", params=params, json=confirm)
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    outcome = response.json()
    refs = outcome["steps"][0]["artifact_refs"]
    assert len(refs) == 2, "the complete Rust ledger must be saved beside the sampled JSON"
    primary_id, ledger_id = [item["artifact_id"] for item in refs]
    assert primary_id.startswith("workflow_capability_quant_replay_")
    assert ledger_id.startswith("quant_replay_ledger_")
    index = read_json(root / "runs" / run_id / "artifacts_index.json")["artifacts"]
    records = {item["artifact_id"]: item for item in index}
    primary = read_json(root / "runs" / run_id / records[primary_id]["path"])
    assert primary["result"] == expected and primary["local_detail"] == local
    assert records[ledger_id]["inputs"] == [source_id, primary_id]
    assert records[ledger_id]["artifact_type"] == "quant_replay_ledger"
    path = root / "runs" / run_id / records[ledger_id]["path"]
    ledger = pd.read_csv(path, float_precision="round_trip")
    assert len(ledger) == len(frame) and ledger["row"].tolist() == list(range(len(frame)))
    columns = ["starting_equity", "post_trade_equity", "ending_equity", "gross_exposure", "fees",
               "traded_notional", "holding_pnl", "net_pnl", "net_return"]
    assert ledger[columns].to_numpy().tobytes() == native_outputs[0].tobytes()
    assert math.fsum(ledger.fees) == expected["metrics"]["total_fees"]
    assert ledger.ending_equity.iloc[-1] == expected["metrics"]["final_equity"]
    assert ledger.drawdown.max() == expected["metrics"]["max_drawdown"]
    assert math.fsum(row["fees"] for row in local["series"]["rows"]) < math.fsum(ledger.fees)
    node = GraphStore(root / "runs").read(run_id).nodes["native-result:" + primary_id]
    [annotation] = [item for item in node.annotations if item.get("type") == "quant_replay_ledger"]
    assert annotation["artifact_id"] == ledger_id and annotation["sha256"] == sha256_file(path)
    assert annotation["row_count"] == len(frame)
    assert "produced_dataset" not in json.dumps(outcome)
    download = client.get(f"/runs/{run_id}/artifacts/{ledger_id}", params=params)
    assert download.status_code == 200 and download.content == path.read_bytes()
    assert "attachment" in download.headers["content-disposition"]
    assert _public_operation_artifact_result("quant_replay_ledger", {"rows": ledger.to_dict("records")})[0] is None
    assert "starting_equity" not in json.dumps(outcome)
    assert client.post("/operations/run", params=params, json=confirm).json() == outcome
    assert len(native_outputs) == 1, "the companion table must reuse the one approved native execution"

    # Neither registry metadata nor graph annotations may redirect the table's
    # source or the original result on a recovery attempt.
    from dataclasses import replace
    from workbench.agent.workflow import WorkflowExecutionError
    from workbench.agent.workflow_runtime_parts.postestimation import (
        _persist_quant_replay_ledger, _publish_native_result_node,
    )
    from workbench.artifacts import write_json

    run_root = root / "runs" / run_id
    index_path = run_root / "artifacts_index.json"
    original_index = read_json(index_path)
    primary_path = run_root / records[primary_id]["path"]
    protected_paths = [run_root / records[source_id]["path"], primary_path, path]
    original_bytes = [file.read_bytes() for file in protected_paths]
    for identity, field, value in [
        (ledger_id, "inputs", [primary_id]), (ledger_id, "path", "tables/another.csv"),
        (ledger_id, "sha256", "0" * 64), (primary_id, "inputs", ["another_source"]),
        (primary_id, "sha256", "0" * 64),
    ]:
        changed = deepcopy(original_index)
        next(item for item in changed["artifacts"] if item["artifact_id"] == identity)[field] = value
        write_json(index_path, changed)
        with pytest.raises(WorkflowExecutionError, match="binding changed"):
            _persist_quant_replay_ledger(run_root, primary_id, ledger, primary["source"], len(frame))
        assert [file.read_bytes() for file in protected_paths] == original_bytes
    write_json(index_path, original_index)

    store = GraphStore(root / "runs")
    original_graph = store.read(run_id)
    for change in ("source", "primary_hash", "ledger_ref"):
        bad = (replace(node, parent_stage_id="stage:other") if change == "source" else
               replace(node, node_hash="0" * 64) if change == "primary_hash" else
               replace(node, annotations=({**annotation, "artifact_id": "another_ledger"},)))
        store.write(replace(original_graph, nodes={**original_graph.nodes, node.id: bad}))
        with pytest.raises(WorkflowExecutionError, match="identity changed|binding changed"):
            _publish_native_result_node(run_root, primary["source"], primary_id, primary_path,
                "Portfolio replay", "quant.replay", "unchanged", replay_ledger=annotation)
        assert store.read(run_id).nodes[node.id] == bad
        assert [file.read_bytes() for file in protected_paths] == original_bytes
    store.write(original_graph)


def test_quant_replay_bad_clock_does_not_publish_a_ledger(tmp_path):
    from tests.test_native_quant_replay import _frame, OPTIONS
    from workbench.app import app
    from workbench.artifacts import read_json

    if not manifest_path(default_output(Path("native/quant_replay"))).exists():
        pytest.skip("Explicit quant build required")
    frame = _frame()
    frame["signal"] = frame["execute"]
    root, run_id, source_id = _source_project(tmp_path, frame)
    client = TestClient(app, base_url="http://127.0.0.1")
    params = {"project_root": str(root)}
    response = client.post("/operations/run", params=params, json={
        "mode": "preview", "request_id": "bad-replay-clock",
        "target": {"kind": "dataset_node", "run_id": run_id, "node_id": "stage:source", "artifact_id": source_id},
        "steps": [{"step_id": "replay", "operation_id": "quant.replay", "spec": {
            "input_mode": "frame", "column_bindings": {name: OPTIONS[name] for name in CASES["quant.replay"][0]},
            "options": {name: OPTIONS[name] for name in ("transaction_cost_bps", "initial_equity")}}}],
    })
    assert response.status_code == 200, response.text
    preview = response.json()
    response = client.post("/operations/run", params=params, json={
        "mode": "confirm", **{key: preview[key] for key in ("request_id", "preview_id", "fingerprint")}})
    assert response.status_code == 200 and response.json()["status"] == "failed", response.text
    index = read_json(root / "runs" / run_id / "artifacts_index.json")
    assert all(item["artifact_type"] != "quant_replay_ledger" for item in index["artifacts"])
    assert not list((root / "runs" / run_id).glob("tables/quant_replay/*.csv"))
