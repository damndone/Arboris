import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.engine.sa_attgt import estimate_sa_saturated
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
