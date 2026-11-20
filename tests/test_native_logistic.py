"""Binary logistic prediction evidence at the adapter and extension boundaries."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

from workbench import native_ridge


@pytest.fixture
def native():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise native Logistic")
    return native_ridge._loaded()[0]


def _tiny_frame():
    return pd.DataFrame({"x": [1, 5, 1, 5, 1, 5], "y": [0, 1, 0, 1, 0, 1]})


def _run(frame, **options):
    return native_ridge.run_logistic(frame, **({
        "outcome": "y", "predictors": ["x"], "alpha": 1 / (3 * math.log(2)), "holdout_fraction": .25,
    } | options))


def test_known_penalized_solution_and_holdout_metrics(native):
    frame = _tiny_frame()
    result = _run(frame)
    log_two = math.log(2)
    assert result["coefficients"]["x"] == pytest.approx(log_two / 2, abs=1e-10)
    assert result["intercept"] == pytest.approx(-3 * log_two / 2, abs=1e-10)
    assert result["metrics"] == pytest.approx({
        "log_loss": math.log(1.5), "brier_score": 1 / 9, "accuracy": 1, "roc_auc": 1,
    })
    assert result["prevalence_baseline"] == pytest.approx({
        "probability": .5, "log_loss": log_two, "brier_score": .25, "accuracy": .5, "roc_auc": .5,
    })
    assert result["class_counts"] == {"train": {"0": 2, "1": 2}, "test": {"0": 1, "1": 1}}
    assert result["convergence"]["objective"] == pytest.approx(math.log(1.5) + log_two / 6)
    assert result["convergence"]["gradient_infinity_norm"] <= result["convergence"]["gradient_tolerance"]
    assert result["link"] == result["prediction_basis"]["link"] == "logit"
    assert result["classification_threshold"] == .5
    assert result["native_build"]["module"] == "ridge"
    assert _run(frame) == json.loads(json.dumps(result, allow_nan=False)) == result


def test_breast_cancer_fixture_matches_independent_sklearn_objective(native):
    pytest.importorskip("sklearn")
    from sklearn.datasets import load_breast_cancer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    data = load_breast_cancer()
    x, y = data.data, data.target
    names = list(data.feature_names)
    frame = pd.DataFrame(x, columns=names).assign(y=y)
    alpha = .07
    result = _run(frame, predictors=names, alpha=alpha, holdout_fraction=.25)
    rows = len(frame) - math.ceil(len(frame) / 4)
    scaler = StandardScaler().fit(x[:rows])
    train = scaler.transform(x[:rows])
    test = scaler.transform(x[rows:])
    oracle = LogisticRegression(C=1 / (rows * alpha), solver="lbfgs", tol=1e-13, max_iter=1000).fit(train, y[:rows])
    basis = result["prediction_basis"]
    np.testing.assert_allclose(basis["standardized_coefficients"], oracle.coef_[0], rtol=0, atol=2e-7)
    assert basis["standardized_intercept"] == pytest.approx(oracle.intercept_[0], abs=2e-7)
    scores = train @ basis["standardized_coefficients"] + basis["standardized_intercept"]
    residual = expit(scores) - y[:rows]
    gradient = np.r_[train.T @ residual / rows + alpha * np.array(basis["standardized_coefficients"]), residual.mean()]
    assert np.max(np.abs(gradient)) <= result["convergence"]["gradient_tolerance"]
    probabilities = oracle.predict_proba(test)[:, 1]
    assert result["metrics"] == pytest.approx({
        "log_loss": log_loss(y[rows:], probabilities), "brier_score": brier_score_loss(y[rows:], probabilities),
        "accuracy": accuracy_score(y[rows:], probabilities >= .5), "roc_auc": roc_auc_score(y[rows:], probabilities),
    }, abs=5e-8)


def test_training_only_scaling_tied_times_and_one_class_holdout(native):
    frame = _tiny_frame().assign(time=[1, 1, 2, 2, 3, 3]).iloc[[5, 0, 3, 1, 4, 2]]
    result = _run(frame, holdout_fraction=.15, time_col="time")
    assert result["split"]["train_rows"] == 4
    assert result["split"]["train_last_time"] == "2" and result["split"]["test_first_time"] == "3"
    changed = frame.copy()
    changed.loc[changed["time"] == 3, ["x", "y"]] = [-10000, 1]
    after = _run(changed, holdout_fraction=.15, time_col="time")
    for field in ("coefficients", "intercept", "prediction_basis", "convergence"):
        assert after[field] == result[field]
    assert after["prevalence_baseline"]["probability"] == .5
    assert after["metrics"]["log_loss"] > 3000
    assert after["metrics"]["accuracy"] == 0 and after["metrics"]["brier_score"] == 1
    assert after["metrics"]["roc_auc"] is None and after["prevalence_baseline"]["roc_auc"] is None
    assert after["roc_auc_reason"] == "single_class_test_outcome"


def test_constant_training_feature_and_tied_decision_scores(native):
    frame = _tiny_frame().assign(x=[1, 1, 1, 1, -1, 9], y=[0, 0, 1, 0, 0, 1])
    result = _run(frame)
    assert result["coefficients"] == {"x": 0.0}
    assert result["prediction_basis"]["varying"] == [False]
    assert result["convergence"]["iterations"] == 0
    assert result["prevalence_baseline"]["probability"] == .25
    assert result["metrics"] == pytest.approx({
        "log_loss": -(math.log(.25) + math.log(.75)) / 2,
        "brier_score": (.25**2 + .75**2) / 2, "accuracy": .5, "roc_auc": .5,
    })


@pytest.mark.parametrize("labels", [
    ["0", "1"] * 3, [False, True] * 3, [0, 1, 0, 1, .5, 1], [0, 1, 0, 1, 2, 1],
    [0, 1, 0, 1, np.inf, 1], pd.array([0, 1, 0, 1, pd.NA, 1], dtype="Int64"),
])
def test_invalid_binary_labels_fail_before_loading_native(monkeypatch, labels):
    monkeypatch.setattr(native_ridge, "_loaded", lambda: pytest.fail("invalid labels reached build loader"))
    with pytest.raises(ValueError, match="LOGISTIC_INVALID_LABELS"):
        _run(_tiny_frame().assign(y=labels))


def test_training_requires_both_classes_even_if_test_has_both(monkeypatch):
    monkeypatch.setattr(native_ridge, "_loaded", lambda: pytest.fail("single class reached build loader"))
    with pytest.raises(ValueError, match="LOGISTIC_TRAIN_SINGLE_CLASS"):
        _run(_tiny_frame().assign(y=[1, 1, 1, 1, 0, 1]))


@pytest.mark.parametrize("alpha", [True, 0, 1e-7, np.inf, 1e7])
def test_penalty_range_is_explicit(monkeypatch, alpha):
    monkeypatch.setattr(native_ridge, "_loaded", lambda: pytest.fail("invalid penalty reached build loader"))
    with pytest.raises(ValueError, match="LOGISTIC_INVALID_ALPHA"):
        _run(_tiny_frame(), alpha=alpha)


def test_native_rejects_bad_buffers_labels_and_nonconvergence(native):
    x = np.array([-1., 1., -1., 1.]).tobytes()
    y = np.array([0., 1., 0., 1.]).tobytes()
    with pytest.raises(ValueError, match="LOGISTIC_INVALID_DATA"):
        native.fit_logistic(x[:-1], y, 4, 1, .1, 128)
    with pytest.raises(ValueError, match="LOGISTIC_INVALID_LABELS"):
        native.fit_logistic(x, np.array([0., 1., 0., .5]).tobytes(), 4, 1, .1, 128)
    with pytest.raises(ValueError, match="LOGISTIC_TRAIN_SINGLE_CLASS"):
        native.fit_logistic(x, bytes(len(y)), 4, 1, .1, 128)
    with pytest.raises(ValueError, match="LOGISTIC_NOT_CONVERGED"):
        native.fit_logistic(x, y, 4, 1, .1, 1)


def test_native_cancellation_surfaces_original_exception(native):
    class Cancelled(Exception):
        pass

    def cancel():
        raise Cancelled("fit interrupted")

    x = np.array([-1., 1., -1., 1.]).tobytes()
    y = np.array([0., 1., 0., 1.]).tobytes()
    with pytest.raises(Cancelled, match="fit interrupted"):
        native.fit_logistic(x, y, 4, 1, .1, 128, cancel)
