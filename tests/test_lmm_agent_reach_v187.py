"""v1.8.7 — bring linear mixed effects into the natural-language surface.

LMM was the one family a user could run from the form and an Agent could not
start at all. `builtin_declarations.py` records why: "C1 does not register an
executable LMM Agent recipe" -- a v1.7.3 decision from when the family had its
own packet lifecycle and nothing else looked like it.

The island went deeper than that note. LMM published *no* parameters to
`/capabilities`, so the form drove it through hard-coded controls and a rerun
rejected every field as unknown: it could be created and never changed.

Nothing here touches how LMM executes. Its options contract, its pre-fit sealed
input and its packet envelope are unchanged; what changes is that the same
declarations the form already sends can be named by an Agent.
"""

from __future__ import annotations

import json

import pytest


def test_lmm_publishes_its_parameters_like_every_other_family():
    """Without published params a rerun cannot change a single LMM field."""
    # Import the orchestrator first: `engine.capabilities` reaches the pipeline
    # through a module cycle that only resolves once the orchestrator is loaded.
    # Pre-existing (recorded as a GAP), not introduced by this family.
    import workbench.orchestrator  # noqa: F401
    from workbench.engine.capabilities import build_capabilities

    entry = next(
        item for item in build_capabilities()["model_types"]
        if item["key"] == "linear_mixed_effects"
    )
    published = {param["key"] for param in entry["params"]}
    # `y` is not a published param for any family -- the outcome is a branch
    # field, not a model parameter. Matching the convention rather than
    # inventing one for this family.
    assert {"model_type", "x", "model_options"} <= published, published

    options = next(p for p in entry["params"] if p["key"] == "model_options")
    assert options["required"] is True, "an LMM without its roles is not an LMM"
    assert set(options.get("options") or []) >= {
        "subject_id", "time", "group", "fit_method", "random_slope",
    }


def test_lmm_declares_a_model_family_contract():
    """The registry is what makes a family nameable in a composed plan."""
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    contract = MODEL_FAMILY_CONTRACTS.get("linear_mixed_effects")
    assert contract is not None, "LMM is still absent from the family registry"
    # The five inputs the LMM contract has always required, now declared where
    # every other family declares its own.
    assert set(contract.model_options_fields) >= {
        "subject_id", "time", "group", "fit_method", "random_slope",
    }
    assert set(contract.model_options_required_fields) >= {"subject_id", "time", "group"}


def test_an_agent_can_compose_a_plan_that_starts_an_lmm():
    from workbench.agent.workflow import compile_workflow

    plan = [
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "spec": {
                "model_family": "linear_mixed_effects",
                "model_options": {
                    "subject_id": "subject", "time": "week", "group": "arm",
                    "fit_method": "reml", "random_slope": True,
                },
                "branches": [
                    {"branch_id": "b1", "outcome": "score", "predictors": ["week"]}
                ],
            },
        }
    ]
    draft = compile_workflow(
        workflow_id="wf-lmm",
        target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
        preconditions={"context_fingerprint": "fp"},
        steps=plan,
        available_columns=["subject", "week", "arm", "score"],
    )
    spec = draft.steps[0].spec
    assert spec["model_family"] == "linear_mixed_effects"
    assert spec["model_options"]["subject_id"] == "subject"


def test_an_lmm_plan_missing_its_repeated_measures_columns_is_refused():
    """Fail closed, and name what is missing -- a plan that ran without a
    subject column would silently fit an ordinary regression instead."""
    from workbench.agent.operations import OperationValidationError
    from workbench.agent.workflow import compile_workflow

    plan = [
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "spec": {
                "model_family": "linear_mixed_effects",
                "model_options": {"time": "week"},
                "branches": [
                    {"branch_id": "b1", "outcome": "score", "predictors": ["week"]}
                ],
            },
        }
    ]
    with pytest.raises(OperationValidationError) as excinfo:
        compile_workflow(
            workflow_id="wf-lmm-bad",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=plan,
            available_columns=["subject", "week", "arm", "score"],
        )
    message = str(excinfo.value)
    assert "subject_id" in message and "group" in message


