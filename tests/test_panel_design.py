"""PanelOLS built from float columns equals the formula's model, without formulaic's copy.

2026-11-09 footprint diagnostics: every PanelOLS.from_formula fit left formulaic's
materialized data in reference cycles (about 300 MiB for the 1M-row DID event study), so
peaks depended on when the collector ran. panel_ols_model gives PanelOLS the same matrices
directly; these tests hold it to the formula byte for byte and keep every other case on it.
"""
from __future__ import annotations

import gc

import numpy as np
import pandas as pd
import pytest
from linearmodels import panel as panel_module
from linearmodels.panel import PanelOLS

from workbench.econometrics.panel_design import panel_formula, panel_ols_model


def _frame(*, unbalanced=False, missing=False) -> pd.DataFrame:
    rng = np.random.default_rng(9)
    frame = pd.DataFrame({"unit": np.repeat(np.arange(30), 8), "year": np.tile(np.arange(2000, 2008), 30)})
    frame["x1"] = rng.normal(size=len(frame))
    frame["d"] = (rng.random(len(frame)) < 0.4).astype(float)
    frame["y"] = 0.3 * frame["x1"] + frame["d"] + rng.normal(size=len(frame))
    if unbalanced:
        frame = frame.drop(index=rng.choice(len(frame), 25, replace=False))
    if missing:
        frame.loc[frame.index[[3, 40]], "y"] = np.nan
        frame.loc[frame.index[[7]], "x1"] = np.nan
    return frame.set_index(["unit", "year"], drop=False)


def _bytes(frame: pd.DataFrame) -> tuple:
    return list(frame.columns), list(map(str, frame.dtypes)), frame.index.tolist(), frame.to_numpy().tobytes()


CASES = [dict(), dict(unbalanced=True), dict(missing=True), dict(unbalanced=True, missing=True)]


@pytest.mark.parametrize("shape", CASES)
@pytest.mark.parametrize("effects", [(True, True), (True, False), (False, True), (False, False)])
def test_the_model_matrices_and_fit_equal_the_formula_byte_for_byte(shape, effects):
    data = _frame(**shape)
    entity, time = effects
    direct = panel_ols_model(panel_module, data, y="y", regressors=["d", "x1"],
                             entity_effects=entity, time_effects=time)
    formula = PanelOLS.from_formula(panel_formula("y", ["d", "x1"], entity_effects=entity, time_effects=time),
                                    data=data)
    assert _bytes(direct.dependent.dataframe) == _bytes(formula.dependent.dataframe)
    assert _bytes(direct.exog.dataframe) == _bytes(formula.exog.dataframe)
    assert (direct.entity_effects, direct.time_effects, direct.formula) == (
        formula.entity_effects, formula.time_effects, formula.formula)
    for options in (dict(cov_type="unadjusted"), dict(cov_type="clustered", cluster_entity=True)):
        a, b = direct.fit(**options), formula.fit(**options)
        assert a.params.to_numpy().tobytes() == b.params.to_numpy().tobytes()
        assert a.cov.to_numpy().tobytes() == b.cov.to_numpy().tobytes()
        assert a.resids.to_numpy().tobytes() == b.resids.to_numpy().tobytes()


@pytest.mark.parametrize("change", ["integer_column", "odd_name", "duplicate"])
def test_any_other_column_goes_through_the_formula(monkeypatch, change):
    data = _frame()
    regressors = ["d", "x1"]
    if change == "integer_column":
        data["d"] = data["d"].astype(int)
    elif change == "odd_name":
        data = data.rename(columns={"x1": "x 1"})
        regressors = ["d", "x 1"]
    else:
        regressors = ["d", "d"]
    seen = []
    original = PanelOLS.from_formula.__func__
    monkeypatch.setattr(PanelOLS, "from_formula",
                        classmethod(lambda cls, formula, data: seen.append(formula) or original(cls, formula, data)))
    try:
        panel_ols_model(panel_module, data, y="y", regressors=regressors, entity_effects=True, time_effects=True)
    except Exception:
        pass  # a duplicated regressor is the formula's to reject, as before
    assert seen == [panel_formula("y", regressors, entity_effects=True, time_effects=True)]


