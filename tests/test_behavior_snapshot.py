"""V1.5.4 behavior snapshot: numeric equivalence vs the Phase-1 golden.
Locks the property that the refactor did not perturb point estimates."""
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_behavior_snapshot_matches_committed_golden(tmp_path):
    """Re-runs the continuous_ols golden's fixture and asserts the model's
    point estimate matches the committed golden (single source of truth)."""
    frame = pd.DataFrame({
        "y": [1.0 + 2.0 * i for i in range(40)],
        "x": list(range(40)),
        "firm_id": list(range(100, 140)),
    })
    src = tmp_path / "d.csv"
    frame.to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    res = run_workflow(project.root, [src], mode="auto", y="y", x=["x"])
    run_root = project.root / "runs" / res["run_id"]
    mr = read_json(run_root / "model_results" / "ols_1.json")
    golden = read_json(Path(__file__).parent / "golden" / "continuous_ols.json")
    # Coefficients in mr are nested dicts ({"estimate": float, ...}); the
    # golden's coef_rounded is the rounded point estimate. Compare those.
    assert round(float(mr["coefficients"]["x"]["estimate"]), 6) == \
        golden["models"]["ols_1"]["coef_rounded"]["x"]
    assert round(float(mr["coefficients"]["Intercept"]["estimate"]), 6) == \
        golden["models"]["ols_1"]["coef_rounded"]["Intercept"]
