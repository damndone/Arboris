import numpy as np
import pandas as pd

from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project
from workbench.artifacts import read_json


def _staggered_csv(tmp_path):
    # cohorts with PRE-periods (so honest-DID runs): observe 2017..2022,
    # treat 2019/2021 + never-treated
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
    src = tmp_path / "csdid.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_honest_did_completes_end_to_end(tmp_path, monkeypatch):
    import workbench.econometrics.runner as runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 150)
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat", honest_did=True)
    run_root = project.root / "runs" / result["run_id"]
    assert read_json(run_root / "run_manifest.json")["status"] == "completed"
    art = read_json(run_root / "cs_did.json")
    assert "honest_did" in art
    hd = art["honest_did"]
    rm, sd = hd["rm"], hd["sd"]
    # may be not_available if this design yields no pre-periods; if ok,
    # post_average present
    if rm["status"] == "ok":
        assert "post_average" in rm and "results" in rm["post_average"]
    # ΔSD/FLCI track runs on the same snapshot: ok (with M-grid) or a sensible
    # not_available reason.
    assert sd["status"] in ("ok", "not_available")
    if sd["status"] == "ok":
        assert sd["method"] == "FLCI"
        assert "results" in sd["post_average"]
        assert sd["post_average"]["results"][0].get("M") is not None
    else:
        assert sd["reason"]
    assert not any(k.startswith("_debug_") for k in hd)     # debug stripped (top level)
    assert not any(k.startswith("_debug_") for k in rm)     # and not in tracks
    assert not any(k.startswith("_debug_") for k in sd)


def test_honest_did_absent_without_flag(tmp_path):
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat")
    art = read_json(project.root / "runs" / result["run_id"] / "cs_did.json")
    assert "honest_did" not in art          # golden 0-drift for the no-flag path


def test_honest_did_no_pre_periods_skips_not_fails(tmp_path, monkeypatch):
    import workbench.econometrics.runner as runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 150)
    # Design with exactly ONE pre-period per treated cohort (treated at the
    # SECOND observed period 2018): the dynamic aggregation's only pre-treatment
    # event time is e=-1, which is the structural reference (excluded) -> num_pre=0.
    # The full 6-period span keeps cs_did itself estimable (it just leaves honest-DID
    # nothing to work with), so the run completes while honest-DID skips.
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
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat", honest_did=True)
    run_root = project.root / "runs" / result["run_id"]
    assert read_json(run_root / "run_manifest.json")["status"] == "completed"   # run STILL completes
    art = read_json(run_root / "cs_did.json")
    hd = art["honest_did"]
    # With no usable pre-period, BOTH tracks are not_available with the same
    # HONEST_NO_PRE_PERIODS reason.
    assert hd["rm"]["status"] == "not_available"
    assert "HONEST_NO_PRE_PERIODS" in hd["rm"]["reason"]
    assert hd["sd"]["status"] == "not_available"
    assert "HONEST_NO_PRE_PERIODS" in hd["sd"]["reason"]
