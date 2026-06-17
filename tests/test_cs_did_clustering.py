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


# --- v1.5.6.1 hardening: characterization of str-coercion edge behavior (I2 fix). ---
# These document CURRENT, correct-but-surprising behavior so a future change to the
# `cl.to_numpy().astype(str)` coercion can't silently alter the cluster partition.

def _df():
    return pd.read_csv("tests/fixtures/cs_did/panel.csv")

def _norm(d):
    return normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")

def _est(d, **kw):
    return estimate_att_gt(_norm(d), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"],
        cluster_var=kw.get("cluster_var", "cluster"))


def test_cluster_partition_invariant_to_int_vs_float_dtype():
    """int cluster col and the same col as float must yield the SAME partition and
    a byte-identical clustered SE (only the string id labels differ '0' vs '0.0')."""
    di = _df()
    df = _df(); df["cluster"] = df["cluster"].astype(float)
    bi, bf = _est(di), _est(df)
    ri, rf = bi.aux["row_cluster"], bf.aux["row_cluster"]
    # same partition (grouping equivalence), even though labels differ
    _, invi = np.unique(ri, return_inverse=True)
    _, invf = np.unique(rf, return_inverse=True)
    assert np.array_equal(invi, invf)
    si = aggregate(bi, "dynamic")["overall_se"]
    sf = aggregate(bf, "dynamic")["overall_se"]
    assert si == sf  # exact byte-identity, not just close


def test_signed_zero_floats_do_not_collide_after_str_coercion():
    """CHARACTERIZATION: numerically-equal 0.0 and -0.0 str-coerce to '0.0' vs '-0.0'
    and therefore form DISTINCT clusters. Unlikely in practice; documented so the
    behavior is intentional, not an accident, if coercion ever changes."""
    d = _df()
    d["cluster"] = d["cluster"].astype(float)
    units = sorted(d.unit.unique())
    d.loc[d.unit.isin(units[:6]), "cluster"] = 0.0
    d.loc[d.unit.isin(units[6:12]), "cluster"] = -0.0
    b = _est(d)
    ids = set(np.unique(b.aux["row_cluster"]).tolist())
    assert "0.0" in ids and "-0.0" in ids   # two separate cluster ids


def test_empty_string_cluster_values_form_their_own_cluster():
    """Empty-string and whitespace cluster values are valid distinct ids (not NaN):
    they str-coerce to '' / '   ' and estimate without escaping to a bare error."""
    d = _df()
    d["cluster"] = d["cluster"].astype(str)
    units = sorted(d.unit.unique())
    d.loc[d.unit.isin(units[:6]), "cluster"] = ""
    b = _est(d)
    out = aggregate(b, "dynamic")
    assert "" in set(np.unique(b.aux["row_cluster"]).tolist())
    assert out["overall_se"] is not None and np.isfinite(out["overall_se"])


# --- I3: cluster-robust per-cell att_gt SE (validated vs R per-cell CRVE oracle) ---

def _run_clustered(method):
    import pandas as pd
    from workbench.engine.did_spec import normalize_did_input
    from workbench.econometrics.runner import run_cs_did
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    return run_cs_did(norm, covariates=["x1"], control_group="never", est_method=method,
        base_period="varying", anticipation=0, cluster_var="cluster", seed=20260615)


@pytest.mark.parametrize("method", ["dr", "ipw", "reg"])
def test_clustered_per_cell_se_matches_R(method):
    ref = CLUSTERED[method]["att_gt"]            # {group:[...], t:[...], se:[...]}
    res = _run_clustered(method)
    ours = {(round(float(g),6), round(float(t),6)): c["se"]
            for c in res["att_gt"] if c["valid"]
            for g, t in [(c["g"], c["t"])]}
    n_checked = 0
    for g, t, se_r in zip(ref["group"], ref["t"], ref["se"]):
        key = (round(float(g),6), round(float(t),6))
        if key in ours and ours[key] is not None:
            assert abs(ours[key] - se_r) < 1e-8, f"(g={g},t={t}) ours={ours[key]} R={se_r}"
            n_checked += 1
    assert n_checked >= 3        # actually compared a meaningful number of cells


def test_clustered_per_cell_se_differs_from_unclustered():
    import pandas as pd
    from workbench.engine.did_spec import normalize_did_input
    from workbench.econometrics.runner import run_cs_did
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    rc = run_cs_did(norm, covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var="cluster", seed=1)
    ru = run_cs_did(norm, covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var=None, seed=1)
    cse = {(c["g"], c["t"]): c["se"] for c in rc["att_gt"] if c["valid"]}
    use = {(c["g"], c["t"]): c["se"] for c in ru["att_gt"] if c["valid"]}
    # at least one cell's SE moved under clustering (point estimates identical)
    assert any(abs(cse[k] - use[k]) > 1e-4 for k in cse)
    ca = {(c["g"], c["t"]): c["att"] for c in rc["att_gt"] if c["valid"]}
    ua = {(c["g"], c["t"]): c["att"] for c in ru["att_gt"] if c["valid"]}
    assert all(abs(ca[k] - ua[k]) < 1e-12 for k in ca)   # points unchanged