def test_lmm_appears_in_the_family_list_the_agent_is_shown():
    """The sentence is derived from the registry, so this follows -- asserted
    because that derivation is exactly what a future refactor could undo."""
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    described = (
        WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"]
        .to_schema()["properties"]["model_family"]["description"]
    )
    assert "linear_mixed_effects" in described


def test_an_agent_started_lmm_meets_the_same_containment_gate_as_the_form(tmp_path):
    """Reachable does not mean privileged.

    LMM execution is admitted only under the frozen local-containment profile
    (v1.7.3). Making the family nameable in a plan must not create a second door
    into it: an Agent-composed run has to arrive at the same gate the form does,
    with the same error code.
    """
    from workbench.model_options import ModelOptionsError

    frame, source, project = _repeated_measures_project(tmp_path, "lmm_gate")
    params = _agent_model_params()

    from workbench.orchestrator import run_workflow

    with pytest.raises(ModelOptionsError) as excinfo:
        run_workflow(
            project.root, [source], mode="auto", y="score", x=["week"],
            model_type=params["model_type"], model_options=params["model_options"],
        )
    assert excinfo.value.code == "LMM_FROZEN_CONTAINMENT_REQUIRED"


def test_the_parameters_an_agent_composes_satisfy_the_lmm_options_contract():
    """The Agent's contribution is the parameters; validate exactly that.

    Whether LMM fits is v1.7.3's question and its own tests answer it. What is
    new here is that a composed plan produces options the family accepts, so
    this drives them through the real validator rather than re-testing the
    estimator.
    """
    from workbench.contracts.model.linear_mixed_effects import LmmModelInput

    params = _agent_model_params()
    assert params["model_type"] == "linear_mixed_effects"

    model_input = LmmModelInput.from_dict(params["model_options"])
    assert model_input.subject_id == "subject"
    assert model_input.time == "week"
    assert model_input.group == "arm"


def test_the_agent_plan_binds_through_the_shared_model_options_gate():
    """`bind_new_model_options` is what every entry point calls before a fit.

    A plan whose options pass the family contract but fail this gate would be
    proposable, confirmable, and dead on submission.
    """
    from workbench.model_options import bind_new_model_options

    params = _agent_model_params()
    bound = bind_new_model_options(params["model_type"], params["model_options"])
    assert bound.payload["subject_id"] == "subject"


def _agent_model_params() -> dict:
    """Exactly what a composed plan hands the runner."""
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    contract = MODEL_FAMILY_CONTRACTS["linear_mixed_effects"]
    spec = {
        "model_family": "linear_mixed_effects",
        "model_options": {
            "subject_id": "subject", "time": "week", "group": "arm",
            "fit_method": "reml", "random_slope": True,
        },
    }
    branch = {"branch_id": "b1", "outcome": "score", "predictors": ["week"]}
    return contract.build_model_params(spec, branch, ["week"], "unadjusted")


def _repeated_measures_project(tmp_path, name):
    import numpy as np
    import pandas as pd

    from workbench.projects import create_project

    rng = np.random.default_rng(20260815)
    rows = []
    for subject in range(30):
        arm = "treat" if subject % 2 else "control"
        intercept = rng.normal(0, 1.0)
        for week in range(4):
            effect = (0.6 if arm == "treat" else 0.2) * week
            rows.append(
                {
                    "subject": f"s{subject}",
                    "week": week,
                    "arm": arm,
                    "score": 10 + intercept + effect + rng.normal(0, 0.5),
                }
            )
    frame = pd.DataFrame(rows)
    source = tmp_path / f"{name}.csv"
    frame.to_csv(source, index=False)
    return frame, source, create_project(tmp_path, name)
