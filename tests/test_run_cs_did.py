import numpy as np, pandas as pd
from workbench.engine.did_spec import normalize_did_input
from workbench.econometrics.runner import run_cs_did

def _norm():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    return normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")

def test_run_cs_did_structure():
    res = run_cs_did(_norm(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var=None, seed=20260615)
    assert set(res) >= {"att_gt", "aggregations", "diagnostics", "warnings", "metadata"}
    assert set(res["aggregations"]) == {"simple", "dynamic", "group", "calendar"}
    # att_gt cell table: one row per cell, with se for valid cells
    assert len(res["att_gt"]) >= 1
    cell = res["att_gt"][0]
    assert {"g","t","event_time","att","se","valid"} <= set(cell)
    # dynamic aggregation carries per-label estimate + uniform band + crit
    dyn = res["aggregations"]["dynamic"]
    assert len(dyn["event_time"]) == len(dyn["estimate"]) == len(dyn["uniform_band"])
    assert dyn["uniform_crit"] >= 1.959
    assert dyn["overall"] is not None and dyn["overall_se"] is not None
    # metadata
    md = res["metadata"]
    assert md["control_group"] == "never" and md["est_method"] == "dr"
    assert md["n_cohorts"] >= 1 and md["seed"] == 20260615

def test_run_cs_did_deterministic():
    a = run_cs_did(_norm(), covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var=None, seed=7)
    b = run_cs_did(_norm(), covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var=None, seed=7)
    assert a["aggregations"]["dynamic"]["uniform_crit"] == b["aggregations"]["dynamic"]["uniform_crit"]

def test_run_cs_did_overall_matches_aggte_point():
    import json
    # aggte.json restructured to {dr,ipw,reg} (hardening round 2 Fix #2); this run is dr.
    ref = json.load(open("tests/fixtures/cs_did/aggte.json"))["dr"]
    res = run_cs_did(_norm(), covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var=None, seed=1)
    assert abs(res["aggregations"]["simple"]["overall"] - ref["simple"]["overall"]) < 1e-6
    assert abs(res["aggregations"]["group"]["overall_se"] - ref["group"]["overall_se"]) < 1e-6
