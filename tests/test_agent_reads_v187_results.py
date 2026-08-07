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
from pathlib import Path

import pytest

from workbench.agent.context_tools import (
    InspectResultSummaryRequest,
    NodeOperationContextProvider,
    _bounded_model_family_evidence,
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
