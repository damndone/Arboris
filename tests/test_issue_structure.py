from workbench.domain import GuardrailIssue, Severity


def test_guardrail_issue_has_all_fields():
    issue = GuardrailIssue(
        severity=Severity.WARNING,
        code="TREATMENT_PROXY_CORRELATION",
        message="x8_treatment and x10_interaction_proxy are highly correlated (r=0.791).",
        evidence={"correlation": 0.791},
        issue_id="diag_001",
        affected_stage="interpretation",
        variables=["x8_treatment", "x10_interaction_proxy"],
        metric="pearson_r",
        value=0.791,
        threshold=0.7,
        template_key="treatment_proxy_high",
        template_params={"r": "0.791", "treatment": "x8_treatment", "proxy": "x10_interaction_proxy"},
        recommended_action_key="interpret_jointly",
        is_user_action_required=False,
    )
    d = issue.to_dict()
    assert d["severity"] == "WARNING"
    assert d["code"] == "TREATMENT_PROXY_CORRELATION"
    assert d["issue_id"] == "diag_001"
    assert d["affected_stage"] == "interpretation"
    assert d["variables"] == ["x8_treatment", "x10_interaction_proxy"]
    assert d["metric"] == "pearson_r"
    assert d["value"] == 0.791
    assert d["threshold"] == 0.7
    assert d["template_key"] == "treatment_proxy_high"
    assert d["template_params"] == {"r": "0.791", "treatment": "x8_treatment", "proxy": "x10_interaction_proxy"}
    assert d["recommended_action_key"] == "interpret_jointly"
    assert d["is_user_action_required"] is False


def test_guardrail_issue_backward_compatible():
    issue = GuardrailIssue(
        severity=Severity.INFO,
        code="CATEGORICAL_AUTO_DUMMY_CODED",
        message="Column 'x7_region_code' was detected as categorical and automatically dummy-coded.",
    )
    d = issue.to_dict()
    assert d["severity"] == "INFO"
    assert d["code"] == "CATEGORICAL_AUTO_DUMMY_CODED"
    assert d["issue_id"] == ""
    assert d["template_key"] == ""


def test_guardrail_issue_variables_is_tuple_internally():
    issue = GuardrailIssue(
        severity=Severity.INFO,
        code="TEST",
        message="test",
        variables=["a", "b"],
    )
    assert isinstance(issue.variables, tuple)
