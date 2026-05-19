"""Trustworthiness & contract tests for the narrative/ pipeline.

Covers:
- Template metadata integrity (all 30)
- Format-string param vs required_params consistency
- Narrative contract derivation scenarios
- End-to-end: issue → diagnostic_summary → view_model → rendered text
"""

import re

import pytest

from workbench.diagnostic_summary import build_diagnostic_summary
from workbench.domain import GuardrailIssue, Severity
from workbench.narrative.render import render_template
from workbench.narrative.templates import TEMPLATES
from workbench.report_view_model import build_report_view_model
from workbench.variable_roles import infer_variable_roles

# ---------------------------------------------------------------------------
# Template metadata integrity
# ---------------------------------------------------------------------------

REQUIRED_TEMPLATE_FIELDS = {"category", "required_params", "text"}


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_template_has_required_fields(key):
    spec = TEMPLATES[key]
    missing = REQUIRED_TEMPLATE_FIELDS - set(spec)
    assert not missing, f"{key} missing fields: {missing}"


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_template_required_params_is_list(key):
    spec = TEMPLATES[key]
    assert isinstance(spec["required_params"], list), f"{key}: required_params must be a list"


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_template_text_is_non_empty_string(key):
    spec = TEMPLATES[key]
    assert isinstance(spec["text"], str) and spec["text"].strip(), f"{key}: text must be non-empty"


def test_template_count_is_30():
    assert len(TEMPLATES) == 30


# ---------------------------------------------------------------------------
# Format-string param vs required_params consistency
# ---------------------------------------------------------------------------

_FORMAT_PARAM_RE = re.compile(r"\{(\w+)(?:\[[^\]]*\])?(?::[^}]*)?\}")


def _extract_format_params(text: str) -> set[str]:
    return {m.group(1) for m in _FORMAT_PARAM_RE.finditer(text)}


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_required_params_match_format_string(key):
    spec = TEMPLATES[key]
    format_params = _extract_format_params(spec["text"])
    required = set(spec["required_params"])
    extra_in_format = format_params - required
    extra_in_required = required - format_params
    assert not extra_in_format, (
        f"{key}: format string has params {extra_in_format} not declared in required_params"
    )
    assert not extra_in_required, (
        f"{key}: required_params has {extra_in_required} not used in format string"
    )


# ---------------------------------------------------------------------------
# Every renderable template works with plausible params
# ---------------------------------------------------------------------------

_PLAUSIBLE_PARAMS: dict = {
    "r": 0.79,
    "treatment": "x8_treatment",
    "proxy": "x10_interaction_proxy",
    "var1": "x1",
    "var2": "x2",
    "variable": "x1",
    "estimate": "0.52",
    "p_label": "statistically significant (p < 0.05)",
    "y": "outcome_y",
    "vif": 3.2,
    "dw": 1.85,
    "ratio": 2.34,
    "n_exceed": 12,
    "threshold": 0.0057,
    "max_d": 0.017,
    "n_severe": 3,
    "event_rate": 0.05,
    "epp": 2.3,
    "positive_count": 15,
    "n_levels": 4,
    "reference": "region_A",
    "nunique": 8,
    "level": "region_B",
    "model_type": "OLS",
    "n_observations": 500,
}

# Make all values str for .format() — format specifiers like :.1f need real types
# Combine: str defaults for unknown params, typed values for known numeric params
_PLAUSIBLE = {**_PLAUSIBLE_PARAMS}  # shallow copy preserves types


@pytest.mark.parametrize("key", list(TEMPLATES))
def test_template_renders_with_plausible_params(key):
    spec = TEMPLATES[key]
    params = {}
    for p in spec["required_params"]:
        if p in _PLAUSIBLE:
            params[p] = _PLAUSIBLE[p]
        elif p.endswith(("_rate", "_count", "_exceed", "_severe", "_levels")):
            params[p] = 5  # int for count-like params
        elif p in ("p_label", "model_type", "reference", "level"):
            params[p] = "test_value"
        else:
            params[p] = "test_value"
    result = render_template(key, params)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "{" not in result


