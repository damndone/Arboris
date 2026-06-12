import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path, frame, *, y, x, mode="auto", model_type="auto"):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode=mode, y=y, x=x, model_type=model_type)
    return project.root / "runs" / result["run_id"], result


def _coef_value(v):
    # Coefficients are serialized as nested dicts ({"estimate": ..., "std_error": ...}),
    # not flat floats. Extract the point estimate; fall back to a scalar if encountered.
    if isinstance(v, dict):
        return v.get("estimate")
    return v


def _capture(run_root):
    manifest = read_json(run_root / "run_manifest.json")
    idx = read_json(run_root / "artifacts_index.json")
    artifacts = {a["artifact_id"]: sorted(a.get("inputs", [])) for a in idx["artifacts"]}
    snapshot = {"status": manifest["status"], "artifacts": artifacts}
    model_dir = run_root / "model_results"
    if model_dir.exists():
        models = {}
        for mr in sorted(model_dir.glob("*.json")):
            m = read_json(mr)
            models[m["model_id"]] = {
                "model_type": m.get("model_type"),
                "coef_keys": sorted(m.get("coefficients", {}).keys()),
                "coef_rounded": {
                    k: round(float(_coef_value(v)), 6)
                    for k, v in m.get("coefficients", {}).items()
                },
            }
        snapshot["models"] = models
    errors_path = run_root / "errors.json"
    if errors_path.exists():
        snapshot["error_codes"] = sorted(i["code"] for i in read_json(errors_path).get("issues", []))
    return snapshot


_GOLDEN_DIR = Path(__file__).parent / "golden"


def _assert_or_write_golden(name, snap):
    _GOLDEN_DIR.mkdir(exist_ok=True)
    path = _GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        path.write_text(json.dumps(snap, indent=2, sort_keys=True))
        pytest.skip(f"golden {name} written; re-run to assert")
    expected = json.loads(path.read_text())
    assert snap == expected, f"golden drift for {name}"


def test_golden_continuous_ols(tmp_path):
    frame = pd.DataFrame({"y": [1.0 + 2.0 * i for i in range(40)], "x": list(range(40)), "firm_id": list(range(100, 140))})
    run_root, result = _run(tmp_path, frame, y="y", x=["x"])
    snap = _capture(run_root)
    assert snap["status"] == "completed"
    assert snap["models"]["ols_1"]["model_type"] in {"ols", "ols_robust", "continuous"}
    assert "x" in snap["models"]["ols_1"]["coef_keys"]
    _assert_or_write_golden("continuous_ols", snap)


def test_golden_binary_logit(tmp_path):
    frame = pd.DataFrame({"y": [0, 1] * 25, "x": [i * 0.5 for i in range(50)], "firm_id": list(range(200, 250))})
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    _assert_or_write_golden("binary_logit", _capture(run_root))


def test_golden_count_poisson(tmp_path):
    frame = pd.DataFrame({"y": [i % 5 for i in range(50)], "x": [i * 0.3 for i in range(50)], "firm_id": list(range(300, 350))})
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    _assert_or_write_golden("count_poisson", _capture(run_root))


def test_golden_panel(tmp_path):
    rows = []
    for firm_id in range(6):
        for year in range(2018, 2025):
            x = firm_id + year - 2018
            rows.append({"firm_id": firm_id, "year": year, "x": x, "y": 1.0 + 2.0 * x + firm_id * 0.1})
    run_root, _ = _run(tmp_path, pd.DataFrame(rows), y="y", x=["x"])
    _assert_or_write_golden("panel", _capture(run_root))


def test_golden_blocked_missing_column(tmp_path):
    frame = pd.DataFrame({"y": [1.0 * i for i in range(35)], "x": list(range(35))})
    run_root, result = _run(tmp_path, frame, y="y", x=["missing"])
    assert result["status"] == "blocked"
    _assert_or_write_golden("blocked_missing_column", _capture(run_root))


def test_golden_imputation(tmp_path):
    # The imputation (MICE) branch is config-gated in run_workflow: it fires only
    # when project config.yml sets imputation_method=mice (not by missing-value
    # proportion alone). We enable it test-side and feed columns with NaNs so the
    # imputed_dataset lineage actually appears. Mirrors test_imputation_mice.py.
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) for i in range(40)]
    for index in (5, 11, 17, 23):
        ys[index] = None
    for index in (7, 13, 19, 29):
        xs[index] = None
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})

    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    (project.root / "config.yml").write_text(
        "imputation_method: mice\nimputation_m: 2\nimputation_max_iter: 2\n",
        encoding="utf-8",
    )
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    run_root = project.root / "runs" / result["run_id"]

    snap = _capture(run_root)
    # Guard: the imputation branch must have fired for this golden to be meaningful.
    assert "imputed_dataset" in snap["artifacts"]
    _assert_or_write_golden("imputation", snap)


def test_golden_explicit_model_type_logit(tmp_path):
    frame = pd.DataFrame({"y": [0, 1] * 25, "x": [i * 0.5 for i in range(50)], "firm_id": list(range(200, 250))})
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"], model_type="logit")
    _assert_or_write_golden("explicit_logit", _capture(run_root))


def test_golden_iv_2sls(tmp_path):
    import numpy as np

    rng = np.random.default_rng(0)
    n = 400
    z = rng.normal(size=n)
    u = rng.normal(size=n)
    educ = 0.8 * z + u + rng.normal(size=n) * 0.3
    age = rng.normal(size=n)
    wage = 1.0 + 0.5 * educ + 0.2 * age + u + rng.normal(size=n) * 0.5
    frame = pd.DataFrame({"wage": wage, "educ": educ, "age": age, "dist": z})

    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [source], mode="auto", y="wage", x=["age"],
        model_type="iv_2sls", iv_endog=["educ"], iv_instruments=["dist"],
    )
    run_root = project.root / "runs" / result["run_id"]

    snap = _capture(run_root)
    # Guard: an IV regression from Task 2 must complete; a failure here is a regression.
    assert snap["status"] == "completed"
    _assert_or_write_golden("iv_2sls", snap)
