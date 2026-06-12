import numpy as np, pandas as pd
from workbench import orchestrator as orch
from workbench.engine.iv_diagnostics import build_iv_diagnostics


def _fitted(n_instruments):
    rng = np.random.default_rng(1)
    n = 800
    z1 = rng.normal(size=n); z2 = rng.normal(size=n)
    u = rng.normal(size=n)
    educ = 1.5 * z1 + (0.0 if n_instruments == 1 else 1.5 * z2) + u
    wage = 1 + 0.5 * educ + u + rng.normal(size=n) * 0.3
    df = pd.DataFrame({"wage": wage, "educ": educ, "z1": z1, "z2": z2})
    instruments = ["z1"] if n_instruments == 1 else ["z1", "z2"]
    _, fitted = orch.run_iv_2sls(df, y="wage", exog=[], endog=["educ"],
                                 instruments=instruments, model_id="iv_2sls_1")
    return fitted, 1, n_instruments


def test_overidentified_includes_sargan():
    fitted, n_endog, n_instr = _fitted(2)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["identification"] == "over"
    assert d["weak_instruments"]["verdict"] in {"strong", "weak"}
    assert "first_stage_f" in d["weak_instruments"]
    assert d["endogeneity"]["test"] == "wu_hausman"
    assert d["overidentification"]["applicable"] is True
    assert "statistic" in d["overidentification"]


def test_just_identified_overid_not_applicable():
    fitted, n_endog, n_instr = _fitted(1)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["identification"] == "just"
    assert d["overidentification"]["applicable"] is False
    assert "not applicable" in d["overidentification"]["verdict"].lower()


def test_strong_instrument_verdict():
    # z1,z2 each enter educ with coef 1.5 => strong first-stage F
    fitted, n_endog, n_instr = _fitted(2)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["weak_instruments"]["verdict"] == "strong"
    assert d["weak_instruments"]["first_stage_f"] > 10
