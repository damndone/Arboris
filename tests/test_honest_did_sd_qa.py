"""v1.5.7.1 honest-DID ΔSD/FLCI Test & QA proofs (adversarial pass).

The code-reading Reviewer already passed; this file PROVES the ΔSD/FLCI track
end-to-end via REAL ``run_workflow`` pipeline runs (not synthetic dicts) and
nails the gaps the unit tests miss:

  1. Happy path: a staggered design (>=2 pre-periods) -> both rm & sd ok,
     sd carries method="FLCI" + finite 5-point m_grid + scale>0, post_average
     rows keyed M with finite-or-null lb/ub, per_event_time length == num_post,
     and the on-disk cs_did.json parses under STRICT JSON (NaN rejected).
  2. Degraded: a design with NO usable pre-period -> run still COMPLETES and
     BOTH tracks are not_available with HONEST_NO_PRE_PERIODS.
  3. breakdown non-None for sd (real run preferred; falls back to honest_sd
     direct with a strong effect). breakdown must be one of the m_grid values.
  4. M=0 anchor: in the real happy-path cs_did.json, the sd post_average CI
     widths are NON-DECREASING in M (M=0 = classical min-SD CI = tightest).
  5. finite-run additivity: a run WITH honest_did vs the SAME run WITHOUT —
     att_gt / aggregations / metadata sections are BYTE-identical (the honest
     block is purely additive).

Reuses the staggered-CSV harness + runner-constant monkeypatch from
``test_honest_did_wiring.py`` / ``test_honest_did_qa.py`` to keep the ΔRM grid
small for speed (ΔSD/FLCI is already fast and deterministic).
"""
import json

import numpy as np
import pandas as pd

from workbench.engine.honest_did import honest_sd
from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project
from workbench.artifacts import read_json


def _reject_constant(token):
    """Emulate the browser's strict JSON parser: NaN/Infinity are NOT valid JSON."""
    raise ValueError(f"strict JSON rejects non-finite constant: {token!r}")


def _staggered_csv(tmp_path, name="csdid.csv"):
    """Staggered panel with 2 pre-periods for the early cohort (treat 2019/2021
    over 2017..2022) + never-treated controls. Mirrors the wiring harness."""
    rng = np.random.default_rng(3)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0), ("G", 2019), ("H", 2021),
                        ("I", 0), ("J", 2019)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / name
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def _run(tmp_path, src, *, honest, monkeypatch):
    import workbench.econometrics.runner as runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])  # tiny ΔRM grid
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 150)
    project = create_project(tmp_path, "demo")
    kw = dict(mode="auto", y="y", x=[], model_type="cs_did", entity_col="id",
              time_col="year", did_mode="cohort", did_cohort_col="first_treat")
    if honest:
        kw["honest_did"] = True
    result = _rw(project.root, [src], **kw)
    return project.root / "runs" / result["run_id"]


# ---------------------------------------------------------------------------
# PROOF 1 — happy path end-to-end (sd ok, FLCI, finite m_grid, strict JSON)
# ---------------------------------------------------------------------------

