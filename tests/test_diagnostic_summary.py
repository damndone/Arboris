from workbench.diagnostic_summary import build_diagnostic_summary


def test_build_minimal_summary():
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1", "x2"],
        profile={"row_count": 100, "column_count": 5},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    assert summary["schema_version"] == "1.0"
    assert "run_id" in summary
    assert summary["run_status"]["model_fit_status"] == "success"
    assert summary["model_identity"]["n_predictors_original"] == 2
    assert summary["diagnostics"] == {"blockers": [], "warnings": [], "cautions": [], "info": []}


def test_build_summary_sorts_issues_by_severity():
    issues = [
        {"severity": "CAUTION", "code": "C", "message": "c"},
        {"severity": "BLOCKER", "code": "A", "message": "a"},
        {"severity": "WARNING", "code": "B", "message": "b"},
        {"severity": "INFO", "code": "D", "message": "d"},
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    assert len(summary["diagnostics"]["blockers"]) == 1
    assert summary["diagnostics"]["blockers"][0]["code"] == "A"
    assert len(summary["diagnostics"]["warnings"]) == 1
    assert summary["diagnostics"]["warnings"][0]["code"] == "B"
    assert len(summary["diagnostics"]["cautions"]) == 1
    assert summary["diagnostics"]["cautions"][0]["code"] == "C"
    assert len(summary["diagnostics"]["info"]) == 1
    assert summary["diagnostics"]["info"][0]["code"] == "D"


def test_build_summary_with_model_results():
    issues = []
    model_results = [{
        "model_id": "ols_1",
        "model_type": "ols_robust",
        "r_squared": 0.42,
        "f_statistic": 12.3,
        "f_p_value": 0.001,
        "aic": 1234.5,
        "bic": 1280.1,
        "coefficients": {
            "Intercept": {"estimate": 1.0, "p_value": 0.001, "std_error": 0.1},
            "x1": {"estimate": 0.5, "p_value": 0.04, "std_error": 0.2},
        },
    }]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=model_results,
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 100, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    assert summary["model_quality"]["metrics"]["r_squared"] == 0.42
    assert len(summary["coefficients_summary"]["rows"]) == 1  # x1, not Intercept


def test_build_summary_includes_narrative_contract():
    issues = [
        {"severity": "WARNING", "code": "TREATMENT_PROXY_CORRELATION", "message": "...",
         "variables": ["x8_treatment", "x10_interaction_proxy"], "template_key": "treatment_proxy_high"},
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x8_treatment", "x10_interaction_proxy"],
        profile={"row_count": 50, "column_count": 4},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={"x8_treatment": {"roles": [{"role": "treatment", "status": "confirmed_by_rules"}]}},
    )
    nc = summary["narrative_contract"]
    assert nc["constraints"]["causal_language_allowed"] is False
    assert "treatment-proxy correlation" in nc["required_mentions"]
    assert any("causal effect" in claim for claim in nc["forbidden_claims"])
    assert nc["constraints"]["must_not_interpret_treatment_independently"] is True
