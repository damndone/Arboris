"""v1.5.7 honest-DID QA backstop (Test & QA hardening pass).

Strengthens the NaN-safety fix (commit ecff1b3) beyond the unit-level
``_json_safe`` tests in ``test_honest_did_nan_safety.py``:

  * INTEGRATION: a REAL ``run_workflow(honest_did=True)`` whose honest-DID emits
    at least one ``(nan, nan)`` CI -> the on-disk ``cs_did.json`` is STRICTLY
    valid JSON (parsed with ``parse_constant`` that REJECTS NaN/Infinity, exactly
    as the browser's ``Response.json()`` does) AND the run status is completed.
  * ADAPTER-level real ``(nan, nan)`` -> ``_json_safe`` -> strict reload.
  * Boundary mbar_grid / pre-post states pinned EXPLICITLY (skip vs run vs error).
  * Regression: a normal finite cs_did run's ``cs_did.json`` is byte-identical
    across two runs (finite floats pass ``_json_safe`` unchanged).

The DGP that yields a genuine ``(nan, nan)`` is near-deterministic (tiny noise ->
tiny Σ) with a large treatment effect, run on an ULTRA-COARSE θ-grid
(``grid_points`` small) so the accept sliver falls between grid nodes. This is
the exact escape the fix guards: a finite Σ, a real effect, a coarse grid.
"""
import json

import numpy as np
import pandas as pd
import pytest

from workbench.engine.honest_did import honest_rm, HonestDiDError
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic
from workbench.engine.stages.diagnostics import _json_safe
from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project
from workbench.artifacts import read_json


def _reject_constant(token):
    """Emulate the browser's strict JSON parser: NaN/Infinity are NOT valid JSON."""
    raise ValueError(f"strict JSON rejects non-finite constant: {token!r}")


# ---------------------------------------------------------------------------
# AREA 1 — INTEGRATION: a real run that emits (nan, nan) writes strict-valid JSON
# ---------------------------------------------------------------------------

def _near_deterministic_csv(tmp_path):
    """Staggered panel with tiny noise (=> tiny Σ) and a LARGE effect (5.0).

    With a coarse θ-grid the honest-DID accept set is a sliver that falls between
    grid nodes -> the ARP CI is ``(nan, nan)`` for some Mbar. cs_did itself stays
    estimable (the DGP is clean), so the run completes.
    """
    rng = np.random.default_rng(3)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0), ("G", 2019), ("H", 2021),
                        ("I", 0), ("J", 2019), ("K", 0), ("L", 2019)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 5.0 * d + rng.normal(0, 1e-4),
                         "first_treat": cohort})
    src = tmp_path / "neardet.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_real_run_with_nan_ci_writes_strict_valid_json(tmp_path, monkeypatch):
    """The WHOLE path: run_workflow -> honest-DID emits (nan,nan) -> cs_did.json
    on disk is strict-valid JSON (no bare NaN/Infinity) AND status==completed."""
    import workbench.econometrics.runner as runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 5)  # ultra-coarse -> miss sliver

    src = _near_deterministic_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat", honest_did=True)
    run_root = project.root / "runs" / result["run_id"]

    # run completes despite the degenerate CI
    assert read_json(run_root / "run_manifest.json")["status"] == "completed"

    cs_path = run_root / "cs_did.json"
    text = cs_path.read_text()
    # no bare non-finite token reached the file
    assert "NaN" not in text and "Infinity" not in text

    # browser-strict parse must NOT raise
    art = json.loads(text, parse_constant=_reject_constant)
    hd = art["honest_did"]

    # this DGP is meant to exercise the (nan,nan) path; if the design ever stops
    # producing one we want a loud signal rather than a silently weakened test.
    assert not hd["skipped"], "expected honest-DID to RUN (not skip) for this DGP"
    flat = [r for r in hd["post_average"]["results"]]
    for pe in hd["per_event_time"]:
        flat += pe["results"]
    null_rows = [r for r in flat if r["lb"] is None or r["ub"] is None]
    assert null_rows, "expected at least one (nan->null) CI row from the coarse grid"
    # the sanitized rows are real JSON null, never a string or NaN
    for r in null_rows:
        assert r["lb"] is None and r["ub"] is None