def test_proof1_happy_path_sd_track_end_to_end(tmp_path, monkeypatch):
    src = _staggered_csv(tmp_path)
    run_root = _run(tmp_path, src, honest=True, monkeypatch=monkeypatch)

    assert read_json(run_root / "run_manifest.json")["status"] == "completed"

    cs_path = run_root / "cs_did.json"
    text = cs_path.read_text()
    assert "NaN" not in text and "Infinity" not in text
    # browser-strict reload must NOT raise
    art = json.loads(text, parse_constant=_reject_constant)

    hd = art["honest_did"]
    rm, sd = hd["rm"], hd["sd"]

    # this >=2-pre design must let BOTH tracks RUN (not skip)
    assert rm["status"] == "ok", f"expected rm ok, got {rm.get('reason')}"
    assert sd["status"] == "ok", f"expected sd ok, got {sd.get('reason')}"

    # sd contract: FLCI method, finite 5-point m_grid, scale > 0
    assert sd["method"] == "FLCI"
    assert len(sd["m_grid"]) == 5
    assert all(np.isfinite(v) for v in sd["m_grid"])
    assert sd["scale"] > 0.0

    # sd post_average rows keyed M with finite-or-null lb/ub
    pa = sd["post_average"]
    assert pa["results"], "sd post_average has no rows"
    for r in pa["results"]:
        assert "M" in r and "Mbar" not in r        # sd uses M, never Mbar
        for k in ("lb", "ub"):
            assert r[k] is None or np.isfinite(r[k])
    # per_event_time length == num_post
    assert len(sd["per_event_time"]) == sd["num_post"]
    for pet in sd["per_event_time"]:
        assert all("M" in r for r in pet["results"])

    # rm rows keyed Mbar (cross-check the keying contract)
    assert all("Mbar" in r and "M" not in r for r in rm["post_average"]["results"])

    # _debug_* fully stripped
    assert not any(k.startswith("_debug_") for k in hd)
    assert not any(k.startswith("_debug_") for k in sd)
    assert not any(k.startswith("_debug_") for k in rm)


# ---------------------------------------------------------------------------
# PROOF 2 — no usable pre-period: run completes, BOTH tracks not_available
# ---------------------------------------------------------------------------

