import numpy as np, pandas as pd, pytest
from workbench.engine.cs_attgt import comparison_mask, CSSpecError

def _panel():
    return pd.read_csv("tests/fixtures/cs_did/panel.csv")

def test_never_treated_comparison_excludes_all_finite_cohorts():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="never", anticipation=0)
    assert set(cohort[m].unique()) == {np.inf}

def test_not_yet_treated_boundary_delta0():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="not_yet", anticipation=0)
    qualifying = set(cohort[m].unique())
    assert np.inf in qualifying and 5 in qualifying
    assert 3 not in qualifying and 4 not in qualifying

def test_not_yet_treated_boundary_delta1_shifts():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="not_yet", anticipation=1)
    assert 5 not in set(cohort[m].unique())

from workbench.engine.cs_attgt import base_period_for, effective_treatment_start, reference_period

def test_reference_and_effective_start_use_anticipation():
    assert effective_treatment_start(g=4, anticipation=1) == 3
    assert reference_period(g=4, anticipation=1) == 2

def test_post_period_base_is_reference():
    assert base_period_for(g=4, t=5, base_period="varying", anticipation=0) == 3

def test_varying_pre_period_is_sequential():
    # t < effective_treatment_start(=4): varying base = t-1
    assert base_period_for(g=4, t=2, base_period="varying", anticipation=0) == 1

def test_universal_pre_period_is_fixed_reference():
    assert base_period_for(g=4, t=2, base_period="universal", anticipation=0) == 3

def test_boundary_at_effective_start_is_post():
    # t == effective_treatment_start(g=4, δ=0) == 4 must be POST → base = reference = 3,
    # NOT the varying pre rule (t-1 = 3 here coincidentally, so use δ=1 to disambiguate):
    assert base_period_for(g=4, t=4, base_period="varying", anticipation=0) == 3
    # δ=1: effective start = 3, reference = 2; t=3 is post → base = 2 (not t-1=2 — pick t=4)
    assert base_period_for(g=5, t=4, base_period="varying", anticipation=1) == 3  # post: ref=5-1-1=3
    assert base_period_for(g=5, t=2, base_period="varying", anticipation=1) == 1  # pre: t-1


def _attach_cohort(d):
    d = d.copy()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    d["_did_cohort"] = d["unit"].map(cohort)
    return d

def test_empty_x_collapse_to_2x2():
    from workbench.engine.cs_attgt import att_gt_cell
    d = _attach_cohort(pd.read_csv("tests/fixtures/cs_did/panel.csv"))
    kw = dict(frame=d, entity="unit", time="period", y="y", g=4.0, t=4.0, base_t=3.0,
              control_group="never", anticipation=0, covariates=[])
    dr  = att_gt_cell(est_method="dr",  **kw)["att"]
    ipw = att_gt_cell(est_method="ipw", **kw)["att"]
    reg = att_gt_cell(est_method="reg", **kw)["att"]
    # with no covariates all three collapse to the clean 2x2 mean-difference
    assert abs(dr - ipw) < 1e-10 and abs(dr - reg) < 1e-10

def test_influence_columns_mean_zero():
    from workbench.engine.cs_attgt import cell_influence_function, att_gt_cell
    d = _attach_cohort(pd.read_csv("tests/fixtures/cs_did/panel.csv"))
    cell = att_gt_cell(frame=d, entity="unit", time="period", y="y", g=4.0, t=4.0,
        base_t=3.0, control_group="never", anticipation=0, covariates=["x1"], est_method="dr")
    assert abs(cell_influence_function(cell, est_method="dr").mean()) < 1e-8

def test_cluster_influence_identity_and_sum():
    from workbench.engine.cs_attgt import cluster_influence
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    ids, summed = cluster_influence(obs, np.array([10, 20, 30, 40]))
    assert np.array_equal(ids, np.array([10, 20, 30, 40]))
    assert np.allclose(summed, obs)
    ids2, summed2 = cluster_influence(obs, np.array([10, 10, 30, 40]))
    assert np.array_equal(ids2, np.array([10, 30, 40]))
    assert np.allclose(summed2, np.array([3.0, 3.0, 4.0]))


