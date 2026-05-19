from pathlib import Path
from unittest.mock import patch

import pytest

from workbench.report_view_model import build_report_view_model


def test_build_view_model_renders_issues():
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS with robust standard errors"},
        "diagnostics": {
            "blockers": [],
            "warnings": [
                {
                    "code": "TREATMENT_PROXY_CORRELATION",
                    "severity": "WARNING",
                    "template_key": "treatment_proxy_high",
                    "template_params": {"r": "0.791", "treatment": "x8_treatment", "proxy": "x10_interaction_proxy"},
                }
            ],
            "cautions": [],
            "info": [],
        },
        "coefficients_summary": {"rows": []},
        "narrative_contract": {
            "constraints": {"must_acknowledge_treatment_proxy_correlation": True},
            "required_mentions": [],
            "forbidden_claims": [],
        },
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    with patch("workbench.report_view_model.render_template") as mock_render:
        mock_render.return_value = "rendered text"
        view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["title"] == "OLS with robust standard errors"
    assert len(view_model["warnings"]) == 1
    assert view_model["warnings"][0]["text"] == "rendered text"


def test_build_view_model_empty_diagnostics():
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {
            "constraints": {"causal_language_allowed": False},
            "required_mentions": [],
            "forbidden_claims": [],
        },
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    with patch("workbench.report_view_model.render_template"):
        view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["critical_errors"] == []
    assert view_model["warnings"] == []
    assert view_model["cautions"] == []
    assert view_model["system_notes"] == []


# ---- QA edge-case tests ----


def test_estimate_none_coeff_row_does_not_crash():
    """estimate=None should not crash the f-string formatter."""
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS", "y_variable": "y"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": [
            {"variable": "x1", "display_name": "x1", "estimate": None,
             "significance_label": "not reported", "template_key": "coef_continuous_association"},
        ]},
        "narrative_contract": {
            "constraints": {},
            "required_mentions": [],
            "forbidden_claims": [],
        },
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    with patch("workbench.report_view_model.render_template") as mock_render:
        mock_render.return_value = "ok"
        view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert len(view_model["coefficient_interpretations"]) == 1


def test_template_keyerror_falls_back_to_message():
    """When render_template raises KeyError, issue message is used."""
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS"},
        "diagnostics": {
            "blockers": [],
            "warnings": [{"code": "X", "severity": "WARNING", "message": "fallback msg",
                          "template_key": "nonexistent_key", "template_params": {}}],
            "cautions": [],
            "info": [],
        },
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}, "required_mentions": [], "forbidden_claims": []},
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["warnings"][0]["text"] == "fallback msg"


def test_template_valueerror_falls_back_to_message():
    """When render_template raises ValueError (missing params), issue message is used."""
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS"},
        "diagnostics": {
            "blockers": [],
            "warnings": [{"code": "X", "severity": "WARNING", "message": "missing params msg",
                          "template_key": "cook_distance_screening", "template_params": {}}],
            "cautions": [],
            "info": [],
        },
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}, "required_mentions": [], "forbidden_claims": []},
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["warnings"][0]["text"] == "missing params msg"


def test_no_template_key_uses_message():
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS"},
        "diagnostics": {
            "blockers": [],
            "warnings": [{"code": "X", "severity": "WARNING", "message": "plain message"}],
            "cautions": [],
            "info": [],
        },
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}, "required_mentions": [], "forbidden_claims": []},
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["warnings"][0]["text"] == "plain message"


def test_causal_caution_with_treatment():
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "Logistic regression"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {
            "constraints": {"must_not_interpret_treatment_independently": True},
            "required_mentions": [],
            "forbidden_claims": [],
        },
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert "treatment-like variable" in view_model["causal_caution"]


def test_causal_caution_default():
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {
            "constraints": {},
            "required_mentions": [],
            "forbidden_claims": [],
        },
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert "associations" in view_model["causal_caution"].lower()


def test_facts_include_model_label_and_y():
    summary = {
        "schema_version": "1.0",
        "model_identity": {
            "model_label": "Poisson regression",
            "y_variable": "claim_count",
            "x_variables": ["age", "region"],
            "n_observations": 500,
            "dataset_kind": "cross_section",
        },
        "preprocessing": {
            "column_count_after_encoding": 5,
        },
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}, "required_mentions": [], "forbidden_claims": []},
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    facts = view_model["facts"]
    assert any("Poisson" in f for f in facts)
    assert any("claim_count" in f for f in facts)
    assert any("age" in f for f in facts)


def test_facts_mention_categorical():
    summary = {
        "schema_version": "1.0",
        "model_identity": {
            "model_label": "OLS", "y_variable": "y", "x_variables": ["x1", "region"],
            "n_observations": 100, "dataset_kind": "cross_section",
        },
        "preprocessing": {
            "categorical_encoded": [{"variable": "region", "n_levels": 4}],
        },
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}, "required_mentions": [], "forbidden_claims": []},
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    view_model = build_report_view_model(summary, Path("/tmp/fake"))
    facts_text = " ".join(view_model["facts"])
    assert "dummy-coded" in facts_text


def test_coeff_render_failure_yields_empty_text():
    summary = {
        "schema_version": "1.0",
        "model_identity": {"model_label": "OLS", "y_variable": "y"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": [
            {"variable": "x1", "display_name": "x1", "estimate": 0.5,
             "significance_label": "significant", "template_key": "coef_continuous_association"},
        ]},
        "narrative_contract": {"constraints": {}, "required_mentions": [], "forbidden_claims": []},
        "model_quality": {"metrics": {}, "primary_metric_keys": []},
    }
    with patch("workbench.report_view_model.render_template", side_effect=KeyError("boom")):
        view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["coefficient_interpretations"][0]["text"] == ""


def test_empty_summary_does_not_crash():
    summary = {}
    with patch("workbench.report_view_model.render_template") as mock_render:
        mock_render.return_value = "rendered"
        view_model = build_report_view_model(summary, Path("/tmp/fake"))
    assert view_model["title"] == "Econometrics Report"
    assert view_model["critical_errors"] == []
    assert view_model["warnings"] == []
    assert view_model["causal_caution"] == "rendered"