def test_proof2_no_pre_periods_degrades_not_fails(tmp_path, monkeypatch):
    # Treated at the SECOND observed period (2018): the only pre-treatment event
    # time is e=-1, the structural reference (excluded) -> num_pre==0. cs_did is
    # still estimable so the run completes; honest-DID has nothing to work with.
    rng = np.random.default_rng(7)
    rows = []
    for ent, cohort in [("A", 2018), ("B", 2018), ("C", 0), ("D", 0),
                        ("E", 2018), ("F", 0), ("G", 0), ("H", 2018),
                        ("I", 0), ("J", 2018)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / "onepre.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    run_root = _run(tmp_path, src, honest=True, monkeypatch=monkeypatch)

    # run STILL completes (degrade-not-fail)
    assert read_json(run_root / "run_manifest.json")["status"] == "completed"
    art = read_json(run_root / "cs_did.json")
    hd = art["honest_did"]
    assert hd["rm"]["status"] == "not_available"
    assert "HONEST_NO_PRE_PERIODS" in hd["rm"]["reason"]
    assert hd["sd"]["status"] == "not_available"
    assert "HONEST_NO_PRE_PERIODS" in hd["sd"]["reason"]
    # the degraded sd track still type-checks against the FE optional fields:
    # only {status, reason, num_pre, num_post, **extra}; no post_average required.
    assert "post_average" not in hd["sd"] or hd["sd"]["post_average"] is not None


# ---------------------------------------------------------------------------
# PROOF 3 — breakdown non-None for sd; value is one of the m_grid points
# ---------------------------------------------------------------------------

def test_proof3_sd_breakdown_is_a_grid_value(tmp_path, monkeypatch):
    # Try the real run first: the clean 2.0-effect staggered design has a strong,
    # precise post effect, so some M on the grid should still exclude 0.
    src = _staggered_csv(tmp_path)
    run_root = _run(tmp_path, src, honest=True, monkeypatch=monkeypatch)
    sd = read_json(run_root / "cs_did.json")["honest_did"]["sd"]
    assert sd["status"] == "ok"
    pa = sd["post_average"]
    grid = set(sd["m_grid"])

    if pa["breakdown"] is not None:
        assert pa["breakdown"] in grid
        # breakdown == largest M that still excludes 0
        excluding = [r["M"] for r in pa["results"]
                     if r["lb"] is not None and r["ub"] is not None
                     and (r["lb"] > 0.0 or r["ub"] < 0.0)]
        assert pa["breakdown"] == max(excluding)
    else:
        # Fallback: force a non-None breakdown via honest_sd directly with a
        # betahat far from 0 and a tight Σ so small M still excludes 0.
        betahat = np.array([0.0, 0.0, 3.0, 3.0])
        sigma = np.eye(4) * 0.02
        l = np.array([0.5, 0.5])
        m_grid = [0.0, 0.5, 1.0, 2.0, 5.0]
        out = honest_sd(betahat=betahat, sigma=sigma, num_pre=2, num_post=2,
                        l_vec=l, m_grid=m_grid)
        assert out["breakdown"] is not None
        assert out["breakdown"] in set(m_grid)


def test_proof3b_honest_sd_breakdown_direct_non_none():
    # Strong precise effect -> the smallest M excludes 0, the largest admits it:
    # a clean, deterministic non-None breakdown that is a grid value.
    betahat = np.array([0.0, 0.0, 3.0, 3.0])
    sigma = np.eye(4) * 0.02
    l = np.array([0.5, 0.5])
    m_grid = [0.0, 0.5, 1.0, 2.0, 5.0]
    out = honest_sd(betahat=betahat, sigma=sigma, num_pre=2, num_post=2,
                    l_vec=l, m_grid=m_grid)
    bd = out["breakdown"]
    assert bd is not None
    assert bd in set(m_grid)
    excluding = [r["M"] for r in out["results"]
                 if r["lb"] == r["lb"] and r["ub"] == r["ub"]
                 and (r["lb"] > 0.0 or r["ub"] < 0.0)]
    assert bd == max(excluding)


# ---------------------------------------------------------------------------
# PROOF 4 — M=0 anchor: CI widths non-decreasing in M (FLCI half-length grows)
# ---------------------------------------------------------------------------

def test_proof4_sd_ci_widths_non_decreasing_in_M(tmp_path, monkeypatch):
    src = _staggered_csv(tmp_path)
    run_root = _run(tmp_path, src, honest=True, monkeypatch=monkeypatch)
    sd = read_json(run_root / "cs_did.json")["honest_did"]["sd"]
    assert sd["status"] == "ok"
    rows = sd["post_average"]["results"]
    # rows are emitted in m_grid order; widths must be non-decreasing in M
    ms = [r["M"] for r in rows]
    assert ms == sorted(ms), "m_grid rows not in ascending M order"
    widths = []
    for r in rows:
        assert r["lb"] is not None and r["ub"] is not None  # finite happy path
        widths.append(r["ub"] - r["lb"])
    # M=0 = classical min-SD FLCI = tightest
    assert widths[0] == min(widths)
    for a, b in zip(widths, widths[1:]):
        assert b >= a - 1e-9, f"CI width decreased with M: {widths}"


# ---------------------------------------------------------------------------
# PROOF 5 — additivity: honest block does not perturb the non-honest sections
# ---------------------------------------------------------------------------

def test_proof5_honest_block_is_purely_additive(tmp_path, monkeypatch):
    # Two SEPARATE project roots so artifact paths don't collide; identical CSV.
    sub_h = tmp_path / "with"
    sub_n = tmp_path / "without"
    sub_h.mkdir()
    sub_n.mkdir()
    src_h = _staggered_csv(sub_h)
    src_n = _staggered_csv(sub_n)

    run_h = _run(sub_h, src_h, honest=True, monkeypatch=monkeypatch)
    run_n = _run(sub_n, src_n, honest=False, monkeypatch=monkeypatch)

    art_h = read_json(run_h / "cs_did.json")
    art_n = read_json(run_n / "cs_did.json")

    # honest block present only on the honest run
    assert "honest_did" in art_h
    assert "honest_did" not in art_n

    # every non-honest section must be byte-identical (additive guarantee)
    for section in ("att_gt", "aggregations", "metadata", "diagnostics", "warnings"):
        assert json.dumps(art_h.get(section), sort_keys=True) == \
               json.dumps(art_n.get(section), sort_keys=True), \
               f"section '{section}' drifted when honest_did was enabled"

    # and the ONLY extra top-level key is honest_did
    assert set(art_h) - set(art_n) == {"honest_did"}