def _high_ps_panel():
    """Panel with ONE control whose fitted propensity exceeds DRDID's 0.995 trim
    threshold. A long, well-separated treated tail keeps the logit slope steep and
    converged; the lone over-threshold control carries a WILD outcome jump so that
    trimming vs not changes the ATT by a large, unmistakable margin. Deterministic
    (no RNG) so the pinned trimmed-ATT values below are stable."""
    xt = np.linspace(5, 40, 30)          # treated, wide high range -> steep slope
    xc = np.linspace(-40, -5, 30)        # clean controls, far negative
    rogue = 30.0                          # control that the logit reads as ~certainly treated
    rows = []
    def add(u, cohort, x1, k):
        y3 = 0.1 * k - 0.3
        eff = 2.0 if cohort == 4 else 0.0
        y4 = y3 + 0.5 + eff
        rows.append(dict(unit=u, period=3, first_treat=cohort, x1=x1, y=y3))
        rows.append(dict(unit=u, period=4, first_treat=cohort, x1=x1, y=y4))
    u = k = 0
    for x in xt:
        add(u, 4, x, k); u += 1; k += 1
    for x in xc:
        add(u, 0, x, k); u += 1; k += 1
    rogue_id = u
    add(rogue_id, 0, rogue, k)
    for r in rows:                        # poison only the rogue control's t=4 outcome
        if r["unit"] == rogue_id and r["period"] == 4:
            r["y"] += 50.0
    d = _attach_cohort(pd.DataFrame(rows))
    return d, rogue_id


def test_trim_ps_applied_consistently_in_att_and_influence_function():
    """Regression: att_gt_cell must apply DRDID's trim.ps (control kept iff
    ps < CS_PS_TRIM = 0.995) to the POINT ESTIMATE, the same trim the influence
    function uses — so both describe one effective sample. Pre-fix, att_gt_cell did
    not trim, so the rogue control (ps>=0.995, wild outcome) blew up the ATT while
    the IF silently dropped it. This test fails if the trim is removed from
    att_gt_cell (the att collapses back to the untrimmed value)."""
    from workbench.engine.cs_attgt import att_gt_cell, cell_influence_function, CS_PS_TRIM
    assert CS_PS_TRIM == 0.995  # DRDID 1.3.0 control-side trim.level default
    d, rogue_id = _high_ps_panel()
    # Pinned trimmed (= IF-consistent) ATTs for this deterministic panel; the
    # untrimmed ATTs are far away (dr ~ -44.65, ipw ~ much larger in magnitude).
    expected = {"dr": -11.6389713117, "ipw": 2.0}
    for method, exp_att in expected.items():
        cell = att_gt_cell(frame=d, entity="unit", time="period", y="y", g=4.0, t=4.0,
            base_t=3.0, control_group="never", anticipation=0, covariates=["x1"],
            est_method=method)
        pos = {u: i for i, u in enumerate(cell["_units"])}
        ir = pos[rogue_id]
        # (a) the rogue control is over threshold and gets ZERO direct weight in BOTH
        #     the att (via _trim) and the influence function (which consumes _trim).
        assert cell["_ps"][ir] >= CS_PS_TRIM, f"{method}: rogue ps {cell['_ps'][ir]} not over threshold"
        assert cell["_trim"][ir] == 0.0, f"{method}: rogue not trimmed"
        # (b) the returned ATT equals the trimmed, IF-consistent value — NOT the
        #     untrimmed estimate that the rogue would otherwise dominate.
        assert abs(cell["att"] - exp_att) < 1e-6, \
            f"{method}: att {cell['att']} != trimmed {exp_att}"
        # reconstruct the att from the SAME trimmed weights the IF uses -> identical.
        D, dY, ps, mhat, tr = (cell["_D"], cell["_dY"], cell["_ps"], cell["_mhat"], cell["_trim"])
        r1 = tr * D; w1 = r1 / r1.mean()
        r0 = tr * ps * (1 - D) / (1 - ps); w0 = r0 / r0.mean()
        recon = float(np.mean((w1 - w0) * (dY - mhat))) if method == "dr" \
            else float(np.mean((w1 - w0) * dY))
        assert abs(cell["att"] - recon) < 1e-12, f"{method}: att not IF-consistent"
        # and the IF is finite / mean-zero with the rogue trimmed out of the weights.
        inf = cell_influence_function(cell, est_method=method)
        assert np.all(np.isfinite(inf)) and abs(inf.mean()) < 1e-8
