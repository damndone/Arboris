"""v1.5.8 QA edge-case coverage for sa_did (Test & QA backstop).

Fills thin spots left by the implementer suite:
  - determinism across two runs (aggregations byte-identical)
  - cluster_var bound to a REAL column (entity-clustered) runs + serializes
  - non-numeric y surfaces a structured error (not a raw crash)
  - honest+UNBALANCED is strict-JSON serializable (only balanced was checked)
  - collinear / no-never-treated still produce a populated dynamic block
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.engine.did_spec import normalize_did_input
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "sa_did"


def _norm(panel):
    d = pd.read_csv(_FIX / f"panel_{panel}.csv")
    return normalize_did_input(
        d, mode="cohort", entity="id", time="year", y="y", cohort="cohort"
    )


def test_sa_did_run_is_deterministic():
    a = runner.run_sa_did(_norm("balanced"), cluster_var=None)
    b = runner.run_sa_did(_norm("balanced"), cluster_var=None)
    assert json.dumps(a["aggregations"], sort_keys=True) == json.dumps(
        b["aggregations"], sort_keys=True
    )


def test_sa_did_cluster_var_real_column_runs_and_serializes():
    # entity 'id' is a valid cluster column; entity-clustered SE must be finite.
    res = runner.run_sa_did(_norm("balanced"), cluster_var="id")
    se = res["aggregations"]["simple"]["overall_se"]
    assert se is not None and np.isfinite(se) and se > 0
    json.dumps(res, allow_nan=False)


def test_sa_did_missing_cluster_column_raises_structured():
    from workbench.engine.sa_spec import SASpecError

    with pytest.raises(SASpecError, match="SA_CLUSTER_COL_MISSING"):
        runner.run_sa_did(_norm("balanced"), cluster_var="not_a_real_column")


def test_sa_did_nonnumeric_y_raises_clean_error():
    d = pd.read_csv(_FIX / "panel_balanced.csv")
    d["y"] = "abc"
    norm = normalize_did_input(
        d, mode="cohort", entity="id", time="year", y="y", cohort="cohort"
    )
    with pytest.raises(ValueError, match="non-numeric"):
        runner.run_sa_did(norm, cluster_var=None)


def test_sa_did_honest_unbalanced_is_strict_json(monkeypatch):
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 120)
    res = runner.run_sa_did(_norm("unbalanced"), cluster_var=None, honest_did=True)
    assert res["honest_did"]["rm"]["status"] == "ok"
    assert res["honest_did"]["sd"]["status"] == "ok"
    json.dumps(res, allow_nan=False)  # must not raise on NaN/inf


@pytest.mark.parametrize("panel", ["collinear"])
def test_sa_did_collinear_dynamic_block_populated(panel):
    res = runner.run_sa_did(_norm(panel), cluster_var=None)
    dyn = res["aggregations"]["dynamic"]
    assert dyn["event_time"] and len(dyn["estimate"]) == len(dyn["event_time"])
    json.dumps(res, allow_nan=False)


def test_sa_did_no_never_treated_dynamic_block_populated():
    d = pd.read_csv(_FIX / "panel_balanced.csv")
    d = d[d["cohort"].notna()].copy()  # drop never-treated -> last-cohort reference
    norm = normalize_did_input(
        d, mode="cohort", entity="id", time="year", y="y", cohort="cohort"
    )
    res = runner.run_sa_did(norm, cluster_var=None)
    dyn = res["aggregations"]["dynamic"]
    assert dyn["event_time"] and len(dyn["estimate"]) == len(dyn["event_time"])
    json.dumps(res, allow_nan=False)