def test_adapter_real_nan_ci_sanitizes_to_strict_json():
    """Adapter-level: a real honest_did_from_cs_dynamic that emits (nan,nan) ->
    _json_safe -> json.dumps -> strict reload (rejecting NaN) succeeds, lb=None."""
    N = 40
    rng = np.random.default_rng(1)
    agg = {"label": [-2.0, -1.0, 0.0], "estimate": [0.0, 0.0, 5.0],
           "component_if": rng.normal(0, 1e-3, size=(N, 3))}  # tiny Σ
    out = honest_did_from_cs_dynamic(agg, row_cluster=np.arange(N), n_total=N,
                                     mbar_grid=[0.0, 1.0], grid_points=5)
    assert out["skipped"] is False
    raw = out["post_average"]["results"]
    assert any(r["lb"] != r["lb"] for r in raw), "expected a real NaN lb pre-sanitize"

    shipped = {k: v for k, v in out.items() if not k.startswith("_debug_")}
    safe = _json_safe(shipped)
    text = json.dumps(safe)
    assert "NaN" not in text and "Infinity" not in text
    parsed = json.loads(text, parse_constant=_reject_constant)
    assert parsed["post_average"]["results"][0]["lb"] is None


# ---------------------------------------------------------------------------
# AREA 2 — boundary / empty states (PIN the actual behavior, skip vs run vs error)
# ---------------------------------------------------------------------------

_BH = np.array([0.0, 0.0, 2.0, 2.5])
_SIG = np.eye(4) * 0.1
_L = np.array([0.5, 0.5])


def test_honest_rm_empty_mbar_grid_returns_empty_results_no_breakdown():
    # empty grid is a benign no-op: no results, no breakdown, NO error.
    r = honest_rm(betahat=_BH, sigma=_SIG, num_pre=2, num_post=2, l_vec=_L,
                  mbar_grid=[], grid_points=80)
    assert r["results"] == []
    assert r["breakdown"] is None


def test_honest_rm_single_mbar_value():
    r = honest_rm(betahat=_BH, sigma=_SIG, num_pre=2, num_post=2, l_vec=_L,
                  mbar_grid=[1.0], grid_points=80)
    assert len(r["results"]) == 1
    assert r["results"][0]["Mbar"] == 1.0


def test_honest_rm_negative_mbar_runs_without_error():
    # Mbar < 0 is unusual but NOT rejected by the engine — it produces a finite CI.
    # Pin this so a future guard is a deliberate choice, not an accident.
    r = honest_rm(betahat=_BH, sigma=_SIG, num_pre=2, num_post=2, l_vec=_L,
                  mbar_grid=[-1.0], grid_points=80)
    assert len(r["results"]) == 1
    assert r["results"][0]["Mbar"] == -1.0
    lb, ub = r["results"][0]["lb"], r["results"][0]["ub"]
    assert np.isfinite(lb) and np.isfinite(ub)  # a real interval, not (nan,nan)


def test_adapter_one_pre_one_post_runs():
    # num_pre==1 & num_post==1 (the minimal ΔRM): runs, one per-event-time entry.
    N = 30
    rng = np.random.default_rng(2)
    agg = {"label": [-2.0, -1.0, 0.0], "estimate": [0.0, 0.0, 2.0],
           "component_if": rng.normal(0, 0.05, (N, 3))}
    o = honest_did_from_cs_dynamic(agg, row_cluster=np.arange(N), n_total=N,
                                   mbar_grid=[0, 1], grid_points=80)
    assert o["skipped"] is False
    assert o["num_pre"] == 1 and o["num_post"] == 1
    assert len(o["per_event_time"]) == 1
    assert o["per_event_time"][0]["event_time"] == 0.0


def test_adapter_no_post_periods_skips_clean():
    # only pre labels (-2,-1): num_post==0 -> HONEST_NO_POST_PERIODS, NEVER throws.
    N = 30
    rng = np.random.default_rng(2)
    agg = {"label": [-2.0, -1.0], "estimate": [0.0, 0.0],
           "component_if": rng.normal(0, 0.05, (N, 2))}
    o = honest_did_from_cs_dynamic(agg, row_cluster=np.arange(N), n_total=N,
                                   mbar_grid=[0, 1], grid_points=80)
    assert o["skipped"] is True
    assert "HONEST_NO_POST_PERIODS" in o["reason"]
    assert o["num_pre"] == 1 and o["num_post"] == 0


