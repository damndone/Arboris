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


def test_robust_fit_uses_robust_tests_and_actual_reference_distribution():
    fitted, n_endog, n_instr = _fitted(2)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["identification"] == "over"
    assert d["weak_instruments"]["verdict"] == "unassessed"
    assert d["weak_instruments"]["first_stage_f"] is None
    assert d["weak_instruments"]["reference_distribution"] == "chi2(2)"
    assert d["endogeneity"]["test"] == "wooldridge_regression"
    assert d["overidentification"]["test"] == "wooldridge_overid"
    assert d["overidentification"]["statistic"] == fitted.wooldridge_overid.stat
    assert d["overidentification"]["applicable"] is True
    assert "statistic" in d["overidentification"]


def test_just_identified_overid_not_applicable():
    fitted, n_endog, n_instr = _fitted(1)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["identification"] == "just"
    assert d["overidentification"]["applicable"] is False
    assert "not applicable" in d["overidentification"]["verdict"].lower()


def test_large_robust_chi_square_does_not_certify_strength():
    fitted, n_endog, n_instr = _fitted(2)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["weak_instruments"]["verdict"] == "unassessed"
    assert d["weak_instruments"]["first_stage_statistic"] > 1000
    assert d["weak_instruments"]["threshold"] is None


def test_clustered_fit_cannot_substitute_iid_hc0_inference():
    from workbench.checks import build_context
    from workbench.checks.iv_checks import FIRST_STAGE_STRENGTH
    fitted, *_ = _fitted(2)
    clustered = fitted.model.fit(cov_type='clustered', clusters=np.arange(800)//10)
    checked = FIRST_STAGE_STRENGTH.run(build_context(fitted=clustered, model_type='iv_2sls', model_id='iv_1', kernel=None, nobs=800), FIRST_STAGE_STRENGTH)
    assert checked.evidence['anderson_rubin_95']['kind'] == 'unavailable'
    assert checked.evidence['anderson_rubin_95']['reason'] == 'unsupported_covariance_for_ar'


def test_categorical_instrument_rank_failure_does_not_publish_an_ar_set(tmp_path):
    import json
    from workbench.projects import create_project
    rng = np.random.default_rng(14)
    group = np.tile(['a', 'b', 'c'], 40)
    latent = rng.normal(size=120)
    x = np.tile([0., 1., 3.], 40)+latent
    frame = pd.DataFrame({'y': 2*x+latent+rng.normal(size=120), 'x': x, 'z': group})
    source = tmp_path / 'category.csv'
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, 'category')
    outcome = orch.run_workflow(project.root, [source], mode='auto', model_type='iv_2sls',
        y='y', x=[], iv_endog=['x'], iv_instruments=['z'], covariance='robust')
    assert outcome['status'] == 'failed', outcome
    run = project.root / 'runs' / outcome['run_id']
    issues = json.loads((run / 'errors.json').read_text())['issues']
    assert any('instruments [exog instruments]  do not have full column rank' in issue['message'] for issue in issues)
    assert not (run / 'iv_diagnostics.json').exists()
