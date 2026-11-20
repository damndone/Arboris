"""Native Ridge numerical, split, cancellation, and build admission evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.linalg import svd
from statsmodels.datasets import longley, macrodata

from workbench import native_ridge
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def loaded_ridge():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise the native Ridge runtime")
    return native_ridge._loaded()[0]


def _longley():
    source = Path(longley.__file__).with_name("longley.csv")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "0927ec7cc34edb5670920cb2ff1542e46de27a2010746e1662f4276cf3569a24"
    )
    return longley.load_pandas().data


def _oracle(x, y, alpha):
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1
    standardized = (x - center) / scale
    u, singular, vh = svd(standardized, full_matrices=False, lapack_driver="gesvd")
    beta = vh.T @ ((singular / (singular**2 + alpha)) * (u.T @ (y - y.mean()))) / scale
    return beta, float(y.mean() - center @ beta)


def _metrics(actual, predicted):
    residual = actual - predicted
    return {"rmse": float(np.sqrt(np.mean(residual**2))), "mae": float(np.mean(np.abs(residual))),
            "r2": float(1 - (residual @ residual) / np.sum((actual - actual.mean())**2))}


@pytest.mark.parametrize("alpha", [0.125, 1.0, 10000.0])
def test_longley_original_units_and_holdout_match_independent_svd(loaded_ridge, alpha):
    frame = _longley()
    predictors = [name for name in frame if name != "TOTEMP"]
    result = native_ridge.run_ridge(frame.iloc[::-1], outcome="TOTEMP", predictors=predictors,
                                    alpha=alpha, holdout_fraction=.25, time_col="YEAR")
    x = frame[predictors].to_numpy()
    y = frame["TOTEMP"].to_numpy()
    beta, offset = _oracle(x[:12], y[:12], alpha)
    np.testing.assert_allclose([result["coefficients"][key] for key in predictors], beta, rtol=2e-9, atol=1e-10)
    assert result["intercept"] == pytest.approx(offset, rel=2e-9, abs=1e-8)
    assert result["metrics"] == pytest.approx(_metrics(y[12:], x[12:] @ beta + offset), rel=2e-9, abs=1e-10)
    baseline = result["mean_baseline"]
    assert baseline["prediction"] == pytest.approx(y[:12].mean())
    assert {key: baseline[key] for key in result["metrics"]} == pytest.approx(_metrics(y[12:], y[:12].mean()))
    assert result["split"]["train_last_time"] == "1958.0"
    assert result["split"]["test_first_time"] == "1959.0"
    assert result["split"]["train_rows"] == 12 and result["split"]["test_rows"] == 4
    assert result["native_build"]["module"] == "ridge" and result["native_build"]["abi_version"] == 1
    for key in ("source_sha256", "binary_sha256", "build_identity_sha256"):
        assert len(result["native_build"][key]) == 64
    assert set(result["metrics"]) == {"rmse", "mae", "r2"}
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_real_macro_chronology_repeatability_and_training_only_scaling(loaded_ridge):
    source = macrodata.load_pandas().data
    quarters = pd.PeriodIndex.from_fields(year=source["year"], quarter=source["quarter"], freq="Q")
    frame = pd.DataFrame({"time": quarters.to_timestamp().strftime("%Y-%m-%d"),
                          "unemployment": source["unemp"],
                          "interest": source["tbilrate"], "inflation": source["infl"],
                          "growth": 100 * np.log(source["realgdp"]).diff().shift(-1)}).iloc[:-1]
    predictors = ["unemployment", "interest", "inflation"]
    args = dict(outcome="growth", predictors=predictors, alpha=1, holdout_fraction=.15, time_col="time")
    scrambled = frame.sample(frac=1, random_state=4)
    result = native_ridge.run_ridge(scrambled, **args)
    assert native_ridge.run_ridge(scrambled, **args) == result
    split = result["split"]["train_rows"]
    x, y = frame[predictors].to_numpy(), frame["growth"].to_numpy()
    beta, offset = _oracle(x[:split], y[:split], 1.0)
    assert result["metrics"] == pytest.approx(_metrics(y[split:], x[split:] @ beta + offset))

    altered = frame.copy()
    altered.iloc[split:, altered.columns.get_loc("unemployment")] += 100_000
    altered.iloc[split:, altered.columns.get_loc("growth")] *= -4
    changed = native_ridge.run_ridge(altered, **args)
    assert changed["coefficients"] == result["coefficients"]
    assert changed["intercept"] == result["intercept"]
    assert changed["mean_baseline"]["prediction"] == result["mean_baseline"]["prediction"]
    assert changed["metrics"] != result["metrics"]


def test_ties_stay_together_and_input_order_is_explicit(loaded_ridge):
    frame = pd.DataFrame({"date": [4, 1, 3, 2, 1, 4, 2, 3],
                          "x": [4., 7., 1., 2., 3., 3., 2., 8.],
                          "y": [3., 6., 1., 2., 3., 4., 5., 8.]})
    args = dict(outcome="y", predictors=["x"], alpha=1, holdout_fraction=.3)
    ordered = native_ridge.run_ridge(frame, time_col="date", **args)
    assert ordered["split"] == {
        "method": "chronological_holdout", "order": "time_column", "time_col": "date",
        "train_rows": 4, "test_rows": 4, "holdout_fraction_requested": .3,
        "holdout_fraction_actual": .5, "train_last_time": "2", "test_first_time": "3",
    }
    existing = native_ridge.run_ridge(frame, **args)
    assert existing["split"]["order"] == "input_order"
    assert existing["split"]["train_rows"] == 5
    assert existing["split"]["test_rows"] == 3
    assert existing["split"]["train_last_time"] is None
    assert existing["split"]["test_first_time"] is None


@pytest.mark.parametrize(("fraction", "reason"), [(.25, "insufficient_test_observations"), (.5, "constant_test_outcome")])
def test_undefined_r2_keeps_defined_metrics_and_constant_feature(loaded_ridge, fraction, reason):
    frame = pd.DataFrame({"x": [2, 2, 9, 16], "y": [1, 3, 4, 4]})
    result = native_ridge.run_ridge(frame, outcome="y", predictors=["x"], alpha=1, holdout_fraction=fraction)
    assert result["r2_reason"] == reason
    assert result["metrics"]["r2"] is None and result["mean_baseline"]["r2"] is None
    assert result["metrics"]["rmse"] >= 0 and result["metrics"]["mae"] >= 0
    if fraction == .5:
        assert result["intercept"] == 2 and result["coefficients"]["x"] == 0


def test_large_and_small_feature_scales_have_finite_raw_coefficients(loaded_ridge):
    x = np.arange(10, dtype=float)
    z = np.sin(x)
    frame = pd.DataFrame({"large": x * 1e200, "small": z * 1e-200, "y": 5 + x * 1.7 + z * 2})
    result = native_ridge.run_ridge(frame, outcome="y", predictors=["large", "small"], alpha=1, holdout_fraction=.2)
    scaled = np.column_stack([x, z])
    beta, offset = _oracle(scaled[:8], frame["y"].to_numpy()[:8], 1.0)
    assert result["coefficients"]["large"] * 1e200 == pytest.approx(beta[0])
    assert result["coefficients"]["small"] * 1e-200 == pytest.approx(beta[1])
    assert result["intercept"] == pytest.approx(offset)


def test_training_mean_baseline_retains_a_small_net_response(loaded_ridge):
    frame = pd.DataFrame({"x": np.ones(5), "y": [1e200, 1., -1e200, 0., 1.]})
    result = native_ridge.run_ridge(frame, outcome="y", predictors=["x"], alpha=1, holdout_fraction=.4)
    assert result["intercept"] == pytest.approx(1 / 3)
    assert result["mean_baseline"]["prediction"] == pytest.approx(1 / 3)
    assert result["metrics"] == pytest.approx({key: result["mean_baseline"][key] for key in result["metrics"]})


def test_repeated_and_nearly_collinear_observed_predictors(loaded_ridge):
    frame = _longley()
    frame["same"] = frame["GNP"]
    frame["close"] = frame["GNP"] + 1e-8 * frame["UNEMP"]
    predictors = ["GNP", "same", "close"]
    args = dict(outcome="TOTEMP", predictors=predictors, alpha=.125, holdout_fraction=.25)
    result = native_ridge.run_ridge(frame, **args)
    x, y = frame[predictors].to_numpy(), frame["TOTEMP"].to_numpy()
    beta, intercept = _oracle(x[:12], y[:12], .125)
    assert list(result["coefficients"].values()) == pytest.approx(beta, rel=1e-10)
    assert result["intercept"] == pytest.approx(intercept)


def test_multi_index_columns_are_refused_at_the_adapter():
    frame = pd.DataFrame(np.arange(12).reshape(6, 2), columns=pd.MultiIndex.from_tuples([("x", "value"), ("y", "value")]))
    with pytest.raises(ValueError, match="RIDGE_INVALID_COLUMNS"):
        native_ridge.run_ridge(frame, outcome="y", predictors=["x"], alpha=1, holdout_fraction=.2)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"alpha": 0}, "RIDGE_INVALID_ALPHA"),
        ({"alpha": np.inf}, "RIDGE_INVALID_ALPHA"),
        ({"alpha": True}, "RIDGE_INVALID_ALPHA"),
        ({"holdout_fraction": 1}, "RIDGE_INVALID_HOLDOUT"),
        ({"holdout_fraction": .9}, "RIDGE_SPLIT_TOO_SMALL"),
        ({"predictors": "x"}, "RIDGE_INVALID_COLUMNS"),
        ({"predictors": ["x", "x"]}, "RIDGE_INVALID_COLUMNS"),
        ({"predictors": ["y"]}, "RIDGE_INVALID_COLUMNS"),
        ({"predictors": ["absent"]}, "RIDGE_INVALID_COLUMNS"),
        ({"time_col": "y"}, "RIDGE_INVALID_COLUMNS"),
        ({"time_col": "invalid_date"}, "RIDGE_INVALID_TIME"),
        ({"time_col": "same_date"}, "RIDGE_SPLIT_TOO_SMALL"),
    ],
)
def test_invalid_arguments_fail_before_requesting_the_build(monkeypatch, overrides, error):
    monkeypatch.setattr(native_ridge, "_loaded", lambda: pytest.fail("invalid request reached build loader"))
    frame = pd.DataFrame({"x": range(6), "y": range(1, 7), "invalid_date": ["later"] * 6, "same_date": [1] * 6})
    args = dict(outcome="y", predictors=["x"], alpha=1, holdout_fraction=.2) | overrides
    with pytest.raises(ValueError, match=error):
        native_ridge.run_ridge(frame, **args)


@pytest.mark.parametrize("values", [
    [1., 2., 3., 4., 5., np.inf],
    [1., 2., 3., 4., 5., np.nan],
    ["1", "2", "3", "4", "5", "6"],
    [1 + 1j] * 6,
    [2**53 + 1] * 6,
])
def test_nonfinite_nonnumeric_and_lossy_input_is_rejected(monkeypatch, values):
    monkeypatch.setattr(native_ridge, "_loaded", lambda: pytest.fail("invalid request reached build loader"))
    frame = pd.DataFrame({"x": values, "y": range(6)})
    with pytest.raises(ValueError, match="RIDGE_INVALID_DATA"):
        native_ridge.run_ridge(frame, outcome="y", predictors=["x"], alpha=1, holdout_fraction=.2)


def test_native_boundary_rejects_invalid_lengths_penalty_and_nonfinite(loaded_ridge):
    x = np.arange(4, dtype=np.float64)
    y = np.array([1, 2], dtype=np.float64)
    with pytest.raises(ValueError, match="buffers"):
        loaded_ridge.fit(x.tobytes()[:-1], y.tobytes(), 2, 2, 1.0)
    with pytest.raises(ValueError, match="positive"):
        loaded_ridge.fit(x.tobytes(), y.tobytes(), 2, 2, 0.0)
    x[-1] = np.nan
    with pytest.raises(ValueError, match="finite"):
        loaded_ridge.fit(x.tobytes(), y.tobytes(), 2, 2, 1.0)


def test_native_checkpoints_preserve_exact_exception_and_can_run_again(loaded_ridge):
    rows = 5_000
    x = np.linspace(-1, 1, rows * 2, dtype=np.float64).tobytes()
    y = np.linspace(1, 2, rows, dtype=np.float64).tobytes()
    marker = RuntimeError("cancelled inside C++")
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls >= 4:  # after the centering pass and part of the QR sweep
            raise marker

    with pytest.raises(RuntimeError) as caught:
        loaded_ridge.fit(x, y, rows, 2, 1.0, cancel)
    assert calls == 4
    assert caught.value is marker
    assert len(loaded_ridge.fit(x, y, rows, 2, 1.0)) == 3 * 8

    with cancellation_scope(cancel), pytest.raises(RuntimeError) as caught:
        native_ridge.run_ridge(_longley(), outcome="TOTEMP", predictors=["YEAR"], alpha=1, holdout_fraction=.2)
    assert caught.value is marker


def test_adapter_preserves_owner_exception_inside_native_arithmetic(loaded_ridge):
    marker = FloatingPointError("stop requested by owner")
    checks = 0

    def cancel_during_native_fit():
        nonlocal checks
        checks += 1
        if checks >= 4:
            raise marker

    with cancellation_scope(cancel_during_native_fit), pytest.raises(FloatingPointError) as caught:
        native_ridge.run_ridge(_longley(), outcome="TOTEMP", predictors=["YEAR"], alpha=1, holdout_fraction=.2)
    assert caught.value is marker


@pytest.fixture
def isolated_loader(tmp_path, monkeypatch):
    native_ridge._load_once.cache_clear()
    monkeypatch.setattr(native_ridge, "library_directory", lambda: tmp_path)
    yield tmp_path
    native_ridge._load_once.cache_clear()


def test_missing_build_is_actionable_and_never_falls_back(isolated_loader, monkeypatch):
    monkeypatch.setattr(native_ridge, "_open", lambda *_: pytest.fail("missing build was opened"))
    with pytest.raises(RuntimeError, match="native/ridge/build.py"):
        native_ridge.run_ridge(_longley(), outcome="TOTEMP", predictors=["YEAR"], alpha=1, holdout_fraction=.25)


def test_unverified_binary_is_rejected_before_import(isolated_loader, monkeypatch):
    (isolated_loader / native_ridge._EXTENSION).write_bytes(b"unproven")
    monkeypatch.setattr(native_ridge, "_open", lambda *_: pytest.fail("unproven build was imported"))
    with pytest.raises(RuntimeError, match="RIDGE_BUILD_INVALID"):
        native_ridge._loaded()


def test_wrong_module_abi_after_open_requires_restart(isolated_loader, monkeypatch):
    path = isolated_loader / native_ridge._EXTENSION
    path.write_bytes(b"registered bytes")
    monkeypatch.setattr(native_ridge, "verify_build", lambda *_: {"abi_version": 1})
    calls = []
    monkeypatch.setattr(native_ridge, "_open", lambda *_: calls.append(True) or SimpleNamespace(ABI_VERSION=2))
    with pytest.raises(RuntimeError, match="restart"):
        native_ridge._loaded()
    with pytest.raises(RuntimeError, match="restart"):
        native_ridge._loaded()
    assert calls == [True]


@pytest.mark.parametrize(("alpha", "mixing"), [(.35, .6), (40., .65), (15000., .8)])
def test_elastic_net_longley_compares_to_sklearn_after_frozen_split(loaded_ridge, alpha, mixing):
    linear_model = pytest.importorskip("sklearn.linear_model")
    preprocessing = pytest.importorskip("sklearn.preprocessing")
    frame = _longley()
    predictors = [column for column in frame if column != "TOTEMP"]
    args = dict(outcome="TOTEMP", predictors=predictors, alpha=alpha, l1_ratio=mixing,
                holdout_fraction=.25, time_col="YEAR")
    result = native_ridge.run_elastic_net(frame.iloc[::-1], **args)
    assert native_ridge.run_elastic_net(frame.iloc[::-1], **args) == result
    assert result["model_type"] == "native_elastic_net" and result["engine"] == "cpp17_elastic_net"
    assert result["l1_ratio"] == mixing and result["native_build"]["abi_version"] == 1
    x, y = frame[predictors].to_numpy(), frame["TOTEMP"].to_numpy()
    scaler = preprocessing.StandardScaler().fit(x[:12])
    reference = linear_model.ElasticNet(alpha=alpha, l1_ratio=mixing, max_iter=25_000, tol=1e-14)
    reference.fit(scaler.transform(x[:12]), y[:12])
    beta = reference.coef_ / scaler.scale_
    offset = reference.intercept_ - scaler.mean_ @ beta
    assert list(result["coefficients"].values()) == pytest.approx(beta, rel=2e-8, abs=2e-8)
    assert result["intercept"] == pytest.approx(offset, rel=2e-9, abs=1e-8)
    assert result["metrics"] == pytest.approx(_metrics(y[12:], reference.predict(scaler.transform(x[12:]))))
    assert result["mean_baseline"]["prediction"] == pytest.approx(y[:12].mean())
    convergence = result["convergence"]
    assert convergence["status"] == "converged"
    assert convergence["method"] == "cyclic_coordinate_descent"
    assert 0 < convergence["iterations"] <= convergence["max_iterations"]
    assert convergence["kkt_violation"] <= convergence["kkt_tolerance"] == 1e-11
    assert convergence["scaled_coefficient_error_bound"] <= convergence["kkt_tolerance"]
    assert json.loads(json.dumps(result, allow_nan=False)) == result

    changed = frame.copy()
    changed.loc[changed.index[12:], "GNP"] *= 100
    changed.loc[changed.index[12:], "TOTEMP"] += 10_000
    refit = native_ridge.run_elastic_net(changed, **args)
    assert (refit["coefficients"], refit["intercept"], refit["convergence"]) == (
        result["coefficients"], result["intercept"], result["convergence"],
    )
    assert refit["mean_baseline"]["prediction"] == result["mean_baseline"]["prediction"]
    assert refit["metrics"] != result["metrics"]


@pytest.mark.parametrize("mixing", [0., 1., np.inf, "0.5"])
def test_elastic_net_refuses_invalid_mixing_before_loading(monkeypatch, mixing):
    monkeypatch.setattr(native_ridge, "_loaded", lambda: pytest.fail("invalid request reached native loading"))
    with pytest.raises(ValueError, match="ELASTIC_NET_INVALID_L1_RATIO"):
        native_ridge.run_elastic_net(_longley(), outcome="TOTEMP", predictors=["GNP"], alpha=.1,
                                     l1_ratio=mixing, holdout_fraction=.25)


def test_elastic_net_reports_insufficient_curvature_and_nonconvergence(loaded_ridge, monkeypatch):
    frame = _longley()
    frame["copy"] = frame["GNP"]
    args = dict(outcome="TOTEMP", predictors=["GNP", "copy"], l1_ratio=.5, holdout_fraction=.25)
    with pytest.raises(ValueError, match="ELASTIC_NET_NUMERICAL_RANGE"):
        native_ridge.run_elastic_net(frame, alpha=1e-30, **args)

    monkeypatch.setattr(native_ridge, "_ELASTIC_MAX_ITERATIONS", 1)
    with pytest.raises(ValueError, match="ELASTIC_NET_NOT_CONVERGED"):
        native_ridge.run_elastic_net(frame, alpha=.01, **args)


def test_elastic_net_native_cancellation_refuses_before_reporting(loaded_ridge):
    rows = 5_000
    x = np.linspace(-1, 1, rows * 2, dtype=np.float64).tobytes()
    y = np.linspace(1, 2, rows, dtype=np.float64).tobytes()
    marker = RuntimeError("cancelled inside the coordinate sweep")
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks >= 6:
            raise marker

    with pytest.raises(RuntimeError) as caught:
        loaded_ridge.fit_elastic_net(x, y, rows, 2, .1, .5, 1e-11, 1000, cancel)
    assert caught.value is marker and checks == 6
    assert len(loaded_ridge.fit_elastic_net(x, y, rows, 2, .1, .5, 1e-11, 1000)) == (2 + 4) * 8


@pytest.mark.parametrize("method", ["ridge", "elastic_net"])
def test_prediction_basis_replays_exact_scored_predictions_at_high_offset(loaded_ridge, monkeypatch, method):
    signs = np.tile([-1., 1.], 50)
    frame = pd.DataFrame({"x": 1e12 + signs * 2**-9,
                          "constant": np.r_[np.full(80, 3.), np.full(20, 1e200)], "y": 5 + 3.5 * signs})
    scored = []
    original_metrics = native_ridge._metrics

    def capture(actual, prediction, r2_scale):
        if isinstance(prediction, np.ndarray):
            scored.append(prediction.copy())
        return original_metrics(actual, prediction, r2_scale)

    monkeypatch.setattr(native_ridge, "_metrics", capture)
    args = dict(outcome="y", predictors=["x", "constant"], holdout_fraction=.2)
    if method == "ridge":
        result = native_ridge.run_ridge(frame, alpha=1., **args)
    else:
        result = native_ridge.run_elastic_net(frame, alpha=.35, l1_ratio=.6, **args)

    basis = json.loads(json.dumps(result["prediction_basis"], allow_nan=False))
    assert basis["schema_version"] == 1
    assert basis["scale_policy"] == "training_max_abs_then_population_sd"
    assert basis["predictors"] == result["predictors"]
    assert basis["varying"] == [True, False]
    assert basis["response_magnitude"] == (8.5 if method == "ridge" else 1.0)
    test_rows = frame[basis["predictors"]].to_numpy(dtype=np.float64)[80:]
    standardized = np.zeros(test_rows.shape, dtype=np.float64, order="C")
    np.divide(test_rows, basis["input_magnitude"], out=standardized, where=basis["varying"])
    np.subtract(standardized, basis["normalized_center"], out=standardized, where=basis["varying"])
    np.divide(standardized, basis["normalized_scale"], out=standardized, where=basis["varying"])
    replayed = (standardized @ basis["standardized_coefficients"] + basis["standardized_intercept"]) * basis["response_magnitude"]
    assert len(scored) == 1 and replayed.tobytes() == scored[0].tobytes()
    actual = frame["y"].to_numpy()[80:]
    assert original_metrics(actual, replayed, native_ridge._r2_scale(actual)[0]) == result["metrics"]
    raw_prediction = test_rows @ list(result["coefficients"].values()) + result["intercept"]
    assert np.max(np.abs(replayed - raw_prediction)) > 1e-3
