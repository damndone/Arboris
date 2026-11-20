"""Any prediction setting that changes the computation changes the prediction identity.

2026-11-06 risk review, finding 8: identity v1 held sample/split, model_type and model_id but not
the target, the ordered features or the estimator settings. Three runs on one data set and split -
features swapped, target swapped - gave different predictions under one prediction and run identity,
the later two reporting prediction_hit=True.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from workbench import prediction
from workbench.artifacts import initialize_artifact_index
from workbench.prediction import run_prediction_model_v186


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    frame = pd.DataFrame({"x": rng.normal(size=60), "z": rng.normal(size=60)})
    frame["y"] = 2 * frame["x"] + rng.normal(size=60)
    frame["y2"] = frame["z"] - frame["x"]
    return frame


def _run(tmp_path, name, **overrides):
    options = dict(y="y", x=["x"], model_type="prediction_ridge", model_id="ridge-1", final_holdout_fraction=0.25,
                   cv_folds=3, shuffle=False, random_seed=11, data_structure="iid")
    options.update(overrides)
    run_root = tmp_path / "project" / "runs" / name
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    return run_prediction_model_v186(_frame(), run_root, **options)


def _identity(result) -> tuple[str, str]:
    return result["prediction_identity_hash"], result["run_identity_hash"]


@pytest.mark.parametrize("change", [
    {"x": ["z"]}, {"y": "y2"}, {"x": ["x", "z"]}, {"x": ["z", "x"]}, {"model_type": "prediction_lasso"},
    {"random_seed": 12}, {"imputation_method": "mice"},
])
def test_a_computational_change_changes_both_identities(tmp_path, change):
    pytest.importorskip("sklearn")
    base = _identity(_run(tmp_path, "base"))
    changed = _identity(_run(tmp_path, "changed", **change))
    assert changed[0] != base[0] and changed[1] != base[1]


def test_the_same_specification_keeps_its_identity(tmp_path):
    pytest.importorskip("sklearn")
    assert _identity(_run(tmp_path, "a")) == _identity(_run(tmp_path, "b"))


@pytest.mark.parametrize("model_type", sorted(prediction._V186_ESTIMATOR_PARAMETERS))
def test_the_declared_builtin_parameters_are_the_factory_s(model_type):
    pytest.importorskip("sklearn")
    pipeline = prediction._make_v186_estimator_factory(model_type, 11)()
    scaler, estimator = pipeline.steps[0][1], pipeline.steps[-1][1]
    declared = prediction._V186_ESTIMATOR_PARAMETERS[model_type]
    assert type(scaler).__name__ == declared["scaler"] and type(estimator).__name__ == declared["estimator"]
    params = estimator.get_params()
    assert all(params[key] == value for key, value in declared.items() if key not in {"estimator", "scaler"})


def _ridge_factory(alpha):
    from sklearn.linear_model import Ridge

    def factory():
        return Ridge(alpha=alpha)
    return factory


def test_one_caller_factory_name_with_other_parameters_is_another_identity(tmp_path):
    pytest.importorskip("sklearn")
    weak = _identity(_run(tmp_path, "weak", estimator_factory=_ridge_factory(0.1)))
    strong = _identity(_run(tmp_path, "strong", estimator_factory=_ridge_factory(100.0)))
    again = _identity(_run(tmp_path, "again", estimator_factory=_ridge_factory(0.1)))
    assert weak[0] != strong[0] and weak == again


class _ScaleEstimator:
    def __init__(self, weights, strategy=None):
        self.weights = weights
        self.strategy = strategy

    def get_params(self, *, deep):
        return {"weights": self.weights, "strategy": self.strategy}

    def fit(self, features, target):
        return self

    def predict(self, features):
        return features.iloc[:, 0] * self.weights[len(self.weights) // 2]


def test_array_parameters_bind_values_omitted_from_the_display(tmp_path):
    weights = np.ones(4096)
    changed = weights.copy()
    changed[2048] = 4
    with np.printoptions(threshold=1000):
        assert repr(weights) == repr(changed)

    base = _run(tmp_path, "base", estimator_factory=lambda: _ScaleEstimator(weights))
    modified = _run(tmp_path, "changed", estimator_factory=lambda: _ScaleEstimator(changed))
    repeated = _run(tmp_path, "repeated", estimator_factory=lambda: _ScaleEstimator(weights.copy()))

    assert _identity(modified) != _identity(base) == _identity(repeated)
    assert modified["cache"]["prediction_hit"] is False
    assert repeated["cache"]["prediction_hit"] is True


def test_factory_with_varying_fit_parameters_has_no_reusable_prediction_identity(tmp_path):
    def run(name):
        instances = []

        class Estimator(_ScaleEstimator):
            def fit(self, features, target):
                self.fitted = True
                return super().fit(features, target)

        def build():
            # Change only a late control fit. The initial model and all early
            # fits agree, so inspecting one sample would miss the difference.
            estimator = Estimator(np.array([4.0 if len(instances) == 11 else 1.0]))
            instances.append(estimator)
            return estimator

        return _run(tmp_path, name, estimator_factory=build), instances

    first, first_instances = run("first")
    second, second_instances = run("second")
    assert first["prediction_identity_hash"] != second["prediction_identity_hash"]
    assert second["cache"]["transformation_hit"] is True
    assert second["cache"]["prediction_hit"] is False
    for instances in (first_instances, second_instances):
        assert len(instances) == 12 and all(item.fitted for item in instances)


def test_opaque_parameters_have_no_reusable_prediction_identity(tmp_path):
    class OpaqueStrategy:
        def __repr__(self):
            return "OpaqueStrategy()"

    def build():
        return _ScaleEstimator(np.ones(2), strategy=OpaqueStrategy())

    first = _run(tmp_path, "first", estimator_factory=build)
    second = _run(tmp_path, "second", estimator_factory=build)
    assert _identity(first) != _identity(second)
    assert second["cache"]["transformation_hit"] is True
    assert second["cache"]["prediction_hit"] is False


def test_an_estimator_without_get_params_is_identified_by_its_state():
    class Shrink:
        def __init__(self, factor):
            self.factor = factor

    identity = prediction._built_estimator_identity
    assert identity(Shrink(0.5)) == identity(Shrink(0.5)) != identity(Shrink(0.9))
    assert identity(Shrink(object())) is None
