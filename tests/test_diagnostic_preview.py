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


# ---------------------------------------------------------------------------
# Task 2: Completed run canonical fields
# ---------------------------------------------------------------------------

def test_completed_summary_returns_required_canonical_fields(tmp_path: Path):
    run_root = _run_root(tmp_path)
    write_json(run_root / "diagnostic_summary.json", {
        "schema_version": "1.0",
        "run_id": "r1",
        "run_status": {
            "has_blockers": False,
            "has_warnings": True,
            "model_results_available": True,
            "safe_to_generate_report": True,
        },
        "model_identity": {
            "model_family": "ols",
            "model_label": "OLS regression",
            "y_variable": "wage",
            "x_variables": ["education", "region_code"],
            "n_observations": 700,
        },
        "diagnostics": {
            "blockers": [],
            "warnings": [{"issue_id": "diag_001", "severity": "WARNING", "code": "HIGH_VIF", "message": "High VIF"}],
            "cautions": [{"issue_id": "diag_002", "severity": "CAUTION", "code": "CATEGORICAL_CANDIDATE", "message": "Review category"}],
            "info": [],
        },
        "preprocessing": {"variable_roles": {}},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}},
    })
    manifest = {"run_id": "r1", "status": "completed", "y": "wage", "x": ["education", "region_code"]}

    preview = build_diagnostic_summary_preview(
        run_root,
        manifest,
        model_results=[{"model_id": "ols_1", "model_type": "ols", "coefficients": {}}],
    )

    assert preview["available"] is True
    assert preview["preview_contract_version"] == "1.0"
    assert preview["preview_status"] == "complete"
    assert preview["run_lifecycle_status"] == "completed"
    assert preview["run_status"]["status"] == "usable_with_caution"
    assert preview["run_status"]["safe_to_generate_report"] is True
    assert preview["run_status"]["safe_to_interpret"] == "partial"
    assert preview["trust_label"] == "interpret_with_caution"
    assert preview["trust_counts"] == {"blockers": 0, "warnings": 1, "cautions": 1, "info": 0}
    assert len(preview["primary_reasons"]) == 2
    assert preview["primary_reasons"][0]["severity"] == "WARNING"
    assert preview["primary_reasons"][1]["severity"] == "CAUTION"
    assert preview["model_identity"]["primary_model_id"] == "ols_1"
    assert preview["model_identity"]["model_label"] == "OLS regression"
    assert preview["model_identity"]["y_variable"] == "wage"
    assert preview["model_identity"]["n_observations"] == 700


def test_ok_run_trust_label_and_status():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rr = Path(td) / "run"
        rr.mkdir(parents=True)
        from workbench.artifacts import write_json as wj
        wj(rr / "artifacts_index.json", {"artifacts": []})
        wj(rr / "diagnostic_summary.json", {
            "schema_version": "1.0",
            "run_status": {"has_blockers": False, "has_warnings": False, "safe_to_generate_report": True, "model_results_available": True},
            "model_identity": {"model_family": "ols", "model_label": "OLS", "y_variable": "y", "x_variables": ["x1"], "n_observations": 100},
            "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
            "preprocessing": {"variable_roles": {}},
            "coefficients_summary": {"rows": []},
            "narrative_contract": {"constraints": {}},
        })
        preview = build_diagnostic_summary_preview(
            rr,
            {"run_id": "r1", "status": "completed", "y": "y", "x": ["x1"]},
            [{"model_id": "ols_1", "model_type": "ols", "coefficients": {}}],
        )
        assert preview["run_status"]["status"] == "ok"
        assert preview["trust_label"] == "ready_to_interpret"
        assert preview["run_status"]["safe_to_interpret"] == "yes"


def test_blocked_run_detected_from_blocker_issue():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rr = Path(td) / "run"
        rr.mkdir(parents=True)
        from workbench.artifacts import write_json as wj
        wj(rr / "artifacts_index.json", {"artifacts": []})
        wj(rr / "diagnostic_summary.json", {
            "schema_version": "1.0",
            "run_status": {"has_blockers": True, "has_warnings": False, "safe_to_generate_report": False, "model_results_available": True},
            "model_identity": {"model_family": "logit", "model_label": "Logistic", "y_variable": "y", "x_variables": ["x1"], "n_observations": 50},
            "diagnostics": {
                "blockers": [{"severity": "BLOCKER", "code": "PERFECT_SEPARATION", "message": "Perfect separation"}],
                "warnings": [], "cautions": [], "info": [],
            },
            "preprocessing": {"variable_roles": {}},
            "coefficients_summary": {"rows": []},
            "narrative_contract": {"constraints": {}},
        })
        preview = build_diagnostic_summary_preview(
            rr,
            {"run_id": "r1", "status": "completed", "y": "y", "x": ["x1"]},
            [{"model_id": "logit_1", "model_type": "logit", "coefficients": {}}],
        )
        assert preview["run_status"]["status"] == "blocked"
        assert preview["trust_label"] == "not_ready_to_interpret"
        assert preview["run_status"]["safe_to_interpret"] == "no"
        assert preview["run_status"]["safe_to_generate_report"] is False


# ---------------------------------------------------------------------------
# Task 3: coefficient risk, restrictions, actions
# ---------------------------------------------------------------------------