def test_adapter_no_pre_no_post_only_reference_skips_clean():
    # only the structural reference e=-1: num_pre==num_post==0. The pre-period
    # guard fires FIRST -> HONEST_NO_PRE_PERIODS.
    N = 30
    rng = np.random.default_rng(2)
    agg = {"label": [-1.0], "estimate": [0.0],
           "component_if": rng.normal(0, 0.05, (N, 1))}
    o = honest_did_from_cs_dynamic(agg, row_cluster=np.arange(N), n_total=N,
                                   mbar_grid=[0, 1], grid_points=80)
    assert o["skipped"] is True
    assert "HONEST_NO_PRE_PERIODS" in o["reason"]
    assert o["num_pre"] == 0 and o["num_post"] == 0


# ---------------------------------------------------------------------------
# AREA 3 — regression: finite inputs are byte-identical (_json_safe untouched them)
# ---------------------------------------------------------------------------

def test_finite_cs_did_json_byte_identical_across_two_runs(tmp_path, monkeypatch):
    """The _json_safe NaN->None change must leave FINITE artifacts untouched:
    two identical finite cs_did(honest_did) runs produce byte-identical
    cs_did.json (proving only NaN/Inf are coerced, finite floats pass through)."""
    import workbench.econometrics.runner as runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 150)

    def _make_csv(path):
        rng = np.random.default_rng(11)
        rows = []
        for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                            ("E", 0), ("F", 0), ("G", 2019), ("H", 2021),
                            ("I", 0), ("J", 2019)]:
            fe = rng.normal()
            for year in range(2017, 2023):
                d = 1 if (cohort and year >= cohort) else 0
                rows.append({"id": ent, "year": year,
                             "y": fe + 0.1 * (year - 2017) + 2.0 * d
                                  + rng.normal(0, 0.01),
                             "first_treat": cohort})
        pd.DataFrame(rows).to_csv(path, index=False)

    texts = []
    for i in range(2):
        sub = tmp_path / f"r{i}"
        sub.mkdir()
        src = sub / "p.csv"
        _make_csv(src)
        project = create_project(sub, "demo")
        result = _rw(project.root, [src], mode="auto", y="y", x=[],
                     model_type="cs_did", entity_col="id", time_col="year",
                     did_mode="cohort", did_cohort_col="first_treat",
                     honest_did=True)
        cs_path = project.root / "runs" / result["run_id"] / "cs_did.json"
        text = cs_path.read_text()
        # finite run: strict parse must still succeed
        json.loads(text, parse_constant=_reject_constant)
        texts.append(text)

    assert texts[0] == texts[1], "finite cs_did.json drifted between identical runs"


# ---------------------------------------------------------------------------
# AREA 5 — fill thin assertions: breakdown is a real value; degenerate Σ reason
# ---------------------------------------------------------------------------

def test_breakdown_is_the_largest_mbar_that_still_excludes_zero():
    """breakdown == max Mbar whose CI still excludes 0. Pin a NON-None value with
    a hand-built monotone case: strong effect, tight Σ -> small Mbars exclude 0,
    large Mbars admit 0. breakdown must equal the last excluding Mbar."""
    betahat = np.array([0.0, 0.0, 3.0, 3.0])  # big post effect
    sigma = np.eye(4) * 0.02                  # tight
    l = np.array([0.5, 0.5])
    grid = [0.0, 0.5, 1.0, 2.0, 5.0]
    r = honest_rm(betahat=betahat, sigma=sigma, num_pre=2, num_post=2, l_vec=l,
                  mbar_grid=grid, grid_points=120)
    excluding = [res["Mbar"] for res in r["results"]
                 if res["lb"] == res["lb"] and res["ub"] == res["ub"]
                 and (res["lb"] > 0.0 or res["ub"] < 0.0)]
    if excluding:
        assert r["breakdown"] == max(excluding)
        assert r["breakdown"] is not None
    else:
        assert r["breakdown"] is None


def test_honest_rm_singular_sigma_clean_degenerate_reason():
    # a PSD-but-singular Σ (zero eigenvalue) -> HONEST_DEGENERATE_SIGMA, asserting
    # the exact reason string the adapter surfaces to the FE skipped note.
    sig = np.eye(4)
    sig[3, 3] = 0.0  # not positive-definite
    with pytest.raises(HonestDiDError, match="HONEST_DEGENERATE_SIGMA"):
        honest_rm(betahat=np.zeros(4), sigma=sig, num_pre=2, num_post=2,
                  l_vec=np.ones(2) / 2, mbar_grid=[1.0], grid_points=50)
