"""dCDH (DIDmultiplegtDYN) estimator-core tests — validated element-wise vs the
committed R oracle (tests/fixtures/dcdh/dyn_*.json).

Recipe locked here (see docs/v1.5.9-IMPL-NOTES.md):
  * Effect_l (1-based) <-> event_time l-1; long diff ref=F-1 -> tgt=F+(l-1).
  * Placebo_l (1-based): pre long diff Y[F-1-l]-Y[F-1], control set = the SAME
    never-treated-through-F-1+l set used by Effect_l (control filter at the
    EFFECT horizon, not the placebo period).
  * Control per (F,l) = baseline=0, D=0 for all s<=control-filter-period,
    observed at both ref and tgt.
  * same_switchers=TRUE: switcher set constant (observed at F-1 and all effect
    horizons F..F+L-1) -> 72 switchers across the three effects.
  * SE 命门: within-cell Bessel sqrt(n/(n-1)) on each demeaned subgroup; IF
    summed per unit; _se reconstructs the DYN per-l SE to machine precision.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.engine.dcdh_estimator import (
    estimate_dcdh_dynamic, dcdh_influence)
from workbench.engine.cs_aggregate import _se

FIX = Path(__file__).parent / "fixtures" / "dcdh"


def _norm(name):
    return normalize_treatment_path(
        pd.read_csv(FIX / f"panel_{name}.csv"),
        entity="id", time="year", y="y", treatment="d")


def _oracle(name):
    return json.loads((FIX / f"dyn_{name}.json").read_text())


# graded tol achieved: 1e-12 (machine precision); spec allowed 1e-4 fallback.
SE_TOL = 1e-9
PT_TOL = 1e-6


def test_effect_point_estimates_match_dyn_nonabsorbing():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    orc = _oracle("nonabsorbing")
    assert len(res["effect_estimate"]) == len(orc["effect_estimate"])
    for got, want in zip(res["effect_estimate"], orc["effect_estimate"]):
        assert abs(got - want) < PT_TOL


def test_placebo_point_estimates_match_dyn_nonabsorbing():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    orc = _oracle("nonabsorbing")
    assert len(res["placebo_estimate"]) == len(orc["placebo_estimate"])
    for got, want in zip(res["placebo_estimate"], orc["placebo_estimate"]):
        assert abs(got - want) < PT_TOL


def test_ell0_is_F_minus_1_to_F_definition():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    orc = _oracle("nonabsorbing")
    # Effect_1 == event_time 0 == F-1 -> F long difference.
    assert abs(res["effect_estimate"][0] - orc["effect_estimate"][0]) < PT_TOL


def test_risk_set_recorded_per_ell():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    rs = res["risk_set_by_ell"]
    assert len(rs) == len(res["event_time"])
    for cell in rs:
        assert {"ell", "n_switchers", "n_controls", "dropped_reason"} <= set(cell)
        assert cell["n_switchers"] > 0
    # effect cells (ell >= 0) have constant 72 switchers (same_switchers=TRUE).
    eff_cells = [c for c in rs if c["ell"] >= 0]
    assert eff_cells, "expected at least one effect cell"
    assert all(c["n_switchers"] == 72 for c in eff_cells)


def test_event_time_axis_monotone():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    et = res["event_time"]
    assert et == sorted(et)
    assert any(e < 0 for e in et)   # placebos
    assert any(e >= 0 for e in et)  # effects


def test_if_reconstructs_dyn_per_ell_se_nonabsorbing():
    norm = _norm("nonabsorbing")
    res = estimate_dcdh_dynamic(norm)
    orc = _oracle("nonabsorbing")
    IF, row_cluster, N = dcdh_influence(res)
    et = res["event_time"]
    n_pl = len(res["placebo_estimate"])
    # placebo columns come first (negative event_time, ascending), then effects.
    # Map oracle Placebo_l / Effect_l by index to IF columns.
    assert IF.shape == (N, len(et))
    # effect columns: event_time >= 0 in ascending order == Effect_1..L.
    eff_cols = [k for k, e in enumerate(et) if e >= 0]
    for j, k in enumerate(eff_cols):
        se = _se(IF[:, k], row_cluster, N)
        assert abs(se - orc["effect_se"][j]) < SE_TOL, (j, se, orc["effect_se"][j])
    # placebo columns: event_time < 0, but Placebo_1 is the closest pre period.
    pl_cols = [k for k, e in enumerate(et) if e < 0]
    # ascending event_time => most negative first => Placebo_P..Placebo_1.
    pl_cols_by_l = list(reversed(pl_cols))
    for j, k in enumerate(pl_cols_by_l):
        se = _se(IF[:, k], row_cluster, N)
        assert abs(se - orc["placebo_se"][j]) < SE_TOL, (j, se, orc["placebo_se"][j])
    assert len(eff_cols) == len(orc["effect_se"])
    assert len(pl_cols) == n_pl == len(orc["placebo_se"])


def test_if_columns_mean_zero():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    IF, _, _ = dcdh_influence(res)
    sums = IF.sum(axis=0)
    assert np.allclose(sums, 0.0, atol=1e-6)
