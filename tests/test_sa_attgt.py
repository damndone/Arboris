import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.engine.cs_aggregate import _se
from workbench.engine.sa_attgt import estimate_sa_saturated, sa_influence
from workbench.engine.sa_spec import SASpecError

_FIX = Path(__file__).parent / "fixtures" / "sa_did"


def _load(p):
    d = pd.read_csv(_FIX / f"panel_{p}.csv")
    o = json.loads((_FIX / f"sunab_{p}.json").read_text())
    return d, o


def _check_coef(panel):
    d, o = _load(panel)
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort")
    got = {(float(g), float(e)): float(b) for g, e, b in zip(res["g"], res["e"], res["beta"])}
    want = {(float(g), float(e)): float(b) for g, e, b in zip(o["coef_g"], o["coef_e"], o["coef"])}
    assert set(got) == set(want), set(got) ^ set(want)
    for k in want:
        assert abs(got[k] - want[k]) < 1e-8, (k, got[k], want[k])


def test_balanced():
    _check_coef("balanced")


def test_unbalanced():
    _check_coef("unbalanced")


def test_collinear():
    _check_coef("collinear")
    d, o = _load("collinear")
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort")
    # cohort 4 @ e=0 has zero support -> absent from beta, present in dropped_cells
    assert (4.0, 0.0) not in {(float(g), float(e)) for g, e in zip(res["g"], res["e"])}
    assert {"g": 4.0, "e": 0.0} in [
        {"g": float(c["g"]), "e": float(c["e"])} for c in res["dropped_cells"]
    ]


def test_return_order_sorted_ge():
    d, _ = _load("balanced")
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort")
    keys = list(zip(res["g"], res["e"]))
    assert keys == sorted(keys), keys


def test_internals_shapes():
    d, _ = _load("balanced")
    res = estimate_sa_saturated(
        d, entity="id", time="year", y="y", cohort="cohort", _return_internals=True
    )
    it = res["_internals"]
    K = len(it["kept_keys"])
    n = it["Dk"].shape[0]
    assert it["Dk"].shape == (n, K)
    assert it["y_abs"].shape == (n,)
    assert it["beta_kept"].shape == (K,)
    assert len(it["ent_codes"]) == n
    assert it["N_all"] == 120
    assert len(it["all_entity_ids"]) == 120
    # treated entities only (never-treated excluded from design rows)
    assert len(it["treated_entity_ids"]) < 120
    assert set(it["ent_codes"]) == set(range(len(it["treated_entity_ids"])))


def test_has_never_and_ref_cohort():
    d, _ = _load("balanced")
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort")
    assert res["has_never"] is True
    assert res["ref_cohort"] is None


def test_no_never_treated_uses_last_cohort_ref():
    # Drop never-treated rows -> last-treated cohort (5) becomes the reference.
    d, _ = _load("balanced")
    dn = d[d["cohort"].notna()].copy()
    res = estimate_sa_saturated(dn, entity="id", time="year", y="y", cohort="cohort")
    assert res["has_never"] is False
    assert res["ref_cohort"] == 5.0
    assert 5.0 not in {float(g) for g in res["g"]}  # reference cohort excluded
    assert len(res["beta"]) > 0


def test_too_few_periods_raises():
    d, _ = _load("balanced")
    d1 = d[d["year"] == 1]
    with pytest.raises(SASpecError):
        estimate_sa_saturated(d1, entity="id", time="year", y="y", cohort="cohort")


def test_no_treated_cohort_raises():
    d, _ = _load("balanced")
    d2 = d.copy()
    d2["cohort"] = np.nan
    with pytest.raises(SASpecError):
        estimate_sa_saturated(d2, entity="id", time="year", y="y", cohort="cohort")


# --- Task 4: SA influence function (命门) ---------------------------------------
# The N_all-scaled entity IF must reconstruct fixest's BARE cluster vcov to 1e-6,
# both the diagonal (via cs_aggregate._se) and the FULL matrix (off-diagonals,
# which honest-DID's Sigma needs). Per-(g,e) vcov is exact regardless of panel
# balance, so this holds on BOTH balanced and unbalanced fixtures.


def _check_if_vcov(panel):
    d, o = _load(panel)
    res = estimate_sa_saturated(
        d, entity="id", time="year", y="y", cohort="cohort", _return_internals=True
    )
    IF = sa_influence(res)
    N = res["_internals"]["N_all"]
    assert IF.shape == (N, len(res["g"]))
    rc = np.arange(N)  # entity-clustered == identity (each entity its own cluster)

    # diagonal: reconstructed se^2 == fixest bare cluster vcov diagonal, join on key
    Vdiag = {
        (float(g), float(e)): float(v)
        for g, e, v in zip(o["vcov_g"], o["vcov_e"], np.diag(np.asarray(o["vcov"])))
    }
    for k, (g, e) in enumerate(zip(res["g"], res["e"])):
        se = _se(IF[:, k], rc, N)
        assert abs(se * se - Vdiag[(float(g), float(e))]) < 1e-6, (g, e)

    # FULL matrix (off-diagonals too): V_kl = (IF_k · IF_l) / N^2
    Vfull = np.asarray(o["vcov"])
    okeys = list(zip(o["vcov_g"], o["vcov_e"]))
    oidx = {(float(g), float(e)): i for i, (g, e) in enumerate(okeys)}
    for k, kk in enumerate(zip(res["g"], res["e"])):
        for l, ll in enumerate(zip(res["g"], res["e"])):
            got = (IF[:, k] @ IF[:, l]) / (N * N)
            want = Vfull[
                oidx[(float(kk[0]), float(kk[1]))], oidx[(float(ll[0]), float(ll[1]))]
            ]
            assert abs(got - want) < 1e-6, (kk, ll, got, want)


def test_if_reconstructs_bare_vcov_balanced():
    _check_if_vcov("balanced")


def test_if_reconstructs_bare_vcov_unbalanced():
    _check_if_vcov("unbalanced")


def test_if_mean_zero_and_never_treated_zero():
    d, _ = _load("balanced")
    res = estimate_sa_saturated(
        d, entity="id", time="year", y="y", cohort="cohort", _return_internals=True
    )
    IF = sa_influence(res)
    # mean-zero columns (OLS normal equations)
    col_sums = IF.sum(axis=0)
    assert np.max(np.abs(col_sums)) < 1e-6, col_sums

    # never-treated entities (cohort NaN) have all-zero IF rows.
    never_ids = np.unique(d.loc[d["cohort"].isna(), "id"].to_numpy())
    assert never_ids.size > 0
    all_ids = res["_internals"]["all_entity_ids"]
    pos = {eid: i for i, eid in enumerate(all_ids)}
    for eid in never_ids:
        assert np.all(IF[pos[eid], :] == 0.0), eid
