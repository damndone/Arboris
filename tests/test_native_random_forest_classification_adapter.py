"""Classification forest scoring and local receipt on the attested Ridge loader."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.test_native_random_forest_classification import fraction_gini, streams, tree_probability
from workbench import native_random_forest_classification, native_ridge
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def adapter():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise the classification forest")
    return native_random_forest_classification


def frame():
    return pd.DataFrame({"t":np.arange(12),"x":[0.,1.,2.,3.,4.,5.,6.,7.,.5,2.5,4.5,6.5],
                         "z":[0,1]*6,"y":[0,0,1,1,1,1,0,0,0,1,1,0]})


def run(adapter,data=None,**options):
    settings = dict(time_col="t",outcome="y",predictors=["x","z"],holdout_fraction=1/3,n_trees=9,max_depth=3,
                    min_samples_leaf=2,max_features=1,seed=731)
    return adapter.run_random_forest_classification(frame() if data is None else data,**(settings | options))


def test_manual_fixture_independent_probability_errors_and_training_prevalence(adapter):
    data = frame()
    result = run(adapter,data.sample(frac=1,random_state=35))
    assert result["engine"] == "cpp17_random_forest_classification"
    assert len(result["native_build"]["build_identity_sha256"]) == 64
    assert result["split"]["train_rows"] == 8 and result["split"]["test_rows"] == 4
    assert result["class_counts"] == {"train":{"0":4,"1":4},"test":{"0":2,"1":2}}
    assert result["classification_threshold"] == .5 and result["roc_auc_reason"] is None
    x,y = data[["x","z"]].to_numpy(),data["y"].to_numpy()
    draws = list(streams(8,9,731))
    expected = [fraction_gini(y[:8],x[:8],sample,rng,depth=3,leaf=2,features=1) for sample,rng in draws]
    p = np.array([math.fsum(tree_probability(tree,row) for tree in expected)/len(expected) for row in x[8:]])
    assert result["metrics"] == pytest.approx({"log_loss":np.mean(np.where(y[8:]==1,-np.log(p),-np.log1p(-p))),
                                               "brier_score":np.mean((p-y[8:])**2),"accuracy":1.,"roc_auc":1.})
    assert result["prevalence_baseline"] == pytest.approx({"probability":.5,"log_loss":math.log(2),"brier_score":.25,
                                                           "accuracy":.5,"roc_auc":.5})
    assert result["sampling"]["repeat_fraction"] == 1/3 and result["sampling"]["draws_per_tree"] == 8
    basis = result["prediction_basis"]
    assert basis["kind"] == "random_forest_classification"
    assert basis["predictor_order"] == ["x","z"]
    assert [tree["bootstrap_unique_rows"] for tree in basis["trees"]] == [len(set(sample)) for sample,_ in draws]
    assert result["model_structure"]["node_count"] == 37 and result["model_structure"]["leaf_count"] == 23
    assert json.loads(json.dumps(result,allow_nan=False)) == result


def test_classification_holdout_perturbation_keeps_bootstrap_and_null_auc_reason(adapter):
    data = frame()
    before = run(adapter,data)
    data.loc[8:,"x"] = [1e10,-1e10,1e10,-1e10]
    data.loc[8:,"z"] = [5,-10,5,-10]
    data.loc[8:,"y"] = [1,1,1,1]
    after = run(adapter,data)
    assert after["prediction_basis"] == before["prediction_basis"]
    assert after["sampling"] == before["sampling"]
    assert after["prevalence_baseline"]["probability"] == before["prevalence_baseline"]["probability"]
    assert after["metrics"] != before["metrics"]
    assert after["metrics"]["roc_auc"] is None and after["prevalence_baseline"]["roc_auc"] is None
    assert after["roc_auc_reason"] == "single_class_test_outcome"


@pytest.mark.parametrize("change,match", [("bool","FOREST_CLASSIFICATION_INVALID_LABELS"),
    ("test_label","FOREST_CLASSIFICATION_INVALID_LABELS"),("single_train","FOREST_CLASSIFICATION_TRAIN_SINGLE_CLASS")])
def test_invalid_label_or_single_class_training_fails_before_loading(adapter,monkeypatch,change,match):
    data = frame()
    if change == "bool":
        data["y"] = data["y"] == 1
    elif change == "test_label":
        data.loc[11,"y"] = 2
    else:
        data.loc[:7,"y"] = 0
    monkeypatch.setattr(adapter,"_loaded",lambda:pytest.fail("invalid labels reached native loader"))
    with pytest.raises(ValueError,match=match):
        run(adapter,data)


def test_invalid_sampling_receipt_does_not_get_scored(adapter,monkeypatch):
    extension, receipt = adapter._loaded()
    def corrupt(*args):
        packed = np.frombuffer(extension.fit_random_forest_classification(*args),dtype=np.float64).copy()
        packed[10] = 0
        return packed.tobytes()
    monkeypatch.setattr(adapter,"_loaded",lambda: (SimpleNamespace(
        fit_random_forest_classification=corrupt,
        predict_random_forest_classification=lambda *args:pytest.fail("invalid forest reached scoring"),
    ),receipt))
    with pytest.raises(RuntimeError,match="FOREST_CLASSIFICATION_BUILD_INVALID"):
        run(adapter)


def test_checkpoint_cancellation_is_preserved(adapter):
    class Stop(Exception):
        pass

    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        if calls >= 8:
            raise Stop("stop classification forest")
    with cancellation_scope(checkpoint),pytest.raises(Stop,match="stop classification forest"):
        run(adapter)
