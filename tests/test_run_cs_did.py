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


def _norm_cluster():
    import pandas as pd
    from workbench.engine.did_spec import normalize_did_input
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    return normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")


def test_run_cs_did_clustered_metadata():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var="cluster", seed=20260615)
    m = res["metadata"]
    assert m["n_units"] == 60          # entities, never overwritten
    assert m["n_clusters"] == 20
    assert m["cluster_level"] == "cluster"


def test_run_cs_did_entity_metadata():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var=None, seed=20260615)
    m = res["metadata"]
    assert m["n_units"] == 60 and m["n_clusters"] == 60
    assert m["cluster_level"] == "entity"


def test_run_cs_did_clustered_bands_differ_from_unclustered():
    # passing clusters must actually change the bands (cluster-robust != entity)
    rc = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var="cluster", seed=1)
    ru = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var=None, seed=1)
    dc = rc["aggregations"]["dynamic"]
    du = ru["aggregations"]["dynamic"]
    # point estimates identical, SE/bands different
    assert abs(dc["overall"] - du["overall"]) < 1e-12
    assert abs(dc["overall_se"] - du["overall_se"]) > 1e-4
    assert dc["overall_uniform_band"] is not None
    assert len(dc["uniform_band"]) == len(dc["estimate"])


def test_run_cs_did_honest_did_block_present(monkeypatch):
    import workbench.econometrics.runner as runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 150)
    res = runner.run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0, cluster_var="cluster",
        seed=20260615, honest_did=True)
    h = res["honest_did"]
    rm = h["rm"]
    assert rm["status"] == "ok"
    assert "post_average" in rm and "results" in rm["post_average"]
    assert len(rm["per_event_time"]) == rm["num_post"]
    # sd (ΔSD/FLCI) track runs on the same snapshot
    sd = h["sd"]
    assert sd["status"] in ("ok", "not_available")
    if sd["status"] == "ok":
        assert sd["method"] == "FLCI"
        assert "results" in sd["post_average"]
        assert sd["post_average"]["results"][0].get("M") is not None
    assert not any(k.startswith("_debug_") for k in h)        # debug keys stripped (top level)
    assert not any(k.startswith("_debug_") for k in rm)       # and not in tracks
    assert not any(k.startswith("_debug_") for k in sd)


def test_run_cs_did_honest_did_absent_by_default():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0, cluster_var=None, seed=20260615)
    assert "honest_did" not in res
