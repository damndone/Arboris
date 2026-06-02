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
