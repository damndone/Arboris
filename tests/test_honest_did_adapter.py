import numpy as np
import pandas as pd

from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt
from workbench.engine.cs_aggregate import aggregate
from workbench.engine.honest_did_adapter import (
    honest_did_from_cs_dynamic,
    HONEST_SD_SCALE_FLOOR,
)


def _dyn(cluster_var=None):
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
                               y="y", cohort="first_treat")
    b = estimate_att_gt(norm, control_group="never", est_method="dr",
                        base_period="varying", anticipation=0,
                        covariates=["x1"], cluster_var=cluster_var)
    return aggregate(b, "dynamic"), b


def test_sigma_is_cluster_robust_crve():
    agg, b = _dyn(cluster_var="cluster")
    N = int(b.aux["n_total"])
    rc = b.aux["row_cluster"]
    out = honest_did_from_cs_dynamic(agg, row_cluster=rc, n_total=N,
                                     mbar_grid=[0, 1], alpha=0.05, grid_points=150)
    CIF = np.asarray(agg["component_if"], float)
    S = pd.DataFrame(CIF).groupby(np.asarray(rc)).sum().to_numpy()
    Sigma_full = S.T @ S / (N ** 2)
    keep = out["_debug_keep_idx"]
    max_err = np.max(np.abs(
        np.asarray(out["_debug_sigma"]) - Sigma_full[np.ix_(keep, keep)]))
    assert max_err < 1e-10, max_err


def test_pre_post_mapping():
    agg, b = _dyn()
    out = honest_did_from_cs_dynamic(agg, row_cluster=b.aux["row_cluster"],
                                     n_total=int(b.aux["n_total"]),
                                     mbar_grid=[0, 1], alpha=0.05, grid_points=150)
    et = out["_debug_event_times"]
    assert all(abs(e + 1.0) > 1e-9 for e in et)          # reference e=-1 excluded

    rm = out["rm"]
    assert rm["num_pre"] == sum(1 for e in et if e < 0)
    assert rm["num_post"] == sum(1 for e in et if e >= 0)
    pre = [e for e in et if e < 0]
    post = [e for e in et if e >= 0]
    assert et == pre + post and pre == sorted(pre) and post == sorted(post)
    if rm["status"] == "ok":
        assert len(rm["per_event_time"]) == rm["num_post"]
        assert "results" in rm["post_average"] and "breakdown" in rm["post_average"]
        for pe in rm["per_event_time"]:
            assert "event_time" in pe and "results" in pe and "breakdown" in pe

    # Equivalent assertions for the sd track.
    sd = out["sd"]
    assert sd["num_pre"] == rm["num_pre"]
    assert sd["num_post"] == rm["num_post"]
    if sd["status"] == "ok":
        assert "m_grid" in sd and len(sd["m_grid"]) > 0
        assert "scale" in sd
        assert len(sd["per_event_time"]) == sd["num_post"]
        assert "results" in sd["post_average"] and "breakdown" in sd["post_average"]


def test_adapter_nested_rm_and_sd():
    agg, b = _dyn()
    out = honest_did_from_cs_dynamic(agg, row_cluster=b.aux["row_cluster"],
                                     n_total=int(b.aux["n_total"]),
                                     mbar_grid=[0, 1], alpha=0.05, grid_points=150)
    assert "rm" in out and "sd" in out
    assert out["rm"]["status"] == "ok"
    assert out["sd"]["status"] == "ok"
    assert out["sd"]["method"] == "FLCI"
    # sd post_average rows use the "M" key (not "Mbar")
    for row in out["sd"]["post_average"]["results"]:
        assert "M" in row and "Mbar" not in row
    # frozen snapshot present at top level
    assert "_debug_sigma" in out and "_debug_keep_idx" in out
    assert out["rm"]["num_pre"] == out["sd"]["num_pre"]


def test_adapter_never_throws_on_shape_mismatch():
    agg, b = _dyn()
    rc = b.aux["row_cluster"]
    bad_cif = np.asarray(agg["component_if"], float)[:-1]  # one fewer row than rc
    agg_bad = dict(agg)
    agg_bad["component_if"] = bad_cif.tolist()
    out = honest_did_from_cs_dynamic(agg_bad, row_cluster=rc,
                                     n_total=int(b.aux["n_total"]),
                                     mbar_grid=[0, 1], alpha=0.05, grid_points=150)
    assert out["rm"]["status"] == "not_available"
    assert out["sd"]["status"] == "not_available"


def test_adapter_sd_scale_clamped():
    # Construct a minimal agg with a tiny IF so Σ falls below the scale floor.
    tiny = 1e-12
    agg = {
        "label": [-1.0, 0.0, 1.0],
        "estimate": [0.0, tiny, tiny],
        "component_if": [
            [0.0, tiny, tiny],
            [0.0, -tiny, -tiny],
        ],
    }
    rc = [0, 1]
    out = honest_did_from_cs_dynamic(agg, row_cluster=rc, n_total=2,
                                     mbar_grid=[0, 1], alpha=0.05, grid_points=150)
    assert out["sd"]["scale"] >= HONEST_SD_SCALE_FLOOR
