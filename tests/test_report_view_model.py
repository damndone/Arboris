from pathlib import Path
from unittest.mock import patch
import json
import tempfile

import pytest

from workbench.report_view_model import build_report_view_model
from tests.test_v189_evidence_report_boundary import (
    _owner_wire,
    _report_projection_wire,
    _server_owned_evidence,
)


def _typed_projection() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "projectionId": "report:evidence-commit-1",
        "consumerId": "report",
        "consumerVersion": "1.0",
        "actorRef": "actor:1",
        "projectRef": "project:1",
        "sessionRef": "session:1",
        "scopeRef": "scope:project:1",
        "runId": "run-1",
        "modelRunId": "run-1",
        "artifactRef": "artifact-1",
        "commitId": "evidence-commit-1",
        "confirmationRef": "confirmation:run-1",
        "envelopeRef": "evidence-envelope:1",
        "envelopeDigest": "a" * 64,
        "status": "available",
        "executionStatus": "completed",
        "availability": "available",
        "completenessStatus": "complete",
        "validationStatus": "met",
        "validationSummary": {"requirement_status": "met"},
        "facts": [
            {"factId": "fact-1", "statisticId": "estimate", "value": 1.25},
            {"factId": "fact-2", "statisticId": "standard-error", "value": 0.2},
        ],
        "sections": [],
        "provenance": {"artifactRef": "artifact-1", "commitId": "evidence-commit-1"},
    }


def _build(summary: dict) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with _server_owned_evidence(root / "owner-store") as (record, _binding, owner):
            wire = _owner_wire(owner, _report_projection_wire())
            wire["envelopeDigest"] = record.envelope_digest
            projection = owner.issue_report_projection(wire)
            return build_report_view_model(
                summary,
                root / "run-1",
                evidence_projection=projection,
                owner=owner,
                artifact_admission=owner._canonical_report_artifact(),  # type: ignore[attr-defined]
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
        view_model = _build(summary)
    assert view_model["status"] == "available"
    assert view_model["validationStatus"] == "met"
    assert str(view_model["commitId"]).startswith("commit:evidence:")
    assert view_model["warnings"][0]["text"] == "rendered text"
    assert mock_render.call_count >= 1


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
        view_model = _build(summary)
    assert view_model["status"] == "available"
    assert [fact["value"] for fact in view_model["facts"]] == [2.0, 0.2]
    assert view_model["title"] == "OLS"
    assert view_model["causal_caution"]


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
        view_model = _build(summary)
    assert view_model["status"] == "available"
    assert view_model["facts"][0]["value"] == 2
    assert len(view_model["coefficient_interpretations"]) == 1
    assert mock_render.call_count >= 1


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
    view_model = _build(summary)
    assert view_model["status"] == "available"
    assert view_model["critical_errors"] == []
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
    view_model = _build(summary)
    assert view_model["status"] == "available"
    assert view_model["critical_errors"] == []
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
    view_model = _build(summary)
    assert view_model["status"] == "available"
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
    view_model = _build(summary)
    assert view_model["status"] == "available"
    assert view_model["validationSummary"]["requirement_status"] == "met"
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
    view_model = _build(summary)
    assert view_model["status"] == "available"
    assert isinstance(view_model["envelopeDigest"], str)
    assert len(view_model["envelopeDigest"]) == 64
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
    view_model = _build(summary)
    facts = view_model["facts"]
    assert [fact["value"] for fact in facts] == [2, 0.2]
    assert any("Poisson regression" in fact for fact in view_model["presentation_facts"])
    assert any("claim_count" in fact for fact in view_model["presentation_facts"])


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
    view_model = _build(summary)
    assert view_model["status"] == "available"
    assert "dummy-coded" in " ".join(view_model["presentation_facts"])


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
        view_model = _build(summary)
    assert view_model["status"] == "available"
    assert any("standardError" in fact for fact in view_model["facts"])
    assert view_model["coefficient_interpretations"][0]["text"] == ""


def test_empty_summary_does_not_crash():
    summary = {}
    with patch("workbench.report_view_model.render_template") as mock_render:
        mock_render.return_value = "rendered"
        view_model = _build(summary)
    assert view_model["status"] == "available"
    assert view_model["critical_errors"] == []
    assert str(view_model["projectionId"]).startswith("report:commit:evidence:")
    assert mock_render.call_count >= 1
