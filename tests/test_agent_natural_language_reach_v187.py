"""v1.8.7 — everything this version added has to be reachable in one sentence.

The product goal is that an Agent can drive the whole workbench from natural
language. `operation.multi_step` is that entry point: the Agent composes which
steps run over which columns, and every step's statistics are still validated
and executed by the same server-owned validators the manual UI uses.

A capability the engine runs, the form configures and a rerun can change is
still unreachable if the *first* run cannot declare it -- the user would have to
build the analysis by hand before the Agent could touch it.
"""

from __future__ import annotations

import json

import pytest

from workbench.agent.workflow_contracts import (
    MODEL_FAMILY_CONTRACTS,
    WORKFLOW_STEP_SPEC_CONTRACTS,
)


def _genesis_schema() -> dict:
    return WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"].to_schema()


def test_the_family_list_an_agent_is_shown_comes_from_the_registry():
    """A hand-written list of families goes stale the first time one is added.

    `anova` shipped in this version and the sentence describing `model_family`
    still named eighteen other families, so a request for a factorial ANOVA had
    nowhere to land -- and nothing failed, because the text is prose.
    """
    described = _genesis_schema()["properties"]["model_family"]["description"]

    executable = {
        key
        for key, contract in MODEL_FAMILY_CONTRACTS.items()
        if key not in {"auto"}
    }
    missing = sorted(family for family in executable if family not in described)
    assert not missing, (
        f"{missing} are executable families the Agent is never told about"
    )


def test_a_first_run_can_declare_a_sampling_design(tmp_path):
    """Otherwise the design is reachable only after building the run by hand."""
    schema = _genesis_schema()
    properties = set(schema["properties"])

    from workbench.survey.fields import DESIGN_FIELDS

    missing = sorted(set(DESIGN_FIELDS) - properties)
    assert not missing, f"a genesis step cannot declare {missing}"
    assert "sampling_weight" in properties, (
        "a design without its weight is refused by the engine, so both must be "
        "declarable in the same step"
    )


def test_a_first_run_can_declare_measurement_levels(tmp_path):
    """The batch declaration exists for reruns; it has to exist here too."""
    assert "labels" in _genesis_schema()["properties"], (
        "an Agent cannot state what a column measures when creating the analysis"
    )


def test_the_step_validator_accepts_what_the_schema_advertises():
    """Two halves of the same contract, kept in step by one declaration.

    Advertising a field the validator rejects teaches the Agent to emit a plan
    that always fails -- the same defect this version already hit once between
    `editable_schema` and `proposal_schema`.
    """
    contract = WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"]
    advertised = set(contract.to_schema()["properties"])
    assert advertised == set(contract.fields), (
        "the published schema and the accepted field set disagree"
    )


# ---------------------------------------------------------------------------
# a declared field that the executor drops is worse than one it rejects
# ---------------------------------------------------------------------------

def test_a_declared_design_survives_compilation_into_the_genesis_step():
    """The plan an Agent writes has to keep the design, not just accept it.

    Every family builds its own model params, and none of them carried the
    survey fields: an Agent could name a design in its plan, watch the run
    succeed, and get ordinary standard errors back. Nothing would report it.
    """
    import pandas as pd

    from workbench.agent.workflow import compile_workflow

    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 3.0, 4.0] * 10,
            "x1": [0.5, 1.5, 2.5, 3.5] * 10,
            "stratum": ["a", "a", "b", "b"] * 10,
            "psu": ["p1", "p2", "p3", "p4"] * 10,
            "weight": [10.0, 12.0, 11.0, 9.0] * 10,
        }
    )
    plan = [
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "spec": {
                "model_family": "ols",
                "sampling_weight": "weight",
                "survey_strata_col": "stratum",
                "survey_psu_col": "psu",
                "branches": [
                    {"branch_id": "b1", "outcome": "y", "predictors": ["x1"]}
                ],
            },
        }
    ]
    draft = compile_workflow(
        workflow_id="wf-survey",
        target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
        preconditions={"context_fingerprint": "fp"},
        steps=plan,
        available_columns=list(frame.columns),
    )

    spec = draft.steps[0].spec
    assert spec.get("survey_strata_col") == "stratum"
    assert spec.get("sampling_weight") == "weight"


