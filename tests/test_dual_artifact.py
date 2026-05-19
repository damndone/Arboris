from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_both_artifacts_written_from_same_internal_state(tmp_path: Path):
    source = tmp_path / "data.csv"
    rng = range(100)
    pd.DataFrame({
        "y": [float(1 + 3 * i) for i in rng],
        "x1": [float(0.5 + 1.5 * i) for i in rng],
    }).to_csv(source, index=False)

    project = create_project(tmp_path, "test_dual")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x1"])

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]

    ds_path = run_root / "diagnostic_summary.json"
    err_path = run_root / "errors.json"
    assert ds_path.is_file(), "diagnostic_summary.json was not written"
    assert err_path.is_file(), "errors.json was not written"

    ds = read_json(ds_path)
    assert ds["schema_version"] == "1.0"
    assert "diagnostics" in ds
    assert "run_status" in ds

    err = read_json(err_path)
    assert "issues" in err
    assert err.get("superseded_by") == "diagnostic_summary.json"

    # Verify same issues appear in both
    ds_codes = set()
    for sev_group in ds["diagnostics"].values():
        for issue in sev_group:
            ds_codes.add(issue["code"])
    err_codes = {i["code"] for i in err["issues"]}
    assert ds_codes == err_codes, f"Mismatch: DS={ds_codes}, ERR={err_codes}"

    # Verify issue IDs are generated and unique
    all_issues = []
    for sev_group in ds["diagnostics"].values():
        all_issues.extend(sev_group)
    if all_issues:
        issue_ids = [i["issue_id"] for i in all_issues]
        assert all(iid.startswith("diag_") for iid in issue_ids)
        assert len(set(issue_ids)) == len(issue_ids)

    # Verify legacy errors.json structure
    assert err["schema_version"] == "legacy"
    assert err["superseded_by"] == "diagnostic_summary.json"

    # Verify diagnostic_summary has all required top-level keys
    required_keys = {
        "schema_version", "run_id", "run_status", "model_identity",
        "preprocessing", "diagnostics", "coefficients_summary",
        "model_quality", "narrative_contract",
    }
    assert required_keys <= ds.keys(), f"Missing keys: {required_keys - ds.keys()}"
