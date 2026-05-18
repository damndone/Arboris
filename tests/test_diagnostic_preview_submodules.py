"""V1.3.2: focused tests for diagnostic_preview submodule boundaries.

These exist alongside (not replacing) test_diagnostic_preview.py. They give
each submodule a direct entry point for regressions that don't surface
through the top-level build_diagnostic_summary_preview.
"""
from pathlib import Path

from workbench.diagnostic_preview.artifact_manifest import build_artifact_manifest
from workbench.diagnostic_preview.contract_validation import (
    base_unavailable,
    safe_to_interpret,
    trust_label_for_status,
    trust_status,
)
from workbench.diagnostic_preview.coefficient_risk import build_coefficient_risk
from workbench.diagnostic_preview.guidance import (
    model_identity,
    primary_reasons,
    recommended_actions,
)


def test_artifact_manifest_marks_missing_report_html(tmp_path: Path):
    manifest = build_artifact_manifest(tmp_path, [{"model_id": "m1"}])
    assert manifest["report_html"]["available"] is False
    assert manifest["report_html"]["expected"] is True
    assert manifest["primary_model_results"]["model_id"] == "m1"


def test_artifact_manifest_secondary_count(tmp_path: Path):
    manifest = build_artifact_manifest(tmp_path, [{"model_id": "m1"}, {"model_id": "m2"}, {"model_id": "m3"}])
    assert manifest["secondary_model_results"]["expected"] is True
    assert manifest["secondary_model_results"]["available_count"] == 2


def test_base_unavailable_shape():
    payload = base_unavailable("queued", "pending", "analysis_running")
    assert payload["available"] is False
    assert payload["preview_status"] == "pending"
    assert payload["trust_label"] == "analysis_running"
    assert payload["primary_reasons"] == []


def test_trust_status_transitions():
    assert trust_status({"blockers": 0, "warnings": 0, "cautions": 0, "info": 0}, True) == "ok"
    assert trust_status({"blockers": 0, "warnings": 1, "cautions": 0, "info": 0}, True) == "usable_with_caution"
    assert trust_status({"blockers": 1, "warnings": 0, "cautions": 0, "info": 0}, True) == "blocked"
    assert trust_status({"blockers": 0, "warnings": 0, "cautions": 0, "info": 0}, False) == "failed"


def test_trust_label_for_status_complete():
    assert trust_label_for_status("ok") == "ready_to_interpret"
    assert trust_label_for_status("usable_with_caution") == "interpret_with_caution"
    assert trust_label_for_status("blocked") == "not_ready_to_interpret"
    assert trust_label_for_status("failed") == "run_failed"


def test_safe_to_interpret_complete():
    assert safe_to_interpret("ok") == "yes"
    assert safe_to_interpret("usable_with_caution") == "partial"
    assert safe_to_interpret("blocked") == "no"
    assert safe_to_interpret("failed") == "unavailable"


def test_primary_reasons_sorts_by_severity_and_limits():
    issues = [
        {"code": "C1", "severity": "WARNING", "message": "w1"},
        {"code": "C2", "severity": "BLOCKER", "message": "b1"},
        {"code": "C3", "severity": "CAUTION", "message": "c1"},
        {"code": "C4", "severity": "INFO", "message": "i1"},
    ]
    out = primary_reasons(issues, limit=2)
    assert len(out) == 2
    assert out[0]["severity"] == "BLOCKER"
    assert out[1]["severity"] == "WARNING"


def test_coefficient_risk_returns_none_without_models():
    assert build_coefficient_risk({}, []) is None


def test_recommended_actions_emits_global_blocked_action():
    actions = recommended_actions("blocked", {}, [])
    assert any(a["action_key"] == "DO_NOT_INTERPRET_UNTIL_BLOCKERS_RESOLVED" for a in actions)


def test_model_identity_falls_back_to_manifest():
    summary = {}
    manifest = {"y": "income", "x": ["age", "education"]}
    model_results = [{"model_id": "primary", "model_type": "ols", "nobs": 100}]
    identity = model_identity(summary, manifest, model_results)
    assert identity["y_variable"] == "income"
    assert identity["x_variables"] == ["age", "education"]
    assert identity["x_variable_count"] == 2
    assert identity["model_type"] == "ols"
    assert identity["n_observations"] == 100
