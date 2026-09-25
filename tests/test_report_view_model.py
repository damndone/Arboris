from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import json
import tempfile
from types import SimpleNamespace

import pytest

from workbench.canonical import sha256_canonical
from workbench.narrative.render import render_template as real_render_template
from workbench.report_view_model import (
    _survey_design_facts,
    build_regression_table,
    build_report_view_model,
    regression_table_export_rows,
)
from tests.test_v189_evidence_report_boundary import (
    _produced_report,
    _owner_wire,
    _report_projection_wire,
    _server_owned_evidence,
)


def test_structured_report_projection_preserves_values_and_declared_sections():
    from tests.test_v189_result_sections import _parse, _section, _facts
    from workbench.report_view_model import _structured_report_fields
    projection = SimpleNamespace(sections=(_parse(_section()),), facts=tuple(_facts().values()))
    fields = _structured_report_fields(projection)
    assert fields["structuredResults"]["sections"] == [_section()]
    section = fields["resolvedSections"][0]
    assert section["content"]["results"][0]["p_value"] == 1.25e-24
    assert section["sectionId"] == "test:x"
    assert fields["statistical_evidence"]["results"][0]["label"] == "<script>untrusted label</script>"


def test_report_document_binding_rejects_unbound_structured_and_presentation_fields():
    from workbench.reporting import _validate_bound_report_view_model
    from copy import deepcopy
    wire = _typed_projection()
    wire["envelopeRef"] = "evidence-envelope:1"
    wire["provenance"]["envelopeRef"] = "evidence-envelope:1"
    wire["structuredResults"] = {"sections": []}
    wire["resolvedSections"] = []
    wire["regression_table"] = None
    projection = SimpleNamespace(wire=wire)
    _validate_bound_report_view_model(deepcopy(wire), projection)
    for key, value in (("resolvedSections", [{"content": 99}]),
                       ("structuredResults", {"sections": [99]}),
                       ("regression_table", {"rows": [{"estimate": 99}]}),
                       ("invented_output", {"value": 99})):
        payload = deepcopy(wire); payload[key] = value
        with pytest.raises(TypeError):
            _validate_bound_report_view_model(payload, projection)


def test_admitted_diagnostic_sections_render_text_without_legacy_reads():
    from tests.test_v189_result_sections import _parse, _section
    from workbench.report_view_model import _structured_report_fields
    def node(value):
        if isinstance(value, str):
            return {"kind": "text", "value": value}
        if isinstance(value, list):
            return {"kind": "list", "items": [node(item) for item in value]}
        return {"kind": "object", "fields": {key: node(item) for key, item in value.items()}}
    wire = _section()
    wire.update(section_type="diagnostics", fact_refs=[], content=node({
        "blockers": [], "warnings": [{"code": "W", "severity": "WARNING",
            "template_key": "existing-template", "template_params": {"variable": "x"},
            "message": "Declared fallback", "variables": ["x"]}], "cautions": [], "info": []}))
    projection = SimpleNamespace(sections=(_parse(wire),), facts=())
    with patch("workbench.report_view_model.render_template", return_value="Rendered warning") as render:
        fields = _structured_report_fields(projection)
    assert fields["warnings"][0]["text"] == "Rendered warning"
    assert fields["warnings"][0]["code"] == "W"
    render.assert_called_once_with("existing-template", {"variable": "x"})
    with patch("workbench.report_view_model.render_template", side_effect=KeyError("unknown")):
        fields = _structured_report_fields(projection)
    assert fields["warnings"][0]["text"] == "Declared fallback"
    assert fields["resolvedSections"][0]["content"]["warnings"][0]["message"] == "Declared fallback"


@pytest.mark.parametrize("unknown_model", [False, True])
def test_admitted_model_title_and_caution_are_not_lost(unknown_model):
    from tests.test_v189_result_sections import _parse, _section
    from workbench.report_view_model import _structured_report_fields
    def node(value):
        if value is None:
            return {"kind": "null"}
        if type(value) is bool:
            return {"kind": "boolean", "value": value}
        if isinstance(value, str):
            return {"kind": "text", "value": value}
        if isinstance(value, list):
            return {"kind": "list", "items": [node(item) for item in value]}
        return {"kind": "object", "fields": {key: node(item) for key, item in value.items()}}
    identity = _section()
    models = [{"id": "model.with.dots", "label": "Poisson regression", "y_variable": "claim_count",
               "x_variables": ["age", "region"]}]
    if unknown_model:
        models.append(None)
    identity.update(section_id="identity", section_type="model_identity", fact_refs=[], content=node({"models": models}))
    caution = _section()
    caution.update(section_id="constraints", section_type="interpretation_constraints", fact_refs=[], content=node({
        "constraints": {"must_not_interpret_treatment_independently": True},
        "required_mentions": [], "forbidden_claims": []}))
    fields = _structured_report_fields(SimpleNamespace(sections=(_parse(identity), _parse(caution)), facts=()))
    assert fields["title"] == ("Econometrics Report" if unknown_model else "Poisson regression")
    assert fields["resolvedSections"][0]["content"]["models"] == models
    assert "treatment-like variable" in fields["causal_caution"]
    assert any("claim_count" in line and "age" in line for line in fields["presentation_facts"])


