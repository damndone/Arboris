"""A persisted forest scores new rows through the existing C++ scorer."""

from copy import deepcopy
import importlib
import importlib.util
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.test_native_random_forest_adapter import frame, run
from workbench import native_random_forest, native_ridge
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def saved():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py")
    result = json.loads(json.dumps(run(native_random_forest), allow_nan=False))
    return result, result.pop("prediction_basis")


def module():
    assert importlib.util.find_spec("workbench.native_prediction_apply") is not None, "saved forest application is missing"
    return importlib.import_module("workbench.native_prediction_apply")


def score(data, result, basis):
    kernel = module()
    return kernel.score_saved_forest(data, forest=kernel.forest_buffer(result, basis))


def independent_predictions(data, basis):
    output = []
    for row in data[basis["predictor_order"]].itertuples(index=False, name=None):
        leaves = []
        for tree in basis["trees"]:
            node = tree["nodes"][0]
            while node["feature_index"] >= 0:
                side = "left_id" if row[node["feature_index"]] <= node["threshold"] else "right_id"
                node = tree["nodes"][node[side]]
            leaves.append(node["training_mean"])
        output.append(sum(leaves) / len(leaves))
    return np.asarray(output)


def test_saved_forest_scores_new_rows_without_outcome_in_persisted_order(saved):
    result, basis = saved
    data = frame().iloc[[9, 8, 1]][["z", "x"]].assign(label=["last", "first", "old"])
    before = data.copy(deep=True)
    predictions, receipt = score(data, result, basis)
    np.testing.assert_allclose(predictions, independent_predictions(data, basis), rtol=1e-15, atol=0)
    assert predictions.shape == (3,) and predictions.dtype == np.float64
    assert receipt["binary_sha256"] == result["native_build"]["binary_sha256"]
    pd.testing.assert_frame_equal(data, before)


@pytest.mark.parametrize("change", ["missing", "strings", "nonfinite", "unsafe_integer", "empty"])
def test_saved_forest_refuses_invalid_new_data(saved, change):
    result, basis = saved
    data = frame()[["x", "z"]].copy()
    if change == "missing":
        data = data.drop(columns="x")
    elif change == "strings":
        data["x"] = data.x.astype(str)
    elif change == "nonfinite":
        data.loc[2, "x"] = np.inf
    elif change == "unsafe_integer":
        data["x"] = np.array([2**53 + 1] * len(data), dtype=np.int64)
    else:
        data = data.iloc[:0]
    with pytest.raises(ValueError, match="FOREST_APPLY_"):
        score(data, result, basis)


@pytest.mark.parametrize("change", ["model", "order", "tree_id", "child", "nonfinite", "count"])
def test_saved_forest_refuses_inconsistent_model(saved, change):
    result, basis = deepcopy(saved)
    if change == "model":
        result["model_type"] = "native_cart_regression"
    elif change == "order":
        basis["predictor_order"].reverse()
    elif change == "tree_id":
        basis["trees"][0]["tree_id"] = 1
    elif change == "child":
        basis["trees"][0]["nodes"][0]["left_id"] = 999999
    elif change == "nonfinite":
        basis["trees"][0]["nodes"][0]["training_mean"] = float("nan")
    else:
        result["options"]["n_trees"] = 33
    with pytest.raises(ValueError, match="FOREST_APPLY_|RANDOM_FOREST_"):
        score(frame()[["x", "z"]], result, basis)


def test_saved_holdout_predictions_are_bit_identical_and_never_refit(saved, monkeypatch):
    native, receipt = native_ridge._loaded()
    observed = []

    def capture(*args):
        scored = native.predict_random_forest_regression(*args)
        observed.append(scored)
        return scored

    monkeypatch.setattr(native_random_forest, "_loaded", lambda: (SimpleNamespace(
        fit_random_forest_regression=native.fit_random_forest_regression,
        predict_random_forest_regression=capture,
    ), receipt))
    run(native_random_forest)
    monkeypatch.setattr(module(), "_loaded", lambda: (SimpleNamespace(
        predict_random_forest_regression=native.predict_random_forest_regression,
    ), receipt))
    result, basis = saved
    predictions, _ = score(frame().iloc[8:][["x", "z"]], result, basis)
    assert predictions.tobytes() == observed[0]


def test_large_scoring_is_batched_and_preserves_native_cancellation(saved, monkeypatch):
    native, receipt = native_ridge._loaded()
    calls = []

    def capture(values, rows, columns, packed, checkpoint):
        calls.append(rows)
        return native.predict_random_forest_regression(values, rows, columns, packed, checkpoint)

    monkeypatch.setattr(module(), "_loaded", lambda: (SimpleNamespace(predict_random_forest_regression=capture), receipt))
    data = pd.concat([frame()[["x", "z"]]] * 900, ignore_index=True)
    result, basis = saved
    prediction, _ = score(data, result, basis)
    assert len(prediction) == 9000 and sum(calls) == 9000 and max(calls) <= 4096 and len(calls) >= 3

    class Stop(Exception):
        pass

    calls.clear()

    def cancel():
        if calls:
            raise Stop("cancel inside native scoring")

    with cancellation_scope(cancel), pytest.raises(Stop, match="cancel inside native scoring"):
        score(data, result, basis)
    assert len(calls) == 1


