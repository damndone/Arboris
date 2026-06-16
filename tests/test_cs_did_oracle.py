import json, numpy as np, pandas as pd, pytest
from workbench.engine.cs_attgt import att_gt_cell, base_period_for

ORACLE = json.load(open("tests/fixtures/cs_did/att_gt.json"))

def _panel():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    d = d.copy(); d["_did_cohort"] = d["unit"].map(cohort)
    return d

@pytest.mark.parametrize("method,control", [("dr","never"),("ipw","never"),
    ("reg","never"),("dr","not_yet")])
def test_attgt_matches_R_did(method, control):
    key = {"never":"nevertreated","not_yet":"notyettreated"}[control]
    ref = ORACLE[f"{method}_{key}"]
    panel = _panel()
    for g, t, att in zip(ref["group"], ref["t"], ref["att"]):
        base = base_period_for(g=float(g), t=float(t), base_period="varying", anticipation=0)
        ours = att_gt_cell(frame=panel, entity="unit", time="period", y="y",
            g=float(g), t=float(t), base_t=float(base), control_group=control,
            anticipation=0, covariates=["x1"], est_method=method)["att"]
        assert abs(ours - att) < 1e-6, f"(g={g},t={t}) ours={ours} R={att}"

from workbench.engine.cs_attgt import cell_influence_function

@pytest.mark.parametrize("method", ["dr", "ipw", "reg"])
def test_cell_influence_function_matches_DRDID(method):
    ref = json.load(open("tests/fixtures/cs_did/drdid_inffunc.json"))
    panel = _panel()   # helper already defined in this file (attaches _did_cohort)
    cell = att_gt_cell(frame=panel, entity="unit", time="period", y="y",
        g=4.0, t=4.0, base_t=3.0, control_group="never", anticipation=0,
        covariates=["x1"], est_method=method)
    inf = cell_influence_function(cell, est_method=method)
    # align ours (cell["_units"]) to the R unit order
    pos = {u: i for i, u in enumerate(cell["_units"])}
    ours = np.array([inf[pos[u]] for u in ref["unit"]])
    assert np.allclose(ours, ref[method]["inf_func"], atol=1e-8), \
        f"{method} max dev {np.max(np.abs(ours - np.array(ref[method]['inf_func'])))}"


# aggte.json is structured by est_method: {"dr": {...}, "ipw": {...}, "reg": {...}}
# (v1.5.6 hardening round 2, Fix #2 — ipw/reg SE machinery frozen vs R too).
def _bundle_never(est_method):
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    from workbench.engine.did_spec import normalize_did_input
    from workbench.engine.cs_attgt import estimate_att_gt
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    return estimate_att_gt(norm, control_group="never", est_method=est_method,
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)

def test_aggregations_match_R_aggte_pointwise():
    from workbench.engine.cs_aggregate import aggregate
    ref = json.load(open("tests/fixtures/cs_did/aggte.json"))["dr"]
    b = _bundle_never("dr")
    # overall for every aggregation type
    for kind in ("simple", "dynamic", "group", "calendar"):
        out = aggregate(b, kind)
        if ref[kind]["overall"] is not None:
            assert abs(out["overall"] - ref[kind]["overall"]) < 1e-6, \
                f"{kind} overall ours={out['overall']} R={ref[kind]['overall']}"
    # per-label estimates for dynamic / group / calendar
    for kind in ("dynamic", "group", "calendar"):
        out = aggregate(b, kind)
        labels = list(map(float, ref[kind]["egt"]))
        for lab, att in zip(labels, ref[kind]["att_egt"]):
            i = [round(x, 9) for x in out["label"]].index(round(lab, 9))
            assert abs(out["estimate"][i] - att) < 1e-6, \
                f"{kind} label={lab} ours={out['estimate'][i]} R={att}"

@pytest.mark.parametrize("est_method", ["dr", "ipw", "reg"])
def test_aggregation_se_matches_R_aggte(est_method):
    """Freeze the shared wif/_agg_inf_func/_se aggregation-SE machinery against R for
    ALL three est_methods. The dr aggte was already oracle'd; ipw/reg close the
    regression-protection hole (a future _wif/_se refactor can't silently break them)."""
    from workbench.engine.cs_aggregate import aggregate
    ref = json.load(open("tests/fixtures/cs_did/aggte.json"))[est_method]
    b = _bundle_never(est_method)
    for kind in ("simple", "dynamic", "group", "calendar"):
        out = aggregate(b, kind)
        if ref[kind]["overall_se"] is not None:
            assert abs(out["overall_se"] - ref[kind]["overall_se"]) < 1e-6, \
                f"{est_method} {kind} overall_se ours={out['overall_se']} R={ref[kind]['overall_se']}"
    for kind in ("dynamic", "group", "calendar"):
        out = aggregate(b, kind)
        labels = list(map(float, ref[kind]["egt"]))
        for lab, se in zip(labels, ref[kind]["se_egt"]):
            i = [round(x, 9) for x in out["label"]].index(round(lab, 9))
            assert abs(out["se"][i] - se) < 1e-6, \
                f"{est_method} {kind} label={lab} ours={out['se'][i]} R={se}"
