"""v1.8.7 — can the Agent *read* what this version produces?

Reachability has two halves and the second is easy to forget. Every earlier
check in this version asked whether an Agent could ask for something; these ask
whether it can see the answer.

The gap matters most for the survey design. An Agent that declared one gets back
coefficients and standard errors like any other run, with nothing saying those
standard errors are design-based, what the design degrees of freedom are, or
that the effective sample size is well below the row count. It will speak about
the precision of the estimate, and it will have no way to know.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from workbench.agent.context_tools import (
    InspectProjectModelCoefficientsRequest,
    InspectResultSummaryRequest,
    NodeOperationContextProvider,
    _bounded_regression_table,
    _bounded_model_family_evidence,
    _public_requested_model_coefficients,
    _bounded_coefficient_row,
)
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.results_service import read_model_results

FIXTURES = Path(__file__).parent / "fixtures"


def _run(tmp_path: Path, name: str, fixture: str, **kwargs):
    source = tmp_path / f"{name}.csv"
    source.write_text((FIXTURES / fixture).read_text())
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    return project, outcome["run_id"]


def _summary(project, run_id: str, node: str) -> dict:
    provider = NodeOperationContextProvider(project.root)
    return provider.inspect_result_summary(
        InspectResultSummaryRequest(
            request_id="read-test", owner_run_id=run_id,
            op_node_id=node, active_head_run_id=run_id,
        )
    )


def test_the_agent_can_see_that_standard_errors_are_design_based(tmp_path):
    """Otherwise it will describe the precision of an interval it cannot read."""
    project, run_id = _run(
        tmp_path, "svy", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    payload = json.dumps(_summary(project, run_id, "model:ols_1"))

    assert "survey_design" in payload, "the Agent cannot tell this run had a design"
    for field in ("degf", "variance_method", "design_effect", "effective_sample_size"):
        assert field in payload, f"the Agent cannot read {field}"


def test_agent_projection_preserves_survey_provenance_and_replicate_metadata(tmp_path):
    """A bounded Agent read must retain the survey qualification per coefficient."""
    replicate_columns = [f"repw{i:02d}" for i in range(1, 13)]
    project, run_id = _run(
        tmp_path, "svy-replicate", "survey/design_with_replicate_weights.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
        survey_replicate_type="provided", survey_replicate_weights=replicate_columns,
    )
    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    design = summary["survey_design"]
    assert design["replicates_attempted"] == 12
    assert design["replicates_succeeded"] + design["replicates_failed"] == 12
    assert isinstance(design["replicate_failure_reasons"], dict)

    row = next(row for row in summary["regression_table"]["rows"] if row["term"] == "x1")
    coefficient = row["models"]["ols_1"]
    assert coefficient["variance_source"] == "survey_design"
    assert coefficient["source_id"] == "model_results.ols_1.coefficients.x1"
    assert isinstance(coefficient["warnings"], list)

    requested = NodeOperationContextProvider(project.root).inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(run_ids=(run_id,), terms=("x1",))
    )
    projected = requested["models"][0]["coefficients"][0]
    assert projected["variance_source"] == "survey_design"
    assert projected["source_id"] == "model_results.ols_1.coefficients.x1"
    assert isinstance(projected["warnings"], list)


def test_agent_rejects_tampered_model_result_before_projection(tmp_path):
    """A valid JSON file is not valid evidence once its indexed hash changes."""
    project, run_id = _run(
        tmp_path, "tampered", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    result_path = project.root / "runs" / run_id / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["coefficients"]["x1"]["estimate"] = 999.0
    result_path.write_text(json.dumps(payload))

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["status"] == "unavailable"
    assert summary["unavailable_reason"] == "AGENT_RESULT_ARTIFACT_INVALID"


def test_agent_rejects_foreign_binding_even_when_index_hash_is_rewritten(tmp_path):
    from workbench.artifacts import sha256_file, write_json

    project, run_id = _run(
        tmp_path, "foreign-binding", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    run_root = project.root / "runs" / run_id
    result_path = run_root / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["result_binding"]["project_root"] = "/foreign/project"
    write_json(result_path, payload)

    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text())
    for record in index["artifacts"]:
        if record.get("artifact_id") == "ols_1":
            record["sha256"] = sha256_file(result_path)
    write_json(index_path, index)

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["unavailable_reason"] == "AGENT_RESULT_ARTIFACT_INVALID"


def test_agent_requires_server_index_and_rejects_synchronized_digest_forgery(tmp_path):
    project, run_id = _run(
        tmp_path, "tamper", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    run_root = project.root / "runs" / run_id
    result_path = run_root / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["coefficients"]["x1"]["estimate"] = 123.0
    result_path.write_text(json.dumps(payload))
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text())
    for record in index["artifacts"]:
        if record.get("artifact_id") == "ols_1":
            record["sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["unavailable_reason"] == "AGENT_RESULT_ARTIFACT_INVALID"


def test_agent_rejects_legacy_model_results_without_index(tmp_path):
    project, run_id = _run(
        tmp_path, "missing-index", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
    )
    run_root = project.root / "runs" / run_id
    (run_root / "artifacts_index.json").unlink()

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["unavailable_reason"] == "AGENT_RESULT_ARTIFACT_INVALID"


def test_agent_coefficient_projection_bounds_huge_values_and_provenance():
    """Agent output must be typed unavailable rather than serializing huge values."""
    result = {
        "model_id": "ols_1",
        "model_label": "Survey OLS",
        "coefficients": {
            "x": {
                "estimate": 10**400,
                "std_error": 10**400,
                "p_value": 10**400,
                "ci_lower": 10**400,
                "ci_upper": 10**400,
                "variance_source": "v" * 2000,
                "source_id": "s" * 2000,
                "warnings": ["w" * 2000] * 100,
            }
        },
        "nobs": 10**400,
        "df_model": -1,
        "df_resid": 10**400,
        "exposure_col": 10**400,
        "sampling_weight": 10**400,
    }

    projected_model = _public_requested_model_coefficients(
        run_id="run-1", result=result, requested_terms=("x",)
    )
    projected = projected_model["coefficients"][0]
    assert projected["projection_status"] == "unavailable"
    assert projected["unavailable_reason"] == "AGENT_COEFFICIENT_VALUE_INVALID"
    assert projected["estimate"] is None
    assert projected["projection_status"] == "unavailable"
    assert projected["unavailable_reason"] == "AGENT_COEFFICIENT_VALUE_INVALID"
    assert projected_model["nobs"] is None
    assert projected_model["df_model"] is None
    assert projected_model["df_resid"] is None
    assert projected_model["model_metadata_status"] == "unavailable"
    assert projected_model["exposure_col"] is None
    assert projected_model["sampling_weight"] is None
    assert len(projected["source_id"]) <= 128
    assert len(projected["variance_source"]) <= 128
    assert len(projected["warnings"]) <= 16
    assert all(len(item) <= 128 for item in projected["warnings"])

    table_cell = _bounded_regression_table([result])["rows"][0]["models"]["ols_1"]
    assert table_cell["projection_status"] == "unavailable"
    assert table_cell["unavailable_reason"] == "AGENT_COEFFICIENT_VALUE_INVALID"


@pytest.mark.parametrize("bad_p", [-1, 2, 10**400, float("nan"), float("inf")])
def test_agent_regression_and_diagnostic_projections_do_not_copy_invalid_survey_scalars(bad_p):
    result = {
        "model_id": "ols_1",
        "model_type": "ols",
        "nobs": 10**400,
        "survey_design": {
            "n_obs": -1,
            "n_psu": 2.5,
            "degf": -2,
            "residual_degf": 10**400,
            "variance_method": "linearization",
            "source_id": "run-1:model_results.ols_1",
        },
        "coefficients": {
            "x": {
                "estimate": 1.0,
                "std_error": -1,
                "p_value": bad_p,
                "ci_lower": 2.0,
                "ci_upper": 1.0,
                "variance_source": "survey_design",
                "source_id": "run-1:model_results.ols_1.coefficients.x",
                "warnings": ["SURVEY_INVALID"],
            }
        },
    }

    table = _bounded_regression_table([result])
    model = table["models"][0]
    cell = table["rows"][0]["models"]["ols_1"]
    assert model["nobs"] is None
    assert model["projection_status"] == "unavailable"
    assert model["survey_design"]["projection_status"] == "unavailable"
    assert "n_obs" not in model["survey_design"]
    assert "degf" not in model["survey_design"]
    assert cell["projection_status"] == "unavailable"
    assert cell.get("p_value") is None
    assert cell.get("std_error") is None
    assert cell.get("ci_lower") is None
    assert cell.get("ci_upper") is None
    assert cell["source_id"] == "run-1:model_results.ols_1.coefficients.x"

    diagnostic = _bounded_coefficient_row({"variable": "x", **result["coefficients"]["x"]})
    assert diagnostic["projection_status"] == "unavailable"
    assert diagnostic.get("p_value") is None
    assert diagnostic.get("std_error") is None


def test_a_run_without_a_design_says_so_rather_than_omitting_the_field(tmp_path):
    """Absence must be readable as absence, not as a field that failed to load."""
    project, run_id = _run(
        tmp_path, "plain", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
    )
    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary.get("survey_design") is None


def test_the_agent_can_read_an_anova_table(tmp_path):
    """It can already propose ANOVA; without this it cannot read the result."""
    project, run_id = _run(
        tmp_path, "an", "anova/anova.csv",
        model_type="anova", y="score", x=["factor_a", "factor_b", "covariate"],
        model_options={"sums_of_squares": 3, "categorical": ["factor_a", "factor_b"]},
    )
    run_root = project.root / "runs" / run_id
    evidence = _bounded_model_family_evidence(run_root, read_model_results(run_root))

    assert evidence is not None, "no ANOVA evidence is projected to the Agent at all"
    payload = json.dumps(evidence)
    # The type is not decoration: Type I and Type III disagree on this fixture
    # (166.74 against 104.05), so a table quoted without it is ambiguous.
    assert "sums_of_squares_type" in payload
    assert "anova_table" in payload
    assert "partial_eta_squared" in payload


def test_the_agent_can_read_average_marginal_effects(tmp_path):
    """A logit coefficient is a log-odds; the AME is the number people quote."""
    project, run_id = _run(
        tmp_path, "glm", "marginal_effects/glm.csv",
        model_type="logit", y="binary", x=["x1", "x2"],
    )
    payload = json.dumps(_summary(project, run_id, "model:logit_1"))
    assert "marginal_effect" in payload, (
        "the result carries average marginal effects and the Agent cannot see them"
    )


def test_the_agent_can_read_how_strongly_a_family_was_validated(tmp_path):
    """v1.8.7 made this a per-family claim; an Agent quoting a result should
    be able to say what backs it rather than implying more than is known."""
    project, run_id = _run(
        tmp_path, "ord", "v186_families/families.csv",
        model_type="ordinal_logit", y="rating", x=["x1", "x2", "grp"],
        model_options={"outcome_order": ["low", "mid", "high"]},
    )
    run_root = project.root / "runs" / run_id
    evidence = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    payload = json.dumps(evidence)
    assert "validation" in payload, "the Agent cannot read the verification level"
    assert "polr" in payload, "the reference implementation is not readable"


def test_every_family_with_its_own_result_shape_is_readable_by_the_agent():
    """The gap this file closed, stated so a new family cannot reopen it.

    `anova` shipped able to be proposed and impossible to read: the run
    succeeded, the Agent had asked for it, and the result projection returned
    None. Reachability has two halves, and the second is the easy one to forget
    because nothing fails when it is missing.

    Families whose result is the ordinary coefficient table are covered by the
    result summary; the ones listed here carry a shape of their own, and each
    needs a declared projection.
    """
    from workbench.agent.context_tools import FAMILY_EVIDENCE_PROJECTIONS
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    # `coefficient_intervals` is the ordinary coefficient table, which the
    # result summary already projects with its own bounds. Everything else has
    # a shape of its own that the summary cannot represent.
    summary_covered = {"coefficient_intervals"}
    shaped = {
        key
        for key, contract in MODEL_FAMILY_CONTRACTS.items()
        if contract.result_shape and contract.result_shape not in summary_covered
    }
    assert shaped, "no family declares a non-standard result shape; the scan is vacuous"
    assert "anova" in shaped, "the family this guard was written for left the scan"

    # The DID families predate this projection and read through their own
    # diagnostics cards; recorded as a known gap rather than silently excluded.
    known_gaps = {"cs_did", "sa_did", "dcdh"}
    missing = sorted(shaped - set(FAMILY_EVIDENCE_PROJECTIONS) - known_gaps)
    assert not missing, (
        f"{missing} declare their own result shape but project nothing to the "
        "Agent, so it can ask for them and cannot read the answer"
    )
