from pathlib import Path
from unittest.mock import patch

import pytest

from workbench.report_view_model import (
    build_regression_table,
    build_report_view_model,
    regression_table_export_rows,
    _survey_design_facts,
)


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


def test_report_projection_omits_absent_survey_fields():
    """Report packets must not invent optional survey metadata placeholders."""
    packet = build_regression_table(
        [
            (
                "ols_1",
                {
                    "model_id": "ols_1",
                    "model_type": "ols",
                    "coefficients": {"x": {"estimate": 1.0}},
                },
            )
        ]
    )

    model = packet["models"][0]
    assert "survey_design" not in model
    assert "survey_provenance" not in model
    assert all(
        "ols_1 survey design" not in row
        for row in regression_table_export_rows(packet)
    )


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


def test_report_facts_preserve_bounded_survey_replicate_metadata(tmp_path: Path):
    """Facts must qualify design-based precision with replicate outcome status."""
    result = {
        "model_id": "ols_1",
        "model_label": "Survey OLS",
        "survey_design": {
            "variance_method": "replicate",
            "strata_column": "stratum",
            "psu_column": "psu",
            "n_strata": 2,
            "n_psu": 6,
            "degf": 4,
            "replicates_attempted": 12,
            "replicates_succeeded": 10,
            "replicates_failed": 2,
            "replicate_failure_reasons": {"ValueError": 2},
        },
        "coefficients": {
            "x": {
                "variance_source": "survey_design",
                "source_id": "model_results.ols_1.coefficients.x",
                "warnings": ["SURVEY_REPLICATE_FAILURES"],
            }
        },
    }
    regression_table = build_regression_table([("ols_1", result)])

    view_model = build_report_view_model(
        {
            "model_identity": {
                "model_label": "Survey OLS",
                "y_variable": "y",
                "x_variables": ["x"],
                "n_observations": 12,
                "dataset_kind": "cross_section",
            },
            "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
            "coefficients_summary": {"rows": []},
            "narrative_contract": {"constraints": {}},
        },
        tmp_path,
        regression_table=regression_table,
    )

    facts_text = " ".join(view_model["facts"])
    assert "replicates attempted=12" in facts_text
    assert "succeeded=10" in facts_text
    assert "failed=2" in facts_text
    assert "ValueError=2" in facts_text
    assert "variance_source=survey_design" in facts_text
    assert "SURVEY_REPLICATE_FAILURES" in facts_text


def test_report_projection_fails_closed_on_huge_coefficient_and_replicate_values():
    """Report projection must not copy unbounded numeric precision into output."""
    packet = build_regression_table(
        [
            (
                "ols_1",
                {
                    "model_label": "Survey OLS",
                    "survey_design": {
                        "replicates_attempted": 10**400,
                        "replicates_succeeded": 10**400,
                        "replicates_failed": 10**400,
                    },
                    "coefficients": {
                        "x": {
                            "estimate": 10**400,
                            "std_error": 10**400,
                            "p_value": 10**400,
                            "confidence_interval": [10**400, 10**400],
                            "source_id": "model_results." + "x" * 2000,
                            "variance_source": "survey_design",
                            "warnings": ["warning"] * 100,
                        }
                    },
                },
            )
        ]
    )

    cell = packet["rows"][0]["models"]["ols_1"]
    assert cell["projection_status"] == "unavailable"
    assert cell["unavailable_reason"] == "REPORT_COEFFICIENT_VALUE_INVALID"
    assert "estimate" not in cell
    provenance = packet["models"][0]["survey_provenance"]
    assert provenance["projection_status"] == "unavailable"
    assert provenance["unavailable_reason"] == "REPORT_SURVEY_METADATA_INVALID"