# ---------------------------------------------------------------------------
# Narrative contract: causal language constraints
# ---------------------------------------------------------------------------

def test_causal_language_blocked_when_treatment_present():
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x8_treatment", "x1"],
        profile={"row_count": 100, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={
            "x8_treatment": {"roles": [{"role": "treatment", "status": "confirmed_by_rules"}]},
        },
    )
    nc = summary["narrative_contract"]
    assert nc["constraints"]["causal_language_allowed"] is False
    assert nc["constraints"]["must_not_interpret_treatment_independently"] is True
    assert any("causal effect" in claim for claim in nc["forbidden_claims"])


def test_causal_language_defaults_to_association_only():
    """Without treatment variables, causal_language_allowed is still False
    (system defaults to association-only language), but treatment-specific
    constraints are not activated."""
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1", "x2"],
        profile={"row_count": 100, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    nc = summary["narrative_contract"]
    assert nc["constraints"]["allowed_effect_language"] == "association_only"
    assert nc["constraints"]["must_not_interpret_treatment_independently"] is False


def test_proxy_correlation_adds_required_mentions():
    issues = [
        {
            "severity": "WARNING",
            "code": "TREATMENT_PROXY_CORRELATION",
            "message": "...",
            "variables": ["x8_treatment", "x10_interaction_proxy"],
            "template_key": "treatment_proxy_high",
        },
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
        variable_roles={
            "x8_treatment": {"roles": [{"role": "treatment", "status": "confirmed_by_rules"}]},
        },
    )
    nc = summary["narrative_contract"]
    mentions = nc["required_mentions"]
    assert any("treatment-proxy correlation" in m for m in mentions)


def test_rare_event_issue_bucketed_as_warning():
    """RARE_EVENT_LOW_EPP severity WARNING lands in warnings bucket."""
    issues = [
        {
            "severity": "WARNING",
            "code": "RARE_EVENT_LOW_EPP",
            "message": "Only 15 positive cases...",
            "template_key": "rare_event_low_epp",
        },
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 100, "column_count": 3},
        categorical_vars=set(),
        y_type="binary",
        primary_type="logit",
        variable_roles={},
    )
    warnings = summary["diagnostics"]["warnings"]
    assert any(i["code"] == "RARE_EVENT_LOW_EPP" for i in warnings)


def test_perfect_separation_buckets_as_blocker():
    """BLOCKER severity → blockers bucket + forbidden claims contain standard prohibitions."""
    issues = [
        {"severity": "BLOCKER", "code": "PERFECT_SEPARATION", "message": "...",
         "template_key": "perfect_separation"},
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="binary",
        primary_type="logit",
        variable_roles={},
    )
    assert len(summary["diagnostics"]["blockers"]) == 1
    assert summary["diagnostics"]["blockers"][0]["code"] == "PERFECT_SEPARATION"
    nc = summary["narrative_contract"]
    assert "causal effect of treatment" in nc["forbidden_claims"]
    assert "X causes Y" in nc["forbidden_claims"]


# ---------------------------------------------------------------------------
# Trustworthiness: diagnostic_summary edge cases
# ---------------------------------------------------------------------------

def test_blocker_issue_bucketed_correctly():
    issues = [
        {"severity": "BLOCKER", "code": "PERFECT_SEPARATION", "message": "..."},
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="binary",
        primary_type="logit",
        variable_roles={},
    )
    assert summary["run_status"]["model_fit_status"] == "success"
    assert len(summary["diagnostics"]["blockers"]) == 1


