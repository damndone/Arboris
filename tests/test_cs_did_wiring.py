import numpy as np
import pandas as pd

from workbench.engine.stages.estimation import CORE_PACK
from workbench.orchestrator._model_types import _MODEL_TYPE_MAP
from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project


def test_cs_did_registered_explicit_only():
    keys = [h.model_type for h in CORE_PACK.model_handlers]
    assert "cs_did" in keys
    assert "cs_did" not in CORE_PACK.defaults_by_y_type.values()
    assert _MODEL_TYPE_MAP["cs_did"] == "continuous"


def test_cs_did_rerun_action_present():
    assert any(a.key == "cs_did_switch_to_did" for a in CORE_PACK.rerun_actions)


def test_cs_did_orchestrator_reexports_run_cs_did():
    from workbench import orchestrator
    assert hasattr(orchestrator, "run_cs_did")


def _staggered_csv(tmp_path):
    rng = np.random.default_rng(3)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / "csdid.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_cs_did_end_to_end_runs_and_records_att(tmp_path):
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat")
    run_root = project.root / "runs" / result["run_id"]
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"
    primary = read_json(run_root / "model_results" / "cs_did_1.json")
    assert primary["model_type"] == "cs_did"
    assert "ATT" in primary["coefficients"]


def test_cs_did_missing_entity_time_fails_clearly(tmp_path):
    rng = np.random.default_rng(7)
    src = tmp_path / "flat.csv"
    pd.DataFrame({"y": rng.normal(size=60), "x1": rng.normal(size=60)}).to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    try:
        result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="cs_did",
                     did_mode="cohort", did_cohort_col="x1")
        run_id = result["run_id"]
    except Exception:
        runs = sorted((project.root / "runs").iterdir(), key=lambda p: p.stat().st_mtime)
        run_id = runs[-1].name
    run_root = project.root / "runs" / run_id
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "failed"
    errors = read_json(run_root / "errors.json")
    codes = [i.get("code") for i in errors.get("issues", [])]
    assert "CS_DID_FIELDS_MISSING" in codes


# ---------------------------------------------------------------------------
# Task 12: degraded-safe cs_did result artifact + capabilities sync
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_FIXTURE_PANEL = _Path(__file__).parent / "fixtures" / "cs_did" / "panel.csv"


def _run_cs_did_on_fixture(tmp_path):
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [_FIXTURE_PANEL], mode="auto", y="y", x=[],
                 model_type="cs_did", entity_col="unit", time_col="period",
                 did_mode="cohort", did_cohort_col="first_treat")
    run_root = project.root / "runs" / result["run_id"]
    return run_root


def test_cs_did_artifact_present_and_valid(tmp_path):
    """End-to-end: a cs_did artifact is written, valid JSON, has the 4
    aggregations + metadata. Goes RED if the diagnostics block is removed."""
    run_root = _run_cs_did_on_fixture(tmp_path)
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"

    cs_path = run_root / "cs_did.json"
    assert cs_path.exists(), "cs_did artifact missing (diagnostics block removed?)"
    artifact = _json.loads(cs_path.read_text())
    assert artifact.get("available") is True
    assert set(artifact["aggregations"]) >= {"simple", "dynamic", "group", "calendar"}
    assert "metadata" in artifact

    summary = read_json(run_root / "diagnostic_summary.json")
    assert summary["run_status"]["report_render_status"] == "complete"
    assert summary["run_status"]["report_available"] is True
    assert summary["run_status"]["has_warnings"] is True
    assert any(
        issue["code"] == "DID_DYNAMIC_THIN_SUPPORT"
        for issue in summary["diagnostics"]["warnings"]
    )
    summary_record = next(
        item for item in read_json(run_root / "artifacts_index.json")["artifacts"]
        if item["artifact_id"] == "diagnostic_summary"
    )
    from workbench.artifacts import sha256_file
    assert summary_record["sha256"] == sha256_file(run_root / "diagnostic_summary.json")

    # registered in the artifact index
    index = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in index["artifacts"]}
    assert "cs_did" in ids


def test_cs_did_artifact_degrades_when_serialization_fails(tmp_path, monkeypatch):
    """If _json_safe raises, the artifact degrades to {available: False, error}
    and the run still completes (status != failed)."""
    from workbench.engine.stages import diagnostics as diag_mod

    def _boom(obj):
        raise RuntimeError("boom-serialize")

    monkeypatch.setattr(diag_mod, "_json_safe", _boom)
    run_root = _run_cs_did_on_fixture(tmp_path)

    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"  # degrade, not WORKFLOW_FAILED

    artifact = _json.loads((run_root / "cs_did.json").read_text())
    assert artifact.get("available") is False
    assert "boom-serialize" in artifact.get("error", "")


def test_cs_did_capabilities_sync():
    from workbench.engine.capabilities import MODEL_UI_META, MODEL_UI_ORDER
    assert MODEL_UI_META["cs_did"]["group"] == "DID"
    assert "cs_did" in MODEL_UI_ORDER


def test_json_safe_coerces_numpy():
    from workbench.engine.stages.diagnostics import _json_safe
    obj = {"a": np.int64(3), "b": np.array([1.0, 2.0]),
           "c": [np.float64(1.5)], "d": None, "e": "x"}
    out = _json_safe(obj)
    assert out == {"a": 3, "b": [1.0, 2.0], "c": [1.5], "d": None, "e": "x"}
    assert isinstance(out, dict)  # so .setdefault works downstream
    _json.dumps(out)  # must be JSON-serializable