@pytest.mark.parametrize("field,value", [
    ("n_obs", -1),
    ("n_psu", 1.5),
    ("degf", 10**400),
    ("residual_degf", -2),
    ("design_effect", float("inf")),
    ("effective_sample_size", -1),
])
def test_report_design_counts_and_effects_are_typed_unavailable(field, value):
    survey_design = {
        "n_obs": 10,
        "n_strata": 2,
        "n_psu": 4,
        "degf": 2,
        "residual_degf": 1,
        "design_effect": 1.2,
        "effective_sample_size": 8,
    }
    survey_design[field] = value
    packet = build_regression_table([
        (
            "ols_1",
            {
                "model_type": "ols",
                "nobs": 10,
                "survey_design": survey_design,
                "coefficients": {"x": {"estimate": 1.0, "std_error": 0.2, "p_value": 0.1}},
            },
        )
    ])
    assert packet["models"][0]["survey_provenance"]["projection_status"] == "unavailable"
    assert packet["models"][0]["survey_provenance"]["unavailable_reason"] == "REPORT_SURVEY_METADATA_INVALID"


def test_report_and_xlsx_propagate_unavailable_design_without_design_claims():
    result = {
        "model_type": "ols",
        "nobs": 10,
        "survey_design": {
            "n_obs": -1,
            "n_strata": 2,
            "n_psu": 4,
            "degf": 2,
            "variance_method": "linearization",
        },
        "coefficients": {
            "x": {"estimate": 1.0, "std_error": 0.2, "p_value": 0.2}
        },
    }

    packet = build_regression_table([("ols_1", result)])
    model = packet["models"][0]
    assert model["survey_design"]["projection_status"] == "unavailable"
    assert model["survey_provenance"]["projection_status"] == "unavailable"
    assert "design-based" not in str(model["survey_design"])
    assert "design-based" not in " ".join(_survey_design_facts(packet))

    rows = regression_table_export_rows(packet)
    assert rows[0]["ols_1 survey design"]["projection_status"] == "unavailable"


def test_unavailable_survey_design_does_not_copy_invalid_safe_metadata():
    from workbench.survey.projection import project_survey_design

    projected = project_survey_design(
        {
            "projection_status": "unavailable",
            "unavailable_reason": "upstream_invalid",
            "variance_method": "linearization",
            "variance_source": 10**400,
            "source_id": False,
            "warnings": [10**400],
            "provenance": {"run_id": "run-1"},
        }
    )

    assert projected["projection_status"] == "unavailable"
    assert projected["unavailable_reason"] == "upstream_invalid"
    assert projected["variance_method"] == "linearization"
    assert "variance_source" not in projected
    assert "source_id" not in projected
    assert "warnings" not in projected
    assert projected["provenance"] == {"run_id": "run-1"}


def test_xlsx_preserves_typed_unavailable_coefficient_projection():
    packet = build_regression_table(
        [
            (
                "ols_1",
                {
                    "model_type": "ols",
                    "coefficients": {
                        "x": {
                            "estimate": 1.0,
                            "std_error": -1,
                            "p_value": 0.2,
                        }
                    },
                },
            )
        ]
    )

    rows = regression_table_export_rows(packet)
    assert rows[0]["ols_1 projection_status"] == "unavailable"
    assert rows[0]["ols_1 unavailable_reason"] == "REPORT_COEFFICIENT_VALUE_INVALID"
    assert rows[0]["ols_1 std_error"] is None


@pytest.mark.parametrize("field,value", [("std_error", -1), ("p_value", 2), ("ci_lower", float("inf"))])
def test_report_coefficient_inference_values_are_not_copied(field, value):
    packet = build_regression_table([
        ("ols_1", {"model_type": "ols", "coefficients": {"x": {
            "estimate": 1.0, "std_error": 0.2, "p_value": 0.1,
            "confidence_interval": [0.5, 1.5],
        }}})
    ])
    source = packet["rows"][0]["models"]["ols_1"]
    source[field] = value
    rows = regression_table_export_rows(packet)
    cell = rows[0]["ols_1 estimate"]
    assert cell is None
    assert rows[0]["ols_1 projection_status"] == "unavailable"


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