@pytest.mark.parametrize("missing", [None, {"status": "unavailable", "reason": "not measured"}])
def test_admitted_template_missing_numbers_preserve_declared_message(missing):
    from workbench.report_view_model import _render_admitted_issue
    issue = {"code": "RARE_EVENT", "template_key": "rare_event_low_epp",
             "template_params": {"event_rate": missing, "epp": missing, "positive_count": missing},
             "message": "Event precision has not been measured"}
    assert _render_admitted_issue(issue)["text"] == issue["message"]
    assert issue["template_params"]["event_rate"] == missing


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


def _build(
    summary: dict,
    *,
    model_results: dict[str, dict],
    report_fields: dict | None = None,
) -> dict[str, object]:
    """Exercise real producer admission, not a numeric-only owner plus raw summary."""
    with tempfile.TemporaryDirectory() as directory:
        run_root = Path(directory) / "project" / "runs" / "run-1"
        with _produced_report(
            run_root,
            model_results=deepcopy(model_results),
            diagnostic_summary=deepcopy(summary),
            report_fields=deepcopy(report_fields),
        ) as case:
            assert sha256_canonical(case.view["facts"]) == sha256_canonical(
                case.projection.wire["facts"]
            )
            return case.view


def _ols_source(label: str = "OLS") -> dict[str, dict]:
    """Declared test model; neither its type nor values come from display text."""
    return {"ols_1": {
        "model_id": "ols_1", "model_type": "ols", "model_label": label,
        "nobs": 20,
        "coefficients": {"x": {"estimate": 2.0, "std_error": 0.2, "p_value": 0.125}},
    }}