def test_the_genesis_model_params_carry_the_design_to_the_run():
    """Where the drop actually happened: the per-family parameter builder."""
    from workbench.agent.workflow_contracts import genesis_run_params

    spec = {
        "model_family": "ols",
        "sampling_weight": "weight",
        "survey_strata_col": "stratum",
        "survey_psu_col": "psu",
        "labels": {"measurement_level": {"y": "scale"}},
    }
    params = genesis_run_params(spec)

    assert params["sampling_weight"] == "weight"
    assert params["survey_strata_col"] == "stratum"
    assert params["survey_psu_col"] == "psu"
    assert params["labels"] == {"measurement_level": {"y": "scale"}}
    # Absent declarations must not appear at all -- an empty string would look
    # like a column named "" to everything downstream.
    assert "survey_subpop" not in params


def test_a_plan_declaring_a_design_runs_and_produces_design_standard_errors(tmp_path):
    """The whole path: a plan an Agent could write, executed, checked against R.

    Structural agreement proves the field survives compilation. Only a run
    proves the number moved.
    """
    import json
    from pathlib import Path

    import pandas as pd

    from workbench.agent.workflow import WorkflowExecutor, compile_workflow

    fixtures = Path(__file__).parent / "fixtures" / "survey"
    frame = pd.read_csv(fixtures / "design.csv")
    oracle = json.loads((fixtures / "oracle.json").read_text())["linearization"]

    plan = [
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "spec": {
                "model_family": "ols",
                "sampling_weight": "weight",
                "survey_strata_col": "stratum",
                "survey_psu_col": "psu",
                "survey_fpc_col": "fpc",
                "branches": [
                    {"branch_id": "b1", "outcome": "y", "predictors": ["x1", "x2"]}
                ],
            },
        }
    ]
    draft = compile_workflow(
        workflow_id="wf-svy-e2e",
        target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
        preconditions={"context_fingerprint": "fp"},
        steps=plan,
        available_columns=list(frame.columns),
    )

    from workbench.agent.workflow_contracts import genesis_run_params

    carried = genesis_run_params(draft.steps[0].spec)
    assert carried["survey_strata_col"] == "stratum"
    assert carried["survey_psu_col"] == "psu"
    assert carried["survey_fpc_col"] == "fpc"
    assert carried["sampling_weight"] == "weight"

    # The same declarations, run through the ordinary workflow the executor
    # ultimately calls, must reproduce R's design-based standard errors.
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.artifacts import read_json

    source = tmp_path / "design.csv"
    source.write_text((fixtures / "design.csv").read_text())
    project = create_project(tmp_path, "plan_e2e")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols",
        y="y", x=["x1", "x2"], **carried,
    )
    assert outcome["status"] == "completed", outcome

    result = read_json(
        project.root / "runs" / outcome["run_id"] / "model_results" / "ols_1.json"
    )
    assert result["survey_design"]["degf"] == 8
    for payload_term, oracle_term in [
        ("Intercept", "(Intercept)"), ("x1", "x1"), ("x2", "x2"),
    ]:
        assert result["coefficients"][payload_term]["std_error"] == pytest.approx(
            oracle["se"][oracle_term], rel=1e-8
        )


def test_the_genesis_executor_merges_the_run_level_declarations():
    """`genesis_run_params` existing is not the same as it being called.

    v1.8.6 shipped five features whose code was correct and which nothing
    invoked. The executor path needs real uploads and drafts to drive, so this
    is a structural assertion rather than an executed one -- stated plainly:
    extraction is covered by its own test, and the resulting parameters are
    checked end to end against R by the test above. This closes the third link.
    """
    from pathlib import Path

    source = (
        Path(__file__).parent.parent
        / "backend/workbench/agent/workflow_runtime.py"
    ).read_text()

    assert "genesis_run_params" in source, (
        "the genesis executor never merges the run-level declarations, so a "
        "design named in a plan is dropped on the way to the run"
    )
    # Merged after the family builder, or the family would overwrite it.
    builder = source.index("family_contract.build_model_params(")
    merge = source.index("genesis_run_params(branch_spec)")
    assert merge > builder, "the merge happens before the family builder overwrites it"
