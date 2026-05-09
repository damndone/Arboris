import pytest
from workbench.diagnostic_summary import build_diagnostic_summary


# ---- existing 4 tests ----

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


# ---- QA edge-case tests ----

def test_severity_none_falls_to_info():
    issues = [
        {"severity": None, "code": "X", "message": "x"},
        {"severity": "UNKNOWN_LEVEL", "code": "Y", "message": "y"},
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
    # Both None and unknown strings land in info bucket
    assert len(summary["diagnostics"]["info"]) == 2
    assert len(summary["diagnostics"]["blockers"]) == 0
    assert len(summary["diagnostics"]["warnings"]) == 0
    assert len(summary["diagnostics"]["cautions"]) == 0


def test_c_encoded_treatment_var_detects_proxy_correlation():
    """C()-encoded treatment terms must still match proxy correlation issues."""
    issues = [
        {"severity": "WARNING", "code": "TREATMENT_PROXY_CORRELATION",
         "message": "...", "variables": ["x8_treatment", "x10_interaction_proxy"],
         "issue_id": "diag_001"},
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "r_squared": 0.42,
            "coefficients": {
                "Intercept": {"estimate": 1.0, "p_value": 0.001, "std_error": 0.1},
                "C(Q('x8_treatment'))[T.1]": {"estimate": 0.5, "p_value": 0.04, "std_error": 0.2},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x8_treatment", "x10_interaction_proxy"],
        profile={"row_count": 50, "column_count": 4},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={"x8_treatment": {"roles": [{"role": "treatment", "status": "confirmed_by_rules"}]},
                        "x10_interaction_proxy": {"roles": [{"role": "proxy", "status": "candidate"}]}},
    )
    row = summary["coefficients_summary"]["rows"][0]
    assert row["interpretation_guide"] == "warn_joint"
    assert "diag_001" in row["linked_issues"]
    assert row["template_key"] == "coef_warn_joint"


def test_treatment_var_no_proxy_sets_guide_correctly():
    """Treatment variable without proxy correlation should get treatment_direct guide."""
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "r_squared": 0.42,
            "coefficients": {
                "Intercept": {"estimate": 1.0, "p_value": 0.001, "std_error": 0.1},
                "x8_treatment": {"estimate": 0.5, "p_value": 0.04, "std_error": 0.2},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x8_treatment", "x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={"x8_treatment": {"roles": [{"role": "treatment", "status": "confirmed_by_rules"}]}},
    )
    row = summary["coefficients_summary"]["rows"][0]
    assert row["interpretation_guide"] == "treatment_direct"
    assert row["template_key"] == "coef_binary_association"


def test_p_value_none_returns_not_reported():
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "coefficients": {
                "x1": {"estimate": 0.5, "p_value": None, "std_error": 0.2},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    row = summary["coefficients_summary"]["rows"][0]
    assert row["significance_label"] == "not reported"
    assert row["p_value"] is None


def test_dropped_vars_affects_predictor_count():
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1", "x2", "x3"],
        profile={"row_count": 100, "column_count": 5},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
        dropped_vars=["x3 (dropped due to zero variance)"],
    )
    assert summary["model_identity"]["n_predictors_original"] == 3
    assert summary["model_identity"]["n_predictors_after_encoding"] == 2


def test_categorical_dummy_coefs_increase_predictor_count():
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "coefficients": {
                "Intercept": {"estimate": 1.0, "p_value": 0.001},
                "x1": {"estimate": 0.5, "p_value": 0.04},
                "C(Q('x7_region_code'))[T.2]": {"estimate": -0.1, "p_value": 0.3},
                "C(Q('x7_region_code'))[T.3]": {"estimate": 0.2, "p_value": 0.1},
                "C(Q('x7_region_code'))[T.4]": {"estimate": 0.05, "p_value": 0.6},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1", "x7_region_code"],
        profile={"row_count": 100, "column_count": 3},
        categorical_vars={"x7_region_code"},
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    # 2 original - 0 dropped + 3 dummy coefs = 5
    assert summary["model_identity"]["n_predictors_after_encoding"] == 5
    cat = summary["preprocessing"]["categorical_encoded"]
    assert len(cat) == 1
    assert cat[0]["n_levels"] == 3  # count of C()-encoded terms


def test_estimate_zero_is_not_skipped():
    """estimate=0.0 is a valid coefficient, not a missing value."""
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "coefficients": {
                "x1": {"estimate": 0.0, "p_value": 0.5, "std_error": 0.1},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    assert len(summary["coefficients_summary"]["rows"]) == 1
    assert summary["coefficients_summary"]["rows"][0]["estimate"] == 0.0


def test_y_type_affects_primary_metric_keys():
    for y_type, expected_key in [("binary", "pseudo_r2"), ("count", "aic"), ("continuous", "r_squared")]:
        summary = build_diagnostic_summary(
            issue_dicts=[],
            model_results=[{
                "model_id": "m",
                "model_type": "logit" if y_type == "binary" else ("poisson" if y_type == "count" else "ols"),
                "r_squared": 0.5, "pseudo_r2": 0.3, "aic": 100.0, "bic": 110.0,
                "coefficients": {},
            }],
            routing={"kind": "cross_section"},
            normalized_y="y",
            normalized_x=["x1"],
            profile={"row_count": 50, "column_count": 3},
            categorical_vars=set(),
            y_type=y_type,
            primary_type="ols_robust",
            variable_roles={},
        )
        keys = summary["model_quality"]["primary_metric_keys"]
        assert expected_key in keys, f"y_type={y_type}: expected {expected_key} in {keys}"