def test_original_numeric_only_owner_preserves_values_and_validation():
    """Retain the original packet's assertions without inventing producer validation."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with _server_owned_evidence(root / "owner-store") as (record, _binding, owner):
            wire = _owner_wire(owner, _report_projection_wire())
            wire["envelopeDigest"] = record.envelope_digest
            projection = owner.issue_report_projection(wire)
            view = build_report_view_model(
                {},
                root / "run-1",
                evidence_projection=projection,
                owner=owner,
                artifact_admission=owner._canonical_report_artifact(),  # type: ignore[attr-defined]
            )
            assert view["status"] == "available"
            assert [fact["value"] for fact in view["facts"]] == [2.0, 0.2]
            assert view["facts"][0]["value"] == 2
            assert any("standardError" in fact for fact in view["facts"])
            assert view["validationStatus"] == "met"
            assert view["validationSummary"]["requirement_status"] == "met"


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
        view_model = _build(summary, model_results=_ols_source("OLS with robust standard errors"))
    assert view_model["status"] == "available"
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
    with patch("workbench.report_view_model.render_template", wraps=real_render_template):
        view_model = _build(summary, model_results=_ols_source())
    assert view_model["status"] == "available"
    row = next(row for row in view_model["regression_table"]["rows"] if row["term"] == "x")
    cell = row["models"]["ols_1"]
    assert cell["estimate"] == 2.0
    assert cell["std_error"] == 0.2
    assert cell["p_value"] == 0.125
    assert view_model["title"] == "OLS"
    assert view_model["causal_caution"]


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
        view_model = _build(summary, model_results={"ols_1": {
            "model_id": "ols_1", "model_type": "ols", "model_label": "OLS",
            "nobs": 20, "coefficients": {"x1": {"estimate": None}},
        }})
    assert view_model["status"] == "available"
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
    view_model = _build(summary, model_results=_ols_source())
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
    view_model = _build(summary, model_results=_ols_source())
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
    view_model = _build(summary, model_results=_ols_source())
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
    view_model = _build(summary, model_results={"logit_1": {
        "model_id": "logit_1", "model_type": "logit", "model_label": "Logistic regression",
        "nobs": 20, "coefficients": {"x": {"estimate": 2.0, "std_error": 0.2, "p_value": 0.125}},
    }})
    assert view_model["status"] == "available"
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
    view_model = _build(summary, model_results=_ols_source())
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
    view_model = _build(summary, model_results={"poisson_1": {
        "model_id": "poisson_1", "model_type": "poisson", "model_label": "Poisson regression",
        "y_variable": "claim_count", "x_variables": ["age", "region"], "nobs": 500,
        "coefficients": {"age": {"estimate": 2.0, "std_error": 0.2, "p_value": 0.125}},
    }})
    assert any("Poisson regression" in fact for fact in view_model["presentation_facts"])
    assert any("claim_count" in fact for fact in view_model["presentation_facts"])


def test_facts_mention_categorical():
    from workbench.diagnostic_summary import build_diagnostic_summary
    source = {"ols_1": {
        "model_id": "ols_1", "model_type": "ols", "model_label": "OLS",
        "y_variable": "y", "x_variables": ["x1", "region"], "nobs": 100,
        "coefficients": {"x1": {"estimate": 2.0, "std_error": 0.2, "p_value": 0.125}},
    }}
    summary = build_diagnostic_summary(
        issue_dicts=[], model_results=list(source.values()), routing={},
        normalized_y="y", normalized_x=["x1", "region"], profile={},
        categorical_vars={"region"}, y_type="continuous", primary_type="ols", variable_roles={},
    )
    assert summary["narrative_contract"]["constraints"]["must_note_categorical_encoded"] is True
    view_model = _build(summary, model_results=source)
    assert view_model["status"] == "available"
    assert "dummy-coded" in " ".join(view_model["presentation_facts"])


def test_report_facts_preserve_bounded_survey_replicate_metadata(tmp_path: Path):
    """Facts must qualify design-based precision with replicate outcome status."""
    result = {
        "model_id": "ols_1",
        "model_type": "ols",
        "model_label": "Survey OLS",
        "nobs": 12,
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
                # An explicit model source lets this test reach the survey
                # presentation assertions instead of missing-estimate admission.
                "estimate": 1.0,
                "std_error": 0.2,
                "p_value": 0.125,
                "variance_source": "survey_design",
                "source_id": "model_results.ols_1.coefficients.x",
                "warnings": ["SURVEY_REPLICATE_FAILURES"],
            }
        },
    }
    view_model = _build(
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
        model_results={"ols_1": result},
    )

    # C0 owns the citable ``facts`` field. Survey provenance is a bounded
    # presentation projection and therefore travels in ``presentation_facts``.
    facts_text = " ".join(view_model["presentation_facts"])
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
    if field == "design_effect":
        assert packet["models"][0]["result_digest"] == {
            "status": "unavailable", "reason": "MODEL_RESULT_NOT_CANONICAL"}


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
        view_model = _build(summary, model_results={"ols_1": {
            "model_id": "ols_1", "model_type": "ols", "model_label": "OLS", "nobs": 20,
            "coefficients": {"x1": {"estimate": 0.5, "std_error": 0.2, "p_value": 0.125}},
        }})
    assert view_model["status"] == "available"
    assert view_model["coefficient_interpretations"][0]["text"] == ""


@pytest.mark.parametrize("estimate,display", [(-1e-24, "-1e-24"), (0.0, "0"), (-0.0, "0")])
def test_admitted_coefficient_text_is_neutral_and_keeps_exact_values(estimate, display):
    source = _ols_source()
    source["ols_1"]["coefficients"]["x"]["estimate"] = estimate
    source["ols_1"]["coefficients"]["x"]["p_value"] = 1e-24
    view = _build({}, model_results=source)
    interpretation = view["coefficient_interpretations"][0]
    assert interpretation["model_id"] == "ols_1"
    assert interpretation["variable"] == "x"
    # Canonical numeric facts normalize either signed zero to integer zero.
    assert f"coefficient = {display};" in interpretation["text"]
    assert "1e-24" in interpretation["text"]
    assert "significant" not in interpretation["text"]
    assert "one-unit" not in interpretation["text"]


def test_empty_summary_does_not_crash():
    summary = {}
    with patch("workbench.report_view_model.render_template") as mock_render:
        mock_render.return_value = "rendered"
        view_model = _build(summary, model_results=_ols_source())
    assert view_model["status"] == "available"
    assert view_model["critical_errors"] == []
    assert str(view_model["projectionId"]).startswith("report:commit:evidence:")
    assert mock_render.call_count >= 1
