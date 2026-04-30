from pathlib import Path

import pandas as pd

from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_run_workflow_creates_traceable_outputs(tmp_path: Path):
    source = tmp_path / "cross_section.csv"
    pd.DataFrame(
        {
            "y": [1 + 2 * i for i in range(35)],
            "x": list(range(35)),
            "firm_id": list(range(100, 135)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "run_manifest.json").exists()
    assert (run_root / "reports" / "report.html").exists()
    assert (run_root / "reports" / "report.pdf").exists()
    assert (run_root / "exports" / "tables.xlsx").exists()
    assert (run_root / "artifacts_index.json").exists()
