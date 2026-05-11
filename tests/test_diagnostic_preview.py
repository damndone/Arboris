from pathlib import Path

from workbench.artifacts import write_json
from workbench.diagnostic_preview import build_diagnostic_summary_preview


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    root.mkdir()
    write_json(root / "artifacts_index.json", {"artifacts": []})
    return root


# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------

def test_running_run_returns_pending_preview(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "running", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is False
    assert preview["preview_status"] == "pending"
    assert preview["run_lifecycle_status"] == "running"
    assert preview["trust_label"] == "analysis_running"
    assert "run_status" not in preview


def test_queued_run_returns_pending_preview(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "queued", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is False
    assert preview["preview_status"] == "pending"
    assert preview["trust_label"] == "analysis_running"


def test_interrupted_run_returns_lifecycle_unavailable(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "interrupted", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is False
    assert preview["preview_status"] == "lifecycle_unavailable"
    assert preview["run_lifecycle_status"] == "interrupted"
    assert preview["trust_label"] == "lifecycle_unavailable"


def test_cancelled_run_returns_lifecycle_unavailable(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "cancelled", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is False
    assert preview["preview_status"] == "lifecycle_unavailable"
    assert preview["trust_label"] == "lifecycle_unavailable"


def test_failed_run_returns_run_failed_preview(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "failed", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(
        run_root, manifest, model_results=[{"model_id": "ols_1", "model_type": "ols"}]
    )

    assert preview["available"] is False
    assert preview["preview_status"] == "unavailable"
    assert preview["trust_label"] == "run_failed"
    assert preview["run_status"]["status"] == "failed"
    assert preview["run_status"]["status_scope"] == "run_level"
    assert preview["run_status"]["safe_to_generate_report"] is False
    assert preview["run_status"]["safe_to_interpret"] == "unavailable"
    assert preview["artifact_manifest"]["primary_model_results"]["model_id"] == "ols_1"


# ---------------------------------------------------------------------------
# Missing diagnostic_summary.json → legacy fallback
# ---------------------------------------------------------------------------

def test_missing_diagnostic_summary_legacy_fallback(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "completed", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is False
    assert preview["preview_status"] == "unavailable"
    assert preview["trust_label"] == "legacy_unavailable"
    assert preview["run_lifecycle_status"] == "completed"
    assert any("missing" in w for w in preview["contract_warnings"])


# ---------------------------------------------------------------------------
# Malformed diagnostic_summary.json
# ---------------------------------------------------------------------------

def test_malformed_diagnostic_summary_contract_unavailable(tmp_path: Path):
    run_root = _run_root(tmp_path)
    (run_root / "diagnostic_summary.json").write_text("not json", encoding="utf-8")
    manifest = {"run_id": "r1", "status": "completed", "y": "y", "x": ["x"], "mode": "auto"}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is False
    assert preview["preview_status"] == "malformed"
    assert preview["trust_label"] == "contract_unavailable"


# ---------------------------------------------------------------------------
# Required canonical fields always present when available is set
# ---------------------------------------------------------------------------

def test_available_base_preview_has_contract_version(tmp_path: Path):
    run_root = _run_root(tmp_path)
    manifest = {"run_id": "r1", "status": "queued", "y": "y", "x": ["x"], "mode": "auto"}
    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])
    assert preview["preview_contract_version"] == "1.0"
    assert preview["source_schema_version"] == "diagnostic_summary.v1"
    assert isinstance(preview["primary_reasons"], list)
