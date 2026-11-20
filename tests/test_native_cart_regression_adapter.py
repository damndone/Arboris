"""Product-shaped regression tree receipts on the attested native loader."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from workbench import native_cart_regression, native_ridge
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def adapter():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise CART regression")
    return native_cart_regression


def frame():
    return pd.DataFrame({"time": np.repeat(np.arange(5), 2),
                         "x": [0., 0., 1., 1., 2., 2., 3., 3., 1., 3.],
                         "y": [0., 0., 4., 4., 4., 4., 0., 0., 5., 2.]})


def run(adapter, data=None, **options):
    settings = dict(time_col="time", outcome="y", predictors=["x"], holdout_fraction=.1,
                    max_depth=2, min_samples_leaf=2)
    return adapter.run_cart_regression(frame() if data is None else data, **(settings | options))


def test_adapter_reports_original_unit_holdout_errors_and_training_mean(adapter):
    result = run(adapter, frame().sample(frac=1, random_state=731))
    assert result["model_type"] == "native_cart_regression"
    assert result["engine"] == "cpp17_cart_regression"
    assert len(result["native_build"]["build_identity_sha256"]) == 64
    assert result["metrics"] == pytest.approx({"mse": 2.5, "rmse": math.sqrt(2.5), "mae": 1.5})
    assert result["mean_baseline"] == pytest.approx({"prediction": 2., "mse": 4.5, "rmse": math.sqrt(4.5), "mae": 1.5})
    split = result["split"]
    assert split["train_rows"] == 8 and split["test_rows"] == 2
    assert split["train_last_time"] == "3" and split["test_first_time"] == "4"
    assert result["options"]["criterion"] == "squared_error"
    assert result["model_structure"] == {"node_count": 5, "leaf_count": 3, "depth": 2, "root_predictor": "x"}
    basis = result["prediction_basis"]
    assert basis["kind"] == "regression" and basis["predictor_order"] == ["x"]
    assert basis["nodes"][0] == pytest.approx({
        "node_id": 0, "feature_index": 0, "threshold": .5, "left_id": 1, "right_id": 2, "depth": 0,
        "training_rows": 8, "training_mean": 2., "training_mse": 4., "mse_gain": 4./3.,
    })
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_holdout_predictors_and_outcome_cannot_change_training_tree_or_baseline(adapter):
    data = frame()
    first = run(adapter, data)
    data.loc[data["time"] == 4, ["x", "y"]] = [[-1e12, -15.], [1e12, 9.]]
    second = run(adapter, data)
    assert second["prediction_basis"] == first["prediction_basis"]
    assert second["mean_baseline"]["prediction"] == first["mean_baseline"]["prediction"] == 2.0
    assert second["metrics"] != first["metrics"]


def test_constant_response_is_a_valid_tree_with_zero_test_errors(adapter):
    result = run(adapter, frame().assign(y=4.))
    assert result["model_structure"] == {"node_count": 1, "leaf_count": 1, "depth": 0, "root_predictor": None}
    assert result["metrics"] == {"mse": 0., "rmse": 0., "mae": 0.}
    assert result["mean_baseline"]["prediction"] == 4.


@pytest.mark.parametrize("changed,options,message", [
    ("bool", {}, "CART_REGRESSION_INVALID_DATA"),
    ("large_int", {}, "exact binary64"),
    ("nan", {}, "finite numeric"),
    (None, {"predictors": ["time"]}, "CART_REGRESSION_INVALID_COLUMNS"),
    (None, {"min_samples_leaf": 9}, "CART_REGRESSION_INVALID_LEAF"),
])
def test_invalid_input_is_rejected_before_native_fit(adapter, monkeypatch, changed, options, message):
    data = frame()
    if changed == "bool":
        data["y"] = data["y"] > 0
    elif changed == "large_int":
        data["y"] = np.arange(2**53 + 1, 2**53 + 11, dtype=np.int64)
    elif changed == "nan":
        data.loc[9, "x"] = np.nan
    monkeypatch.setattr(adapter, "_loaded", lambda: pytest.fail("invalid input reached the native build"))
    with pytest.raises(ValueError, match=message):
        run(adapter, data, **options)


@pytest.mark.parametrize("magnitude", [1e-200, 1e200])
def test_unrepresentable_holdout_mse_cannot_appear_as_a_finite_zero_or_infinity(adapter, magnitude):
    data = frame().assign(y=0.)
    data.loc[data["time"] == 4, "y"] = magnitude
    with pytest.raises(ValueError, match="CART_REGRESSION_NUMERICAL_RANGE"):
        run(adapter, data)


def test_nonzero_holdout_residual_fails_even_when_rmse_rounds_to_zero(adapter):
    data = frame().assign(y=0.)
    data.loc[9, "y"] = math.nextafter(0., 1.)
    with pytest.raises(ValueError, match="CART_REGRESSION_NUMERICAL_RANGE"):
        run(adapter, data, holdout_fraction=.5)


def test_adapter_preserves_native_cancellation_and_missing_abi_is_explicit(adapter, monkeypatch):
    class Stop(Exception):
        pass

    count = 0

    def stop():
        nonlocal count
        count += 1
        if count >= 7:
            raise Stop("stop tree fit")

    with cancellation_scope(stop), pytest.raises(Stop, match="stop tree fit"):
        run(adapter)
    monkeypatch.setattr(adapter, "_loaded", lambda: (SimpleNamespace(), {}))
    with pytest.raises(RuntimeError, match="CART_REGRESSION_BUILD_INVALID"):
        run(adapter)
