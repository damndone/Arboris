import numpy as np
import pandas as pd

from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt
from workbench.engine.cs_aggregate import aggregate
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic


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
    assert out["num_pre"] == sum(1 for e in et if e < 0)
    assert out["num_post"] == sum(1 for e in et if e >= 0)
    pre = [e for e in et if e < 0]
    post = [e for e in et if e >= 0]
    assert et == pre + post and pre == sorted(pre) and post == sorted(post)
    if not out["skipped"]:
        assert len(out["per_event_time"]) == out["num_post"]
        assert "results" in out["post_average"] and "breakdown" in out["post_average"]
        for pe in out["per_event_time"]:
            assert "event_time" in pe and "results" in pe and "breakdown" in pe
