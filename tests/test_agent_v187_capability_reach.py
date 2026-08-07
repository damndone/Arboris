"""v1.8.7 — can the Agent actually reach what this version added?

A family counts as integrated only when the engine runs it, the UI configures it,
*and* the Agent can emit a typed proposal for it.  The first two were verified in
a browser; this file asks the third question, which nothing else does.

The answers are checked against the real validators.  A vocabulary or a schema
that merely mentions a field, while confirmation rejects a proposal carrying it,
is worse than an absent one: it teaches the Agent to produce patches that always
fail, and reads as authoritative while doing so.
"""

from __future__ import annotations

import pytest

from workbench.agent.operations import OperationRegistry, OperationValidationError


def _rerun_scaffold() -> tuple[dict, dict]:
    """A target/preconditions pair the rerun validator already accepts."""
    target = {
        "run_id": "r1",
        "node_ref": "model:ols_1",
        "node_hash": "h1",
        "forest_node_key": "k1",
    }
    preconditions = {
        "context_version": "v1",
        "context_fingerprint": "fp1",
        "active_head_run_id": "r1",
        "owner_resolution": "explicit",
    }
    return target, preconditions


def _await_run(client, project_root, run_id, timeout=90.0):
    """Runs are submitted asynchronously; reading artifacts before the terminal
    status is a race that fails as a missing file rather than as a wrong number."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(
            f"/runs/{run_id}", params={"project_root": str(project_root)}
        ).json()
        status = payload.get("status")
        if status in {"completed", "succeeded", "failed", "error"}:
            assert status in {"completed", "succeeded"}, payload
            return payload
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} never reached a terminal status")


def _validate_rerun(changes: dict) -> None:
    definition = OperationRegistry().require("model.rerun")
    target, preconditions = _rerun_scaffold()
    definition.validator(target, preconditions, changes)


def test_agent_can_patch_anova_options_through_model_options():
    """The ANOVA knobs ride the generic options envelope, so they already work."""
    _validate_rerun({"model_options": {"sums_of_squares": 3, "categorical": ["factor_a"]}})


def test_agent_can_declare_a_survey_design_in_a_typed_proposal():
    """The design fields are run-level, not model options -- and that is the gap.

    `model.rerun` closes `changes` to `{model_options}`, and the survey design
    travels as run parameters (`survey_strata_col` and friends), so there is no
    field an Agent can put them in.  The engine executes a design and the form
    collects one, but a natural-language request to add one has nowhere to land.

    `model.genesis` does accept `model_params`, but it is registered with
    `natural_language_enabled=False`, so it is not a route an Agent can take.
    """
    _validate_rerun(
        {
            "survey_strata_col": "stratum",
            "survey_psu_col": "psu",
            "survey_fpc_col": "fpc",
            "survey_lonely_psu": "adjust",
        }
    )


def test_the_rerun_schema_and_its_validator_agree_on_every_field():
    """A field the schema advertises and the validator rejects is worse than none.

    It teaches the Agent to emit a proposal that always fails, while reading as
    authoritative. Both sides read one declaration; this proves they still do.
    """
    from workbench.agent.operations import model_rerun_change_fields

    definition = OperationRegistry().require("model.rerun")
    declared = set(model_rerun_change_fields())
    assert set(definition.editable_schema["properties"]) == declared

    # The schema the *model* is handed is `proposal_schema`, not
    # `editable_schema`. Aligning only the latter is how the survey fields came
    # to be accepted by the validator while the tool contract still forbade
    # them -- the model would have been unable to emit them at all.
    changes = definition.proposal_schema["properties"]["changes"]
    branch = next(
        option for option in changes["oneOf"]
        if "model_options" in option.get("properties", {})
    )
    assert set(branch["properties"]) == declared, (
        "the proposal schema the model sees disagrees with the validator"
    )

    for field_name in declared:
        _validate_rerun({field_name: {} if field_name == "model_options" else "x"})


def test_the_executor_can_carry_every_field_the_proposal_may_declare():
    """Accepting a proposal the executor silently drops is the worse failure.

    `op_overrides` are validated against the params a family publishes, so a
    design field the Agent may propose but the capability never publishes would
    be dropped on the way to the run -- reported as success, returning a result
    with no design in it.
    """
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS
    from workbench.engine.capabilities import build_capabilities
    from workbench.survey.fields import DESIGN_FIELDS

    caps = build_capabilities()
    design_families = set(caps["survey_design"]["sampling_weight_families"])
    checked = 0

    for entry in caps["model_types"]:
        contract = MODEL_FAMILY_CONTRACTS.get(entry["key"])
        if contract is None:
            continue
        # Per family, not the global union: a family that takes only a sampling
        # weight has no reason to publish a frequency one.
        required = {f"{kind}_weight" for kind in contract.allows_weights}
        if entry["key"] in design_families:
            required |= set(DESIGN_FIELDS)
        if not required:
            continue
        checked += 1
        published = {param["key"] for param in entry["params"]}
        missing = required - published
        assert not missing, (
            f"{entry['key']} accepts {sorted(missing)} but never publishes them, "
            "so a rerun carrying them would be rejected as unknown fields"
        )

    assert checked >= 4, "the scan matched almost nothing and proves little"


def test_creating_a_first_run_is_still_not_agent_reachable():
    """Switching family now works; creating one from nothing still does not.

    `model.rerun` re-runs an existing node under a different family. `model.genesis`
    builds a first run from a dataset and stays `natural_language_enabled=False`,
    so "start an analysis for me" is not something an Agent can do. Asserted so
    the day that changes, the release-notes claim has to be rewritten rather than
    quietly becoming false.
    """
    genesis = OperationRegistry().require("model.genesis")
    assert genesis.natural_language_enabled is False

    # `model_params` remains the genesis envelope and is not a rerun field; a
    # family switch on a rerun is a flat `model_type`, checked above.
    with pytest.raises(OperationValidationError):
        _validate_rerun({"model_params": {"model_type": "anova"}})


def test_a_rerun_override_actually_produces_a_design_run(tmp_path):
    """The whole path, end to end: propose a design, get design SEs back.

    Every assertion above is structural -- schemas agreeing with validators,
    fields agreeing with params. None of them proves a number moves. This runs a
    plain OLS, applies the override an Agent's confirmed proposal would carry,
    and checks the child against R.
    """
    import json
    import time
    from pathlib import Path

    from fastapi.testclient import TestClient

    from workbench.api import app
    from workbench.artifacts import read_json
    from workbench.projects import create_project

    fixtures = Path(__file__).parent / "fixtures" / "survey"
    oracle = json.loads((fixtures / "oracle.json").read_text())["linearization"]

    project = create_project(tmp_path, "agent_reach")
    source = project.root / "design.csv"
    source.write_text((fixtures / "design.csv").read_text())

    client = TestClient(app)
    with source.open("rb") as handle:
        created = client.post(
            "/runs",
            files={"file": ("design.csv", handle, "text/csv")},
            data={
                "project_root": str(project.root),
                "mode": "auto", "model_type": "ols", "y": "y", "x": "x1,x2",
            },
        )
    assert created.status_code == 200, created.text
    parent_id = created.json()["run_id"]
    _await_run(client, project.root, parent_id)

    parent = read_json(
        project.root / "runs" / parent_id / "model_results" / "ols_1.json"
    )
    assert parent.get("survey_design") is None, "the parent must have no design"

    rerun = client.post(
        f"/runs/{parent_id}/rerun",
        params={"project_root": str(project.root)},
        json={
            "from_node": "model:ols_1",
            "op_overrides": {
                "sampling_weight": "weight",
                "survey_strata_col": "stratum",
                "survey_psu_col": "psu",
                "survey_fpc_col": "fpc",
            },
            "rerun_reason": "agent_confirmed",
        },
    )
    assert rerun.status_code == 200, rerun.text
    child_id = rerun.json()["run_id"]
    _await_run(client, project.root, child_id)

    child = read_json(
        project.root / "runs" / child_id / "model_results" / "ols_1.json"
    )
    design = child.get("survey_design")
    assert design, "the override was accepted but produced no design"
    assert design["n_strata"] == 8 and design["degf"] == 8

    for payload_term, oracle_term in [
        ("Intercept", "(Intercept)"), ("x1", "x1"), ("x2", "x2"),
    ]:
        entry = child["coefficients"][payload_term]
        assert entry["std_error"] == pytest.approx(oracle["se"][oracle_term], rel=1e-8)


def test_agent_can_switch_the_model_family_and_carry_the_new_family_options():
    """Switching family is a rerun override, and the Agent may ask for it.

    `resolve_overrides_target` has re-resolved the contract against the new
    `model_type` since v1.6.0, so the executor has always supported this; only
    the Agent's change whitelist stood in the way. Options for the target family
    ride `model_options`, which the same proposal already carries.
    """
    _validate_rerun({"model_type": "anova", "model_options": {"sums_of_squares": 3}})


def test_switching_to_a_family_that_needs_more_is_refused_by_the_engine_not_the_agent():
    """The Agent may *ask*; the target family's own contract still decides.

    Letting the proposal through is only safe because the override is validated
    against the target family's published params, so an under-specified switch
    fails there rather than producing a run configured by omission.
    """
    from workbench.lineage.op_contract import (
        OpOverrideError,
        resolve_overrides_target,
        validate_overrides,
    )
    from workbench.lineage.op_contract import _contract_for_model_type

    ols = _contract_for_model_type("ols")
    overrides = {"model_type": "anova", "entity_col": "psu"}
    target = resolve_overrides_target(ols, overrides)
    assert target.op_type == "anova", "the contract did not follow the switch"

    # `entity_col` is an OLS field; against the ANOVA contract it is unknown.
    with pytest.raises(OpOverrideError):
        validate_overrides(target, overrides)


def test_switching_family_on_a_rerun_actually_produces_the_new_family(tmp_path):
    """The switch the Agent may now propose, executed end to end.

    Structural agreement is not evidence that a family switch runs: the override
    has to survive contract re-resolution, the target family's own validation and
    the pipeline. This takes an OLS fitted on factorial data and reruns it as
    ANCOVA -- the continuous covariate is inherited from the parent, so the
    correct oracle is the ANCOVA one -- checking the child against R.
    """
    import json
    from pathlib import Path

    from fastapi.testclient import TestClient

    from workbench.api import app
    from workbench.artifacts import read_json
    from workbench.projects import create_project

    fixtures = Path(__file__).parent / "fixtures" / "anova"
    oracle = json.loads((fixtures / "oracle.json").read_text())["ancova"]["type_3"]

    project = create_project(tmp_path, "switch")
    source = project.root / "anova.csv"
    source.write_text((fixtures / "anova.csv").read_text())

    client = TestClient(app)
    with source.open("rb") as handle:
        created = client.post(
            "/runs",
            files={"file": ("anova.csv", handle, "text/csv")},
            data={
                "project_root": str(project.root), "mode": "auto", "model_type": "ols",
                "y": "score", "x": "factor_a,factor_b,covariate",
            },
        )
    assert created.status_code == 200, created.text
    parent_id = created.json()["run_id"]
    _await_run(client, project.root, parent_id)

    rerun = client.post(
        f"/runs/{parent_id}/rerun",
        params={"project_root": str(project.root)},
        json={
            "from_node": "model:ols_1",
            "op_overrides": {
                "model_type": "anova",
                "model_options": {
                    "sums_of_squares": 3,
                    "categorical": ["factor_a", "factor_b"],
                    "interactions": [["factor_a", "factor_b"]],
                },
            },
            "rerun_reason": "agent_confirmed",
        },
    )
    assert rerun.status_code == 200, rerun.text
    child_id = rerun.json()["run_id"]
    _await_run(client, project.root, child_id)

    results = project.root / "runs" / child_id / "model_results"
    produced = sorted(p.name for p in results.glob("*.json"))
    assert any(name.startswith("anova") for name in produced), (
        f"the switch was accepted but produced {produced}"
    )

    child = read_json(next(p for p in results.glob("anova*.json")))
    rows = {row["term"]: row for row in child["anova_table"]}
    assert child["sums_of_squares_type"] == 3
    checked = 0
    for term, expected in oracle.items():
        if term not in rows:
            continue
        checked += 1
        assert rows[term]["sum_sq"] == pytest.approx(expected["sum_sq"], rel=1e-8)
    assert checked >= 3, f"almost nothing was compared; produced terms {sorted(rows)}"
