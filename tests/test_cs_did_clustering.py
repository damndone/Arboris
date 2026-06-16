import json
import numpy as np
import pandas as pd
import pytest

CLUSTERED = json.load(open("tests/fixtures/cs_did/aggte_clustered.json"))
UNCLUSTERED = json.load(open("tests/fixtures/cs_did/aggte.json"))


def test_clustered_oracle_present_and_differs():
    for m in ("dr", "ipw", "reg"):
        assert CLUSTERED[m]["n"] == 60 and CLUSTERED[m]["n_clusters"] == 20
        c = CLUSTERED[m]["dynamic"]["overall_se"]
        u = UNCLUSTERED[m]["dynamic"]["overall_se"]
        assert c is not None and abs(c - u) > 1e-6  # clustering changed the SE


from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt
from workbench.engine.cs_aggregate import aggregate


def _bundle_clustered(method):
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    return estimate_att_gt(norm, control_group="never", est_method=method,
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var="cluster")


@pytest.mark.parametrize("method", ["dr", "ipw", "reg"])
def test_clustered_se_matches_R_crve(method):
    ref = CLUSTERED[method]
    b = _bundle_clustered(method)
    out = aggregate(b, "dynamic")
    if ref["dynamic"]["overall_se"] is not None:
        assert abs(out["overall_se"] - ref["dynamic"]["overall_se"]) < 1e-8
    if ref["dynamic"]["se_egt"] is not None:
        our = {lab: se for lab, se in zip(out["label"], out["se"])}
        for e, se_r in zip(ref["dynamic"]["egt"], ref["dynamic"]["se_egt"]):
            assert abs(our[float(e)] - se_r) < 1e-8, f"e={e} ours={our[float(e)]} R={se_r}"


@pytest.mark.parametrize("kind", ["simple", "group", "calendar"])
def test_clustered_overall_se_matches_R(kind):
    ref = CLUSTERED["dr"][kind]
    b = _bundle_clustered("dr")
    out = aggregate(b, kind)
    if ref["overall_se"] is not None:
        assert abs(out["overall_se"] - ref["overall_se"]) < 1e-8


def test_point_estimates_cluster_invariant():
    bu = _bundle_clustered("dr")                       # clustered
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    bc = estimate_att_gt(norm, control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    assert np.allclose(np.nan_to_num(bu.estimates), np.nan_to_num(bc.estimates), atol=1e-12)
    for kind in ("simple", "dynamic", "group", "calendar"):
        ou, oc = aggregate(bu, kind), aggregate(bc, kind)
        if ou["overall"] is not None:
            assert abs(ou["overall"] - oc["overall"]) < 1e-12
