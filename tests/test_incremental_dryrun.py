"""Loop 2A.4 — cache wrapper DRY-RUN: computes node_hash + writes
incremental_trace.json, but does NOT skip any stage (execution unchanged).
golden 0-drift is guaranteed because the flag defaults OFF (golden suite never
sets it); here we set it on via monkeypatch to exercise the trace."""
import json
from pathlib import Path

from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURE = Path(__file__).parent / "fixtures" / "forest_min.csv"


def _run(tmp_path, **extra):
    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [FIXTURE], mode="auto", y="wage",
        x=["education", "experience"], model_type="ols", **extra,
    )
    return project.root / "runs" / result["run_id"], result


def test_dryrun_writes_complete_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    run_root, result = _run(tmp_path)
    trace = json.loads((run_root / "incremental_trace.json").read_text())
    names = [t["stage"] for t in trace]

    # Every cacheable stage of a successful OLS run appears.
    for expected in ("source", "cleaning", "estimation", "report"):
        assert expected in names, f"{expected} missing from trace: {names}"

    # RecordingStage is NEVER cached (it builds the graph view, Loop 2A.7).
    assert "recording" not in names

    # Each trace entry carries a real node_hash, op_spec_hash, parents and a
    # valid status from the 2A.5 taxonomy. forest_min has no missing data, so no
    # MICE skip — a fresh project run records every cacheable stage as executed.
    _VALID = {"miss_executed", "hit_reused", "recomputed_same_hash", "recomputed_changed"}
    for t in trace:
        assert t["node_hash"] and isinstance(t["node_hash"], str)
        assert t["op_spec_hash"] and isinstance(t["op_spec_hash"], str)
        assert "parents" in t
        assert t["status"] in _VALID


def test_flag_off_writes_no_trace(tmp_path):
    # Default (flag off) → no behavior change, no trace file.
    run_root, _ = _run(tmp_path)
    assert not (run_root / "incremental_trace.json").exists()