def test_broken_or_missing_native_scoring_is_an_explicit_error(saved, monkeypatch):
    result, basis = saved
    monkeypatch.setattr(module(), "_loaded", lambda: (SimpleNamespace(), {}))
    with pytest.raises(RuntimeError, match="FOREST_APPLY_BUILD_INVALID"):
        score(frame(), result, basis)


def test_saved_classifier_restores_exact_native_buffer_and_scores_without_refit(monkeypatch):
    from tests.test_native_random_forest_classification_adapter import frame as classification_frame, run as train
    from workbench import native_random_forest_classification as classification

    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py")
    native, receipt = native_ridge._loaded()
    fitted, scored = [], []

    def fit(*args):
        value = native.fit_random_forest_classification(*args)
        fitted.append(value)
        return value

    def predict(*args):
        value = native.predict_random_forest_classification(*args)
        scored.append(value)
        return value

    monkeypatch.setattr(classification, "_loaded", lambda: (SimpleNamespace(
        fit_random_forest_classification=fit, predict_random_forest_classification=predict), receipt))
    result = json.loads(json.dumps(train(classification), allow_nan=False))
    basis = result.pop("prediction_basis")
    restored = module().forest_buffer(result, basis)
    assert restored[1] == fitted[0], "reopening the saved trees must preserve the exact native scoring receipt"
    monkeypatch.setattr(module(), "_loaded", lambda: (SimpleNamespace(
        predict_random_forest_classification=native.predict_random_forest_classification), receipt))
    data = classification_frame().iloc[8:][["z", "x"]]
    output, _ = module().score_saved_forest(data, forest=restored, classification=True)
    assert output.tobytes() == scored[0]
    assert ((0 < output) & (output < 1)).all() and len(fitted) == 1


@pytest.fixture
def saved_classifier():
    from tests.test_native_random_forest_classification_adapter import run as train
    from workbench import native_random_forest_classification as classification

    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py")
    result = json.loads(json.dumps(train(classification), allow_nan=False))
    return result, result.pop("prediction_basis")


@pytest.mark.parametrize("change", ["threshold", "train_count", "bootstrap", "child"])
def test_saved_classifier_rejects_changed_probability_contract_or_structure(saved_classifier, change):
    result, basis = saved_classifier
    if change == "threshold":
        result["classification_threshold"] = .4
    elif change == "train_count":
        result["class_counts"]["train"]["1"] += 1
    elif change == "bootstrap":
        basis["trees"][0]["bootstrap_unique_rows"] = 0
    else:
        basis["trees"][0]["nodes"][0]["left_id"] = 999999
    with pytest.raises(ValueError, match="FOREST_APPLY_|FOREST_CLASSIFICATION_"):
        module().score_saved_forest(frame()[["x", "z"]], forest=module().forest_buffer(result, basis), classification=True)


@pytest.mark.parametrize("probability", [0., 1.])
def test_classifier_native_probabilities_must_respect_existing_open_interval(saved_classifier, monkeypatch, probability):
    result, basis = saved_classifier
    monkeypatch.setattr(module(), "_loaded", lambda: (SimpleNamespace(
        predict_random_forest_classification=lambda values, rows, *args: np.full(rows, probability).tobytes()), {}))
    with pytest.raises(RuntimeError, match="FOREST_APPLY_BUILD_INVALID"):
        module().score_saved_forest(frame(), forest=module().forest_buffer(result, basis), classification=True)


def test_classifier_batches_new_rows_and_stops_before_the_next_batch(saved_classifier, monkeypatch):
    result, basis = saved_classifier
    native, receipt = native_ridge._loaded()
    calls = []

    def predict(values, rows, *args):
        calls.append(rows)
        return native.predict_random_forest_classification(values, rows, *args)

    monkeypatch.setattr(module(), "_loaded", lambda: (SimpleNamespace(predict_random_forest_classification=predict), receipt))
    data = pd.concat([frame()[["x", "z"]]] * 500, ignore_index=True)
    forest = module().forest_buffer(result, basis)
    output, _ = module().score_saved_forest(data, forest=forest, classification=True)
    assert len(output) == len(data) and calls == [4096, len(data) - 4096]

    class Stop(Exception):
        pass

    calls.clear()

    def cancel():
        if calls:
            raise Stop("classification cancelled")

    with cancellation_scope(cancel), pytest.raises(Stop, match="classification cancelled"):
        module().score_saved_forest(data, forest=forest, classification=True)
    assert calls == [4096]