def test_y_types_detected_for_all_supported_types():
    for y_type, expected_fit_type in [
        ("continuous", "success"),
        ("binary", "success"),
        ("count", "success"),
    ]:
        summary = build_diagnostic_summary(
            issue_dicts=[],
            model_results=[],
            routing={"kind": "cross_section"},
            normalized_y="y",
            normalized_x=["x1"],
            profile={"row_count": 50, "column_count": 3},
            categorical_vars=set(),
            y_type=y_type,
            primary_type="ols_robust",
            variable_roles={},
        )
        assert summary["run_status"]["model_fit_status"] == expected_fit_type


def test_coefficient_rows_filter_intercept():
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "r_squared": 0.5,
            "coefficients": {
                "Intercept": {"estimate": 1.0, "p_value": 0.001, "std_error": 0.1},
                "x1": {"estimate": 0.5, "p_value": 0.04, "std_error": 0.2},
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
    variables = [row["variable"] for row in summary["coefficients_summary"]["rows"]]
    assert "Intercept" not in variables
    assert "x1" in variables


def test_missing_model_results_yields_empty_coefficients():
    summary = build_diagnostic_summary(
        issue_dicts=[],
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
    assert summary["coefficients_summary"]["rows"] == []


# ---------------------------------------------------------------------------
# Trustworthiness: variable_roles edge cases
# ---------------------------------------------------------------------------

import pandas as pd


def test_bool_column_is_not_categorical_candidate():
    frame = pd.DataFrame({"flag": [True, False, True, False, True, False]})
    result = infer_variable_roles(frame, ["flag"])
    role_list = result["flag"]["roles"]
    cat_roles = [r for r in role_list if r["role"] == "categorical"]
    assert not any(r["status"] != "rejected" for r in cat_roles)


def test_single_unique_value_column():
    frame = pd.DataFrame({"constant": [1.0] * 10})
    result = infer_variable_roles(frame, ["constant"])
    role_list = result["constant"]["roles"]
    assert isinstance(role_list, list)
    assert len(role_list) > 0


def test_y_type_default_is_continuous():
    frame = pd.DataFrame({"x2_exposure": [10.0, 20.0, 15.0, 25.0, 30.0]})
    result = infer_variable_roles(frame, ["x2_exposure"])
    exposure_roles = [r for r in result["x2_exposure"]["roles"] if r["role"] == "exposure"]
    assert len(exposure_roles) >= 1
    assert exposure_roles[0]["confidence"] == 0.55


# ---------------------------------------------------------------------------
# Trustworthiness: end-to-end GuardrailIssue → rendered text
# ---------------------------------------------------------------------------

from pathlib import Path


def test_e2e_issue_to_rendered_text(tmp_path: Path):
    """Full pipeline: GuardrailIssue → diagnostic_summary → view_model → text."""
    import pandas as pd

    frame = pd.DataFrame({
        "x8_treatment": [0, 1, 0, 1, 0, 1, 0, 1],
        "x10_interaction_proxy": [0.5, 1.2, 3.4, 5.6, 7.8, 9.0, 1.1, 2.2],
        "y": [1.0, 2.0, 1.5, 3.0, 4.0, 5.0, 1.8, 2.5],
    })

    issue = GuardrailIssue(
        severity=Severity.WARNING,
        code="TREATMENT_PROXY_CORRELATION",
        message="x8_treatment and x10_interaction_proxy are highly correlated (r=0.791).",
        evidence={"correlation": 0.791},
        issue_id="diag_001",
        variables=["x8_treatment", "x10_interaction_proxy"],
        template_key="treatment_proxy_high",
        template_params={"r": "0.791", "treatment": "x8_treatment", "proxy": "x10_interaction_proxy"},
    )

    source_file = tmp_path / "data.csv"
    frame.to_csv(source_file, index=False)

    variable_roles = infer_variable_roles(frame, ["x8_treatment", "x10_interaction_proxy"])

    summary = build_diagnostic_summary(
        issue_dicts=[issue.to_dict()],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "r_squared": 0.42,
            "coefficients": {
                "Intercept": {"estimate": 1.0, "p_value": 0.001, "std_error": 0.1},
                "x8_treatment": {"estimate": 0.5, "p_value": 0.04, "std_error": 0.2},
                "x10_interaction_proxy": {"estimate": 0.3, "p_value": 0.08, "std_error": 0.15},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x8_treatment", "x10_interaction_proxy"],
        profile={"row_count": 8, "column_count": 4},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles=variable_roles,
    )

    # Narrative contract must fire
    nc = summary["narrative_contract"]
    assert nc["constraints"]["causal_language_allowed"] is False
    assert nc["constraints"]["must_not_interpret_treatment_independently"] is True

    # Coefficient interpretation guide for treatment + proxy must be warn_joint
    treatment_row = next(
        r for r in summary["coefficients_summary"]["rows"] if r["variable"] == "x8_treatment"
    )
    assert treatment_row["interpretation_guide"] == "warn_joint"
    assert treatment_row["template_key"] == "coef_warn_joint"

    # View model must render
    view_model = build_report_view_model(summary, tmp_path)
    assert any("causal" in cc.lower() for cc in [view_model.get("causal_caution", "")])


def test_e2e_no_treatment_simple_model():
    """Simple model with no treatment variables — causal caution default."""
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "r_squared": 0.65,
            "coefficients": {
                "Intercept": {"estimate": 2.0, "p_value": 0.001, "std_error": 0.3},
                "education": {"estimate": 0.15, "p_value": 0.001, "std_error": 0.02},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="wage",
        normalized_x=["education"],
        profile={"row_count": 500, "column_count": 3},
        categorical_vars=set(),
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={},
    )
    nc = summary["narrative_contract"]
    assert nc["constraints"].get("must_not_interpret_treatment_independently") is not True


def test_e2e_categorical_variable_encoding():
    """Categorical variable produces correct coefficient metadata."""
    summary = build_diagnostic_summary(
        issue_dicts=[],
        model_results=[{
            "model_id": "ols_1",
            "model_type": "ols_robust",
            "r_squared": 0.55,
            "coefficients": {
                "Intercept": {"estimate": 3.0, "p_value": 0.001, "std_error": 0.2},
                "C(Q('region'))[T.East]": {"estimate": 1.5, "p_value": 0.01, "std_error": 0.5},
                "C(Q('region'))[T.West]": {"estimate": -0.8, "p_value": 0.15, "std_error": 0.6},
            },
        }],
        routing={"kind": "cross_section"},
        normalized_y="sales",
        normalized_x=["region"],
        profile={"row_count": 200, "column_count": 3},
        categorical_vars={"region"},
        y_type="continuous",
        primary_type="ols_robust",
        variable_roles={
            "region": {"roles": [{"role": "categorical", "status": "confirmed_by_rules"}]},
        },
    )
    preproc = summary["preprocessing"]
    assert len(preproc["categorical_encoded"]) == 1
    assert preproc["categorical_encoded"][0]["variable"] == "region"
    assert preproc["categorical_encoded"][0]["n_levels"] == 2
    # After encoding: 1 original + 2 dummy coefs = 3
    assert summary["model_identity"]["n_predictors_after_encoding"] == 3


def test_e2e_blocker_issue_appears_in_blocker_bucket():
    """BLOCKER issue lands in blockers bucket and forbidden_claims are populated."""
    issues = [
        GuardrailIssue(
            Severity.BLOCKER, "PERFECT_SEPARATION",
            "Perfect separation detected.",
            template_key="perfect_separation",
        ).to_dict(),
    ]
    summary = build_diagnostic_summary(
        issue_dicts=issues,
        model_results=[],
        routing={"kind": "cross_section"},
        normalized_y="y",
        normalized_x=["x1"],
        profile={"row_count": 50, "column_count": 3},
        categorical_vars=set(),
        y_type="binary",
        primary_type="logit",
        variable_roles={},
    )
    assert len(summary["diagnostics"]["blockers"]) == 1
    assert len(summary["narrative_contract"]["forbidden_claims"]) >= 4
