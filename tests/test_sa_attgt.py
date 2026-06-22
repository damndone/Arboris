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


def test_no_never_treated_blocked():
    # v1.5.8 hardening: a panel with NO never-treated group (every entity eventually
    # treated) is BLOCKED, not silently estimated. The previously-shipped no-never
    # (last-cohort-reference) path diverged structurally from fixest::sunab and emitted
    # UNIDENTIFIED high-event-time coefficients (its Gram-Schmidt collinearity drop never
    # fired). It now fails loud with SA_NO_NEVER_TREATED. See docs/v1.5.8-IMPL-NOTES.md.
    d, _ = _load("balanced")
    dn = d[d["cohort"].notna()].copy()
    with pytest.raises(SASpecError, match="SA_NO_NEVER_TREATED"):
        estimate_sa_saturated(dn, entity="id", time="year", y="y", cohort="cohort")


def test_genuine_collinearity_drop_matches_fixest_balanced():
    # Hardening: make the implicit explicit. The saturated design has cells that are
    # genuinely collinear with the two-way (id+year) FEs (NOT zero-support) — the
    # Gram-Schmidt path (sa_attgt.py) must drop EXACTLY fixest's $collin.var set.
    # This locks the most fragile branch against silent regressions. The expected set
    # is fixest 0.14.1 sunab $collin.var on the committed panel_balanced.csv.
    d, _ = _load("balanced")
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort")
    got = {(float(c["g"]), float(c["e"])) for c in res["collinear_cells"]}
    want = {(3.0, -2.0), (3.0, 2.0), (5.0, 2.0), (3.0, 3.0), (4.0, 3.0), (3.0, 4.0)}
    assert got == want, got ^ want
    # and these collinear cells must be absent from the estimated set
    kept = {(float(g), float(e)) for g, e in zip(res["g"], res["e"])}
    assert not (got & kept)


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


# --- Task 5: EffectEstimateBundle assembly + balanced dynamic oracle -----------
from workbench.engine.cs_attgt import EffectEstimateBundle  # noqa: E402
from workbench.engine.cs_aggregate import aggregate  # noqa: E402
from workbench.engine.did_spec import normalize_did_input  # noqa: E402
from workbench.engine.sa_attgt import estimate_sa  # noqa: E402


def _norm(panel):
    d = pd.read_csv(_FIX / f"panel_{panel}.csv")
    return normalize_did_input(d, mode="cohort", entity="id", time="year", y="y", cohort="cohort")


def test_sa_bundle_is_effectestimatebundle_and_consumable():
    b = estimate_sa(_norm("balanced"), cluster_var=None)
    assert isinstance(b, EffectEstimateBundle)
    assert b.influence_func.shape[0] == b.aux["n_total"]
    assert b.influence_func.shape[1] == len(b.cell_metadata) == len(b.estimates)
    assert all(m["valid"] for m in b.cell_metadata)
    agg = aggregate(b, "dynamic")
    assert len(agg["label"]) > 0


def test_sa_dynamic_matches_fixest_balanced():
    d, o = _load("balanced")
    b = estimate_sa(_norm("balanced"), cluster_var=None)
    agg = aggregate(b, "dynamic")
    got = {float(e): float(v) for e, v in zip(agg["label"], agg["estimate"])}
    want = {float(e): float(v) for e, v in zip(o["agg_e"], o["agg_estimate"])}
    common = set(got) & set(want)
    assert common
    for e in common:
        assert abs(got[e] - want[e]) < 1e-6, (e, got[e], want[e])


def test_sa_bundle_diagnostics_balanced_flag():
    assert estimate_sa(_norm("balanced"), cluster_var=None).diagnostics["balanced"] is True
    assert estimate_sa(_norm("unbalanced"), cluster_var=None).diagnostics["balanced"] is False


def test_sa_unbalanced_dynamic_differs_from_fixest():
    d, o = _load("unbalanced")
    b = estimate_sa(_norm("unbalanced"), cluster_var=None)
    agg = aggregate(b, "dynamic")
    got = {float(e): float(v) for e, v in zip(agg["label"], agg["estimate"])}
    want = {float(e): float(v) for e, v in zip(o["agg_e"], o["agg_estimate"])}
    diffs = [abs(got[e] - want[e]) for e in (set(got) & set(want))]
    assert max(diffs) > 1e-6   # documents the architectural boundary (NOT a bug)


# --- v1.5.8.1 hardening: SA cluster-column guards (mirror cs_attgt) + empty design ---
from workbench.engine.sa_attgt import estimate_sa  # noqa: E402
from workbench.engine.did_spec import normalize_did_input  # noqa: E402


def _norm_frame(d):
    return normalize_did_input(d, mode="cohort", entity="id", time="year", y="y", cohort="cohort")


def test_sa_cluster_col_nan_raises_structured():
    d = pd.read_csv(_FIX / "panel_balanced.csv")
    d["clu"] = (d["id"] % 5 + 1).astype(float)   # ensure >=2 levels among the rest
    d.loc[d["id"] == 1, "clu"] = np.nan           # id 1 exists (ids are 1..120)
    with pytest.raises(SASpecError, match="SA_CLUSTER_COL_NAN"):
        estimate_sa(_norm_frame(d), cluster_var="clu")


def test_sa_cluster_single_level_raises_structured():
    d = pd.read_csv(_FIX / "panel_balanced.csv")
    d["clu"] = 1.0
    with pytest.raises(SASpecError, match="SA_CLUSTER_SINGLE"):
        estimate_sa(_norm_frame(d), cluster_var="clu")


def test_sa_cluster_object_dtype_coerced_not_garbage():
    d = pd.read_csv(_FIX / "panel_balanced.csv")
    d["clu"] = ["c" + str(int(i) % 6) for i in d["id"]]
    b = estimate_sa(_norm_frame(d), cluster_var="clu")
    se = _se(b.influence_func[:, 0], b.aux["row_cluster"], b.aux["n_total"])
    assert np.isfinite(se) and se < 1e6


def test_sa_no_identified_cells_raises_structured():
    # Empty interaction design WITH a never-treated group present (so the v1.5.8
    # SA_NO_NEVER_TREATED guard does NOT fire first): the single treated cohort is
    # observed ONLY at its reference period e=-1, so no identified (g,e) cell survives.
    rows = []
    for i in range(10):  # never-treated: full panel, provides the comparison group
        for yr in range(1, 6):
            rows.append({"id": i, "year": yr, "cohort": np.nan, "y": float(i + yr)})
    for i in range(10, 15):  # treated cohort 4, observed ONLY at year 3 == e=-1
        rows.append({"id": i, "year": 3, "cohort": 4.0, "y": float(i)})
    with pytest.raises(SASpecError, match="SA_NO_IDENTIFIED_CELLS"):
        estimate_sa(_norm_frame(pd.DataFrame(rows)), cluster_var=None)