def _frames_left_by(fit) -> int:
    data = _frame()
    gc.collect()
    gc.disable()
    try:
        before = {id(o) for o in gc.get_objects()}
        fit(data)  # inside a function, as the product calls it: formulaic captures the caller's frame
        return sum(1 for o in gc.get_objects() if id(o) not in before and isinstance(o, pd.DataFrame))
    finally:
        gc.enable()


def test_the_direct_model_leaves_no_copy_of_the_data_behind_and_the_formula_does():
    # As the product writes it: the fit kept in a local, which formulaic's captured context holds.
    def via_formula(data):
        fitted = PanelOLS.from_formula("y ~ 1 + d + x1 + EntityEffects + TimeEffects", data=data).fit()
        return fitted.nobs

    def via_direct(data):
        fitted = panel_ols_model(panel_module, data, y="y", regressors=["d", "x1"],
                                 entity_effects=True, time_effects=True).fit()
        return fitted.nobs

    assert _frames_left_by(via_formula) > 0
    assert _frames_left_by(via_direct) == 0


def _iv_frame() -> pd.DataFrame:
    rng = np.random.default_rng(21)
    n = 300
    frame = pd.DataFrame({"w": rng.normal(size=n), "z1": rng.normal(size=n), "z2": rng.normal(size=n),
                          "z3": rng.normal(size=n)})
    frame["d1"] = frame.z1 + 0.5 * frame.z2 + rng.normal(size=n)
    frame["d2"] = frame.z3 - frame.z1 + rng.normal(size=n)
    frame["y"] = frame.w + frame.d1 - 0.5 * frame.d2 + rng.normal(size=n)
    return frame


@pytest.mark.parametrize("covariance", ["unadjusted", "robust", "kernel"])
@pytest.mark.parametrize("endog,instruments", [(["d1"], ["z1", "z2"]), (["d1", "d2"], ["z1", "z2", "z3"])])
def test_iv_2sls_from_float_columns_equals_the_formula_model_byte_for_byte(monkeypatch, covariance, endog,
                                                                            instruments):
    from linearmodels.iv import IV2SLS
    from workbench.econometrics import panel_iv

    calls = []
    original = IV2SLS.from_formula
    monkeypatch.setattr(IV2SLS, "from_formula", staticmethod(lambda *a, **k: calls.append(a) or original(*a, **k)))
    data = _iv_frame()
    _, direct = panel_iv.run_iv_2sls(data, "y", ["w"], endog, instruments, "iv_2sls_1", covariance=covariance)
    assert calls == []
    formula = original(direct.model.formula, data=data).fit(cov_type=covariance)
    for name in ("dependent", "exog", "endog", "instruments"):
        assert _bytes(getattr(direct.model, name).pandas) == _bytes(getattr(formula.model, name).pandas)
    for attribute in ("params", "cov", "resids"):
        assert getattr(direct, attribute).to_numpy().tobytes() == getattr(formula, attribute).to_numpy().tobytes()


def test_iv_2sls_with_an_integer_column_still_goes_through_the_formula(monkeypatch):
    from linearmodels.iv import IV2SLS
    from workbench.econometrics import panel_iv

    calls = []
    original = IV2SLS.from_formula
    monkeypatch.setattr(IV2SLS, "from_formula", staticmethod(lambda *a, **k: calls.append(a) or original(*a, **k)))
    data = _iv_frame()
    data["z3"] = (data["z3"] > 0).astype(int)
    panel_iv.run_iv_2sls(data, "y", ["w"], ["d1"], ["z1", "z3"], "iv_2sls_1")
    assert len(calls) == 1
