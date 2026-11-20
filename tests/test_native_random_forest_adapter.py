"""Public/private forest receipt and fixed-prefix checks on the real loader."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.test_native_random_forest import fraction_tree, one_prediction, streams
from workbench import native_random_forest, native_ridge
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def adapter():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise random forest")
    return native_random_forest


def frame():
    return pd.DataFrame({"t":np.arange(10), "x":[0.,1.,2.,3.,4.,5.,6.,7.,1.5,6.5],
                         "z":[0,1]*5, "y":[0,0,1,1,8,8,9,9,3,7]})


def run(adapter, data=None, **options):
    settings = dict(time_col="t", outcome="y", predictors=["x","z"], holdout_fraction=.2,
                    n_trees=5, max_depth=3, min_samples_leaf=2, max_features=1, seed=731)
    return adapter.run_random_forest_regression(frame() if data is None else data, **(settings | options))


def test_fixed_seed_product_fixture_matches_independent_heldout_predictions_and_baseline(adapter):
    data = frame()
    result = run(adapter, data.sample(frac=1, random_state=550))
    assert result["model_type"] == "native_random_forest_regression"
    assert result["engine"] == "cpp17_random_forest_regression"
    assert len(result["native_build"]["build_identity_sha256"]) == 64
    assert result["split"]["train_rows"] == 8 and result["split"]["test_rows"] == 2
    assert result["split"]["train_last_time"] == "7" and result["split"]["test_first_time"] == "8"
    x, y = data[["x","z"]].to_numpy(), data["y"].to_numpy()
    trees = [fraction_tree(x[:8], y[:8], sample, rng, depth=3, leaf=2, m=1) for sample,rng in streams(8,5,731)]
    expected = np.asarray([np.mean([one_prediction(tree,row) for tree in trees]) for row in x[8:]])
    error = expected-y[8:]
    assert result["metrics"] == pytest.approx({"mse":np.mean(error**2),"rmse":np.sqrt(np.mean(error**2)),
                                              "mae":np.mean(abs(error))})
    assert result["mean_baseline"] == pytest.approx({"prediction":4.5,"mse":4.25,"rmse":math.sqrt(4.25),"mae":2.})
    assert result["model_structure"] == {"tree_count":5,"node_count":sum(map(len,trees)),
                                         "leaf_count":sum(np.count_nonzero(tree[:,0] < 0) for tree in trees),
                                         "depth":max(int(tree[:,4].max()) for tree in trees)}
    basis = result["prediction_basis"]
    assert basis["kind"] == "random_forest_regression" and basis["predictor_order"] == ["x","z"]
    assert [tree["tree_id"] for tree in basis["trees"]] == list(range(5))
    assert all(tree["nodes"][0]["training_rows"] == 8 for tree in basis["trees"])
    assert result["options"]["seed"] == 731 and result["options"]["max_features"] == 1
    assert json.loads(json.dumps(result,allow_nan=False)) == result


def test_both_holdout_features_and_targets_can_change_without_refitting_forest(adapter):
    data = frame()
    result = run(adapter, data)
    data.loc[8:,"x"] = [-1e10,1e10]
    data.loc[8:,"z"] = [5,-10]
    data.loc[8:,"y"] = [-20,99]
    other = run(adapter, data)
    assert result["prediction_basis"] == other["prediction_basis"]
    assert result["mean_baseline"]["prediction"] == other["mean_baseline"]["prediction"]
    assert result["metrics"] != other["metrics"]


def test_default_candidate_feature_rule_is_recorded(adapter):
    data = frame().assign(u=lambda f: f.x*2, v=lambda f: f.z*2)
    result = run(adapter, data, predictors=["x","z","u","v"], max_features=0)
    assert result["options"]["max_features"] == 2
    assert result["options"]["max_features_requested"] == 0


@pytest.mark.parametrize("options", [{"max_features":3},{"max_features":True},{"seed":-1},{"seed":2**32},
                                     {"n_trees":33},{"max_depth":11},{"min_samples_leaf":9},
                                     {"predictors":["t"]}])
def test_adapter_validates_options_and_inputs_before_loading(adapter, monkeypatch, options):
    monkeypatch.setattr(adapter,"_loaded",lambda: pytest.fail("invalid options reached native loading"))
    with pytest.raises(ValueError,match="RANDOM_FOREST_"):
        run(adapter,**options)


def test_invalid_forest_receipt_is_rejected_before_scoring(adapter, monkeypatch):
    extension, receipt = adapter._loaded()
    def corrupt(*args):
        packed = np.frombuffer(extension.fit_random_forest_regression(*args),dtype=np.float64).copy()
        packed[6] = 3.
        return packed.tobytes()
    monkeypatch.setattr(adapter,"_loaded",lambda: (SimpleNamespace(
        fit_random_forest_regression=corrupt,
        predict_random_forest_regression=lambda *args: pytest.fail("invalid forest reached scoring"),
    ),receipt))
    with pytest.raises(RuntimeError,match="RANDOM_FOREST_BUILD_INVALID"):
        run(adapter)


def test_adapter_preserves_cancellation_exception(adapter):
    class Stop(Exception):
        pass

    count = 0

    def cancel():
        nonlocal count
        count += 1
        if count >= 8:
            raise Stop("stop forest adapter")

    with cancellation_scope(cancel), pytest.raises(Stop,match="stop forest adapter"):
        run(adapter)
