import json
from pathlib import Path
import pandas as pd
import pytest
from workbench.engine.dcdh_spec import normalize_treatment_path, DCDHSpecError
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "dcdh"


def _norm(name):
    d = pd.read_csv(_FIX / f"panel_{name}.csv")
    return normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")


def test_nonabsorbing_switchback_runs():
    # the main fixture contains 0->1->0 switch-backs; run must complete + serialize
    res = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    json.dumps(res, allow_nan=False)


def test_placebo_near_zero():
    res = runner.run_dcdh(_norm("placebo"), cluster_var=None)
    es = res["event_study"]
    plac = [es["estimate"][i] for i, k in enumerate(es["kind"]) if k == "placebo"]
    assert plac and max(abs(p) for p in plac) < 0.25   # DGP has no effect


def test_baseline1_runs_and_excludes():
    # baseline1 fixture mixes baseline=1 (excluded) with baseline=0 up-switchers
    res = runner.run_dcdh(_norm("baseline1"), cluster_var=None)
    assert len(res["diagnostics"]["excluded_units"]) > 0
    json.dumps(res, allow_nan=False)


def test_all_baseline1_raises_no_eligible():
    rows = [{"id": i, "year": yr, "d": int(yr <= 2), "y": float(i + yr)}
            for i in range(4) for yr in range(1, 5)]
    n = normalize_treatment_path  # noqa: F841 (just for clarity)
    with pytest.raises(DCDHSpecError, match="DCDH_NO_ELIGIBLE_UP_SWITCHERS"):
        runner.run_dcdh(
            normalize_treatment_path(pd.DataFrame(rows), entity="id", time="year",
                                     y="y", treatment="d"),
            cluster_var=None)


def test_nonnumeric_y_raises_clean():
    d = pd.read_csv(_FIX / "panel_nonabsorbing.csv")
    d["y"] = "abc"
    n = normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")
    with pytest.raises(ValueError):
        runner.run_dcdh(n, cluster_var=None)


def test_cluster_var_real_column_serializes():
    n = _norm("nonabsorbing")
    n.frame["clu"] = (n.frame["id"] % 5 + 1).astype(float)
    res = runner.run_dcdh(n, cluster_var="clu")
    json.dumps(res, allow_nan=False)


def test_string_entity_ids_work():
    # Regression: entity ids may be strings (e.g. "u00") — must not float()-coerce.
    rows = []
    for i in range(12):
        ent = f"u{i:02d}"; fy = [3, 4, 0][i % 3]
        for yr in range(1, 7):
            d = 1 if (fy and yr >= fy) else 0
            rows.append({"id": ent, "year": yr, "d": d, "y": float(i + yr)})
    n = normalize_treatment_path(pd.DataFrame(rows), entity="id", time="year", y="y", treatment="d")
    res = runner.run_dcdh(n, cluster_var=None)
    json.dumps(res, allow_nan=False)