def test_coefficient_risk_groups_dummy_terms_by_original_variable(tmp_path: Path):
    run_root = _run_root(tmp_path)
    write_json(run_root / "diagnostic_summary.json", {
        "schema_version": "1.0",
        "run_status": {"has_blockers": False, "has_warnings": True, "safe_to_generate_report": True, "model_results_available": True},
        "model_identity": {"model_family": "ols", "model_label": "OLS regression", "y_variable": "wage", "x_variables": ["region_code"], "n_observations": 100},
        "preprocessing": {
            "variable_roles": {
                "region_code": {"roles": [{"role": "categorical", "status": "confirmed_by_rules", "confidence": 0.85, "needs_user_confirmation": False}]}
            },
            "categorical_encoded": [{"variable": "region_code", "reference": "1", "n_levels": 3}],
        },
        "diagnostics": {
            "blockers": [],
            "warnings": [{"issue_id": "diag_003", "severity": "WARNING", "code": "CATEGORICAL_AUTO_DUMMY_CODED", "message": "Dummy coded", "variables": ["region_code"]}],
            "cautions": [],
            "info": [],
        },
        "coefficients_summary": {"rows": [
            {"variable": "C(Q('region_code'))[T.2]", "display_name": "region_code", "level": "2", "estimate": 1.23, "p_value": 0.04, "linked_issues": ["diag_003"]},
            {"variable": "C(Q('region_code'))[T.3]", "display_name": "region_code", "level": "3", "estimate": 0.50, "p_value": 0.20, "linked_issues": ["diag_003"]},
        ]},
        "narrative_contract": {"constraints": {}},
    })
    manifest = {"run_id": "r1", "status": "completed", "y": "wage", "x": ["region_code"]}
    model_results = [{"model_id": "ols_1", "model_type": "ols", "coefficients": {"C(Q('region_code'))[T.2]": {"estimate": 1.23}}}]

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results)

    risk = preview["coefficient_risk"]
    assert risk["primary_model_id"] == "ols_1"
    group = risk["models"][0]["risk_groups"][0]
    assert group["variable"] == "region_code"
    assert group["variable_kind"] == "dummy_coded"
    assert group["risk_level"] == "WARNING"
    assert group["interpretation_guide"] == "categorical_levels_vs_reference"
    assert group["role_summary"]["role"] == "categorical"
    assert group["terms"][0]["display_term"] == "region_code = 2"
    assert group["terms"][0]["reference_level"] == "1"
    assert "source_id" in group["terms"][0]
    assert group["terms"][0]["source_id"] == "model_results.ols_1.coefficients.C(Q('region_code'))[T.2]"


def test_restrictions_and_actions_include_treatment_proxy_and_causal_limits(tmp_path: Path):
    run_root = _run_root(tmp_path)
    write_json(run_root / "diagnostic_summary.json", {
        "schema_version": "1.0",
        "run_status": {"has_blockers": False, "has_warnings": True, "safe_to_generate_report": True, "model_results_available": True},
        "model_identity": {"model_family": "ols", "model_label": "OLS regression", "y_variable": "y", "x_variables": ["x8_treatment", "x10_proxy"], "n_observations": 100},
        "preprocessing": {"variable_roles": {"x8_treatment": {"roles": [{"role": "treatment", "status": "confirmed_by_rules"}]}}},
        "diagnostics": {
            "blockers": [],
            "warnings": [{"issue_id": "diag_001", "severity": "WARNING", "code": "TREATMENT_PROXY_CORRELATION", "message": "Interpret jointly", "variables": ["x8_treatment", "x10_proxy"]}],
            "cautions": [],
            "info": [],
        },
        "coefficients_summary": {"rows": []},
        "narrative_contract": {
            "constraints": {
                "causal_language_allowed": False,
                "must_not_interpret_treatment_independently": True,
                "must_acknowledge_treatment_proxy_correlation": True,
            }
        },
    })

    preview = build_diagnostic_summary_preview(
        run_root,
        {"run_id": "r1", "status": "completed", "y": "y", "x": ["x8_treatment", "x10_proxy"]},
        [{"model_id": "ols_1", "model_type": "ols", "coefficients": {}}],
    )

    restriction_types = {item["restriction_type"] for item in preview["interpretation_restrictions"]}
    assert {"causal", "treatment_proxy"} <= restriction_types
    action_keys = {item["action_key"] for item in preview["recommended_actions"]}
    assert "INTERPRET_TREATMENT_PROXY_JOINTLY" in action_keys
    assert "REVIEW_CAUTIONS_BEFORE_INTERPRETING" in action_keys


# ---------------------------------------------------------------------------
# Regression: a completed pack result without a classic coefficient table
# (e.g. ARMA-GARCH) must not be mislabelled "run failed".
# ---------------------------------------------------------------------------

def test_completed_run_without_coefficient_table_is_not_run_failed(tmp_path: Path):
    run_root = _run_root(tmp_path)
    write_json(run_root / "diagnostic_summary.json", {
        "schema_version": "1.0",
        "run_id": "r1",
        "run_status": {
            "has_blockers": False,
            "has_warnings": False,
            "model_results_available": True,
            "safe_to_generate_report": True,
        },
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
    })
    manifest = {"run_id": "r1", "status": "completed", "y": "price", "x": []}

    # The coefficient projection surfaces nothing for a time-series pack result,
    # so model_results reaches the preview empty even though the run succeeded.
    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["available"] is True
    assert preview["trust_label"] == "ready_to_interpret"
    assert preview["run_status"]["status"] == "ok"
    assert preview["run_status"]["model_results_available"] is True


def test_completed_run_without_results_stays_run_failed(tmp_path: Path):
    run_root = _run_root(tmp_path)
    write_json(run_root / "diagnostic_summary.json", {
        "schema_version": "1.0",
        "run_id": "r1",
        "run_status": {
            "has_blockers": False,
            "has_warnings": False,
            "model_results_available": False,
            "safe_to_generate_report": False,
        },
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
    })
    manifest = {"run_id": "r1", "status": "completed", "y": "price", "x": []}

    preview = build_diagnostic_summary_preview(run_root, manifest, model_results=[])

    assert preview["trust_label"] == "run_failed"
