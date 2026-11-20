"""Chronological alpha selection, final refit, and held-out Ridge evidence."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from workbench import native_ridge, native_ridge_selection
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def modules():
    if not native_ridge.library_directory().exists():
        pytest.skip("build with native/ridge/build.py to exercise Ridge selection")
    return native_ridge_selection, native_ridge


def frame():
    return pd.DataFrame({"t": np.arange(10), "x": [-1., 1.] * 5,
                         "y": [-2., 2.] * 3 + [-1., 1., -1.5, 1.5]})


def run(adapter, data=None, **options):
    base = dict(time_col="t", outcome="y", predictors=["x"], alpha_grid=[.1, 1., 6., 24.],
                holdout_fraction=.2, validation_fraction=.25)
    return adapter.run_ridge_selection(frame() if data is None else data, **(base | options))


def test_hand_selection_and_final_refit_equal_fixed_ridge_on_selected_alpha(modules):
    adapter, ridge = modules
    data = frame().sample(frac=1, random_state=219)
    result = run(adapter, data)
    assert result["model_type"] == "native_ridge_selection"
    assert result["alpha"] == 6.
    assert result["split"]["train_rows"] == 8 and result["split"]["test_rows"] == 2
    detail = result["selection"]
    assert (detail["fit_rows"], detail["validation_rows"], detail["refit_rows"]) == (6, 2, 8)
    assert detail["criterion"] == "validation_rmse" and detail["tie_break"] == "largest_alpha"
    assert detail["selected_alpha"] == 6. and detail["selected_validation_rmse"] == pytest.approx(0., abs=1e-15)
    assert result["prediction_basis"]["selection_times"] == {
        "fit_last_time": "5", "validation_first_time": "6", "validation_last_time": "7",
    }
    assert result["coefficients"]["x"] == pytest.approx(1.)
    assert result["metrics"]["rmse"] == pytest.approx(.5)
    assert result["mean_baseline"]["rmse"] == pytest.approx(1.5)
    fixed = ridge.run_ridge(data, time_col="t", outcome="y", predictors=["x"], alpha=6., holdout_fraction=.2)
    for name in ("alpha", "coefficients", "intercept", "metrics", "mean_baseline", "split", "native_build"):
        assert result[name] == fixed[name]
    basis = {key: value for key, value in result["prediction_basis"].items() if key != "selection_times"}
    assert basis == fixed["prediction_basis"]
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_default_positive_grid_selects_on_validation_and_improves_the_heldout_baseline(modules):
    adapter, _ = modules
    result = adapter.run_ridge_selection(frame(), time_col="t", outcome="y", predictors=["x"])
    candidates = result["selection"]["candidates"]
    assert [candidate["alpha"] for candidate in candidates] == [.01, .1, 1., 10., 100.]
    assert result["alpha"] == 10.
    assert result["selection"]["selected_validation_rmse"] == pytest.approx(.25)
    assert result["metrics"]["rmse"] == pytest.approx(13./18.)
    assert result["mean_baseline"]["rmse"] == pytest.approx(1.5)


def test_product_selection_matches_sklearn_early_scaling_and_final_scoring(modules):
    adapter, _ = modules
    sklearn = pytest.importorskip("sklearn.linear_model")
    preprocessing = pytest.importorskip("sklearn.preprocessing")
    rng = np.random.default_rng(41204)
    x = rng.normal(size=(50, 3))
    x[:30, 2] = 2.
    x[30:40, 2] += 400.
    y = .25 + x[:, 0] - .1*x[:, 1] + rng.normal(scale=.7, size=50)
    data = pd.DataFrame(x, columns=["x", "z", "v"]).assign(t=np.arange(len(y)), y=y)
    grid = [.001, .3, 3., 30., 300.]
    result = run(adapter, data, predictors=["x", "z", "v"], alpha_grid=grid)
    inner = preprocessing.StandardScaler().fit(x[:30])
    refit = preprocessing.StandardScaler().fit(x[:40])
    scores = []
    for alpha in grid:
        candidate = sklearn.Ridge(alpha=alpha, solver="svd").fit(inner.transform(x[:30]), y[:30])
        predicted = candidate.predict(inner.transform(x[30:40]))
        scores.append(math.sqrt(float(np.mean((y[30:40]-predicted)**2))))
    selected = min(range(len(grid)), key=lambda index: (scores[index], -grid[index]))
    assert result["alpha"] == grid[selected]
    np.testing.assert_allclose([item["validation_rmse"] for item in result["selection"]["candidates"]],
                               scores, rtol=1e-12, atol=1e-14)
    final = sklearn.Ridge(alpha=grid[selected], solver="svd").fit(refit.transform(x[:40]), y[:40])
    held = final.predict(refit.transform(x[40:]))
    assert result["metrics"]["rmse"] == pytest.approx(math.sqrt(float(np.mean((y[40:]-held)**2))))
    assert result["mean_baseline"]["prediction"] == pytest.approx(float(y[:40].mean()))


def test_validation_changes_ranking_while_each_candidate_uses_early_training_only(modules):
    adapter, _ = modules
    data = frame()
    data.loc[6:7, "x"] = [-10., 10.]
    data.loc[6:7, "y"] = [-10., 10.]
    prior = run(adapter, data)
    assert prior["alpha"] == 6.
    data.loc[6:7, "y"] = [-20., 20.]
    after = run(adapter, data)
    assert after["alpha"] == .1
    for expected, target_slope in ((prior, 1.), (after, 2.)):
        for item in expected["selection"]["candidates"]:
            coefficient = 12/(6+item["alpha"])
            assert item["validation_rmse"] == pytest.approx(10*abs(coefficient-target_slope), abs=1e-13)
    assert after["coefficients"] != prior["coefficients"]


def test_holdout_changes_only_holdout_scores(modules):
    adapter, _ = modules
    data = frame()
    before = run(adapter, data)
    data.loc[8:, "x"] = [-11., 5.]
    data.loc[8:, "y"] = [20., -100.]
    after = run(adapter, data)
    for name in ("selection", "alpha", "coefficients", "intercept", "prediction_basis", "split"):
        assert after[name] == before[name]
    assert after["mean_baseline"]["prediction"] == before["mean_baseline"]["prediction"]
    assert after["metrics"] != before["metrics"]


def test_equal_times_stay_together_at_both_boundaries(modules):
    adapter, _ = modules
    data = pd.DataFrame({"t": np.repeat(np.arange(6), 2), "x": [-1., 1.] * 6, "y": np.zeros(12)})
    result = run(adapter, data.sample(frac=1, random_state=312), holdout_fraction=.08, validation_fraction=.21)
    assert result["alpha"] == 24.
    assert (result["selection"]["fit_rows"], result["selection"]["validation_rows"], result["split"]["test_rows"]) == (6,4,2)
    assert result["split"]["train_last_time"] == "4" and result["split"]["test_first_time"] == "5"
    assert result["prediction_basis"]["selection_times"] == {
        "fit_last_time": "2", "validation_first_time": "3", "validation_last_time": "4",
    }


def test_prepare_and_pack_once_for_candidate_call_then_fit_once_on_refit_block(modules, monkeypatch):
    adapter, _ = modules
    engine, receipt = adapter._loaded()
    original_selection, original_fit = engine.select_ridge, engine.fit
    calls = []

    def select(*args):
        calls.append(("select", args[4:7], np.frombuffer(args[3], dtype=np.float64).tolist()))
        return original_selection(*args)

    def fit(*args):
        calls.append(("fit", args[2:5]))
        return original_fit(*args)

    monkeypatch.setattr(adapter, "_loaded", lambda: (SimpleNamespace(select_ridge=select, fit=fit), receipt))
    assert run(adapter)["alpha"] == 6.
    assert calls == [("select", (6, 2, 1), [-1., 1.]), ("fit", (8, 1, 6.))]


@pytest.mark.parametrize("options", [{"alpha_grid": [1.]}, {"alpha_grid": [1., 1.]}, {"alpha_grid": [True, 2.]},
                                     {"alpha_grid": [np.nan, 1.]}, {"alpha_grid": list(range(1, 18))},
                                     {"validation_fraction": 0.}, {"validation_fraction": .95},
                                     {"holdout_fraction": .95}])
def test_bad_options_rejected_before_native_loading(modules, monkeypatch, options):
    adapter, _ = modules
    monkeypatch.setattr(adapter, "_loaded", lambda: pytest.fail("invalid request reached native loader"))
    with pytest.raises(ValueError, match="RIDGE_"):
        run(adapter, **options)


def test_product_rejects_inconsistent_native_winner_and_bounds_combined_work(modules, monkeypatch):
    adapter, _ = modules
    engine, receipt = adapter._loaded()

    def corrupt(*args):
        results = np.frombuffer(engine.select_ridge(*args), dtype=np.float64).copy()
        results[0] = 0.
        return results.tobytes()

    monkeypatch.setattr(adapter, "_loaded", lambda: (SimpleNamespace(select_ridge=corrupt, fit=engine.fit), receipt))
    with pytest.raises(RuntimeError, match="RIDGE_SELECTION_BUILD_INVALID"):
        run(adapter)
    with pytest.raises(ValueError, match="RIDGE_SELECTION_WORK_LIMIT"):
        adapter.validate_ridge_selection_size(20_000, 80, alpha_grid=[.1, 1., 6., 24.])


def test_checkpoint_exception_preserved_by_product_selection(modules):
    adapter, _ = modules

    class Stop(Exception):
        pass

    polls = 0

    def checkpoint():
        nonlocal polls
        polls += 1
        if polls >= 7:
            raise Stop("cancel Ridge selection")

    with cancellation_scope(checkpoint), pytest.raises(Stop, match="cancel Ridge selection"):
        run(adapter)
