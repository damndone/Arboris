"""A plan of a shape no template describes must compile and execute."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationRegistry, OperationValidationError
from workbench.agent.workflow_contracts import (
    WORKFLOW_STEP_OPERATIONS,
    WORKFLOW_STEP_SPEC_CONTRACTS,
    _validate_step_spec,
)
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "south"] * 20,
            "revenue": [100.0 + index * 1.5 for index in range(40)],
            "headcount": [10 + index for index in range(40)],
            "rnd_share": [float(index % 19) for index in range(40)],
            "export_share": [float(index % 11) for index in range(40)],
        }
    )


def _plan() -> list[dict]:
    """Not this repo's reference exercise: 2 groups, a decile split, 3 models."""
    return [
        {
            "step_id": "describe",
            "operation_id": "statistical.explore",
            "spec": {
                "operation": "summarize",
                "selected_columns": ["revenue", "headcount", "rnd_share", "export_share"],
                "options": {"group_by": "region", "group_values": ["north", "south"]},
            },
        },
        {
            "step_id": "detail",
            "operation_id": "statistical.explore",
            "spec": {
                "operation": "summarize_detail",
                "selected_columns": ["headcount"],
                "options": {"quantile_method": "stata_summarize_detail_v1"},
            },
        },
        {
            "step_id": "split",
            "operation_id": "statistical.derive_boolean",
            "depends_on": ["detail"],
            "spec": {
                "operation": "derive_boolean",
                "recipes": [
                    {"source_column": "headcount", "percentile": 90, "comparison": "gte", "output_name": "top_decile"},
                ],
            },
        },
        {
            "step_id": "compare",
            "operation_id": "statistical.derived_group_summarize",
            "depends_on": ["split", "detail"],
            "spec": {
                "groups": [
                    {"source_column": "headcount", "percentile": 90, "comparison": "gte", "output_name": "top_decile"},
                ],
                "summarize_columns": ["revenue"],
            },
        },
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "depends_on": ["describe", "compare"],
            "spec": {
                "model_family": "ols",
                "covariance": "unadjusted",
                "branches": [
                    {"branch_id": "m1", "outcome": "revenue", "predictors": ["rnd_share"]},
                    {"branch_id": "m2", "outcome": "revenue", "predictors": ["rnd_share", "export_share"]},
                    {"branch_id": "m3", "outcome": "revenue", "predictors": ["rnd_share", "export_share", "headcount"]},
                ],
            },
        },
    ]


def test_an_arbitrary_agent_composed_plan_compiles(tmp_path):
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    draft = compile_workflow(
        workflow_id="wf-generic",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        steps=_plan(),
        available_columns=list(_frame().columns),
    )

    assert [step.step_id for step in draft.steps] == [
        "describe", "detail", "split", "compare", "models",
    ]
    assert len(draft.steps[4].spec["branches"]) == 3
    assert draft.workflow_template == "agent-composed-v1"


def test_the_arbitrary_plan_executes_its_exploration_steps(tmp_path):
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    steps = [item for item in _plan() if item["operation_id"] != "model.genesis"]
    draft = compile_workflow(
        workflow_id="wf-generic-run",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        steps=steps,
        available_columns=list(_frame().columns),
    )

    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))

    assert state.status == "completed"
    assert {step.status for step in state.steps.values()} == {"completed"}


def test_a_derived_column_is_available_to_later_steps(tmp_path):
    """`top_decile` exists only because an earlier step creates it."""
    compile_workflow(
        workflow_id="wf-produced",
        target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
        preconditions={"context_fingerprint": "fp"},
        steps=[
            _plan()[1],
            _plan()[2],
            {
                "step_id": "use",
                "operation_id": "statistical.explore",
                "depends_on": ["split"],
                "spec": {
                    "operation": "summarize",
                    "selected_columns": ["revenue"],
                    "filters": [{"column": "top_decile", "operator": "eq", "value": True}],
                },
            },
        ],
        available_columns=list(_frame().columns),
    )


def test_numeric_derived_columns_are_typed_and_available_to_later_steps(tmp_path):
    """A workflow may name safe transforms, never an executable expression."""

    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    steps = [
        {
            "step_id": "transform",
            "operation_id": "statistical.derive_numeric",
            "spec": {
                "recipes": [
                    {
                        "operator": "natural_log",
                        "input_columns": ["headcount"],
                        "output_name": "log_headcount",
                    },
                    {
                        "operator": "multiply",
                        "input_columns": ["rnd_share", "export_share"],
                        "output_name": "rnd_export_product",
                    },
                ]
            },
        },
        {
            "step_id": "describe_transform",
            "operation_id": "statistical.explore",
            "depends_on": ["transform"],
            "spec": {"operation": "summarize", "selected_columns": ["log_headcount", "rnd_export_product"]},
        },
    ]
    draft = compile_workflow(
        workflow_id="wf-numeric-derived",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        steps=steps,
        available_columns=list(_frame().columns),
    )

    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))

    assert state.status == "completed"
    assert state.steps["transform"].artifact_ids
    assert state.steps["describe_transform"].status == "completed"
    records = {
        item["artifact_id"]: item
        for item in json.loads(
            (project / "runs" / run_id / "artifacts_index.json").read_text(
                encoding="utf-8"
            )
        )["artifacts"]
    }
    data_record = records[state.steps["transform"].artifact_ids[0]]
    derived = pd.read_csv(project / "runs" / run_id / data_record["path"])
    assert derived["log_headcount"].iloc[0] == pytest.approx(2.302585093)
    assert derived["rnd_export_product"].iloc[23] == pytest.approx(4.0)


@pytest.mark.parametrize(
    "recipe, message",
    [
        (
            {
                "operator": "formula",
                "input_columns": ["headcount"],
                "output_name": "derived_value",
            },
            "operator must be natural_log or multiply",
        ),
        (
            {
                "operator": "natural_log",
                "input_columns": ["headcount"],
                "output_name": "headcount",
            },
            "output column already exists",
        ),
        (
            {
                "operator": "multiply",
                "input_columns": ["headcount", "headcount"],
                "output_name": "squared_headcount",
            },
            "requires 2 distinct input column",
        ),
    ],
)
def test_numeric_derivation_contract_refuses_code_and_unsafe_shapes(recipe, message):
    with pytest.raises(OperationValidationError, match=message):
        compile_workflow(
            workflow_id="wf-numeric-contract-rejection",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=[
                {
                    "step_id": "transform",
                    "operation_id": "statistical.derive_numeric",
                    "spec": {"recipes": [recipe]},
                }
            ],
            available_columns=list(_frame().columns),
        )


def test_numeric_derivation_fails_closed_for_invalid_observed_values(tmp_path):
    frame = _frame()
    frame.loc[0, "headcount"] = 0
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="wf-numeric-domain-rejection",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        steps=[
            {
                "step_id": "transform",
                "operation_id": "statistical.derive_numeric",
                "spec": {
                    "recipes": [
                        {
                            "operator": "natural_log",
                            "input_columns": ["headcount"],
                            "output_name": "log_headcount",
                        }
                    ]
                },
            }
        ],
        available_columns=list(frame.columns),
    )

    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))

    assert state.status == "failed"
    assert state.steps["transform"].status == "failed"
    assert "strictly positive" in str(state.steps["transform"].error)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p[0]["spec"].__setitem__("selected_columns", ["nope"]), "missing column"),
        (lambda p: p[0].__setitem__("operation_id", "code.execute"), "unsupported"),
        (lambda p: p[0].__setitem__("step_id", p[1]["step_id"]), "duplicate"),
        (lambda p: p[2].__setitem__("depends_on", ["ghost"]), "unknown step"),
        (lambda p: p[0]["spec"].__setitem__("operation", "regress"), "invalid statistical.explore"),
        (lambda p: p[4]["spec"]["branches"][0].__setitem__("covariance", "HC3"), "covariance"),
        (lambda p: p[4]["spec"]["branches"][1].__setitem__("branch_id", "m1"), "duplicate model branch"),
    ],
)
def test_a_malformed_plan_fails_closed(tmp_path, mutate, message):
    plan = _plan()
    mutate(plan)
    with pytest.raises(OperationValidationError, match=message):
        compile_workflow(
            workflow_id="wf-bad",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=plan,
            available_columns=list(_frame().columns),
        )


def test_a_dependency_cycle_is_refused_rather_than_looping():
    with pytest.raises(OperationValidationError, match="cycle"):
        compile_workflow(
            workflow_id="wf-cycle",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=[
                {"step_id": "a", "operation_id": "statistical.explore",
                 "depends_on": ["b"], "spec": {"operation": "misstable", "selected_columns": ["revenue"]}},
                {"step_id": "b", "operation_id": "statistical.explore",
                 "depends_on": ["a"], "spec": {"operation": "misstable", "selected_columns": ["revenue"]}},
            ],
        )


def test_percentile_evidence_is_found_through_an_intermediate_step(tmp_path):
    """A live agent routed the threshold evidence through the derive step.

    step_group depends on step_derive, which depends on step_detail. Requiring
    a direct edge to the detail step would reject that correct plan.
    """
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    draft = compile_workflow(
        workflow_id="wf-transitive",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        steps=[
            {
                "step_id": "step_detail",
                "operation_id": "statistical.explore",
                "spec": {"operation": "summarize_detail", "selected_columns": ["headcount"]},
            },
            {
                "step_id": "step_derive",
                "operation_id": "statistical.derive_boolean",
                "depends_on": ["step_detail"],
                "spec": {
                    "operation": "derive_boolean",
                    "recipes": [
                        {"source_column": "headcount", "percentile": 75,
                         "comparison": "gte", "output_name": "large"},
                    ],
                },
            },
            {
                "step_id": "step_group",
                "operation_id": "statistical.derived_group_summarize",
                # Only the derivation is named — the detail evidence is reached
                # through it.
                "depends_on": ["step_derive"],
                "spec": {
                    "groups": [
                        {"source_column": "headcount", "percentile": 75,
                         "comparison": "gte", "output_name": "large"},
                    ],
                    "summarize_columns": ["revenue"],
                },
            },
        ],
        available_columns=list(_frame().columns),
    )

    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))

    assert state.status == "completed"
    assert state.steps["step_group"].status == "completed"


def test_every_natural_language_operation_can_read_its_own_contract() -> None:
    """An operation an Agent may propose must be able to state its own shape.

    ``operation.multi_step`` answered ``no contract for operation.multi_step@v1``
    because the resolver only fell back to the registry for ``data_node``-scoped
    operations. A live agent asked to compose a workflow burned its entire step
    budget re-inspecting nodes and never wrote a plan.
    """

    registry = OperationRegistry()

    for definition in registry._definitions.values():
        if not definition.natural_language_enabled:
            continue
        assert definition.editable_schema, (
            f"{definition.operation_id} is Agent-facing but publishes no editable schema"
        )
        if definition.contract_owner == "operation_registry":
            assert "lineage" not in definition.scope_requirements


def test_multi_step_contract_is_registry_owned_and_admits_composed_steps() -> None:
    definition = OperationRegistry().require("operation.multi_step")

    assert definition.contract_owner == "operation_registry"
    # A composed step list is the editable surface, and now the only one: the
    # schema used to also admit a named preset whose bindings were a single
    # exercise's variables.
    assert definition.editable_schema["required"] == ["steps"]
    assert "steps" in definition.editable_schema["properties"]
    assert "bindings" not in definition.editable_schema["properties"]
    assert "workflow_template" not in definition.editable_schema["properties"]


def test_published_step_vocabulary_covers_every_composable_operation() -> None:
    """The vocabulary is what an Agent reads *before* guessing field names."""

    definition = OperationRegistry().require("operation.multi_step")
    assert definition.vocabulary_builder is not None

    vocabulary = definition.vocabulary_builder()
    published = vocabulary["step_operations"]

    assert set(published) == set(WORKFLOW_STEP_OPERATIONS)
    for operation_id, entry in published.items():
        assert entry["summary"]
        assert entry["fields"], f"{operation_id} publishes no field vocabulary"
        assert set(entry["required"]) <= set(entry["fields"])

    # The exact traps that cost two live execution failures must be stated,
    # not left for the agent to discover by failing.
    explore = published["statistical.explore"]["fields"]
    assert "selected_columns" in explore and "NOT `columns`" in explore["selected_columns"]
    assert "group_by" in explore["options"]
    assert vocabulary["reported_percentiles"] == [1, 5, 10, 25, 50, 75, 90, 95, 99]
    assert published["model.joint_f_test"]["required"] == [
        "branch_id",
        "term_selectors",
    ]
    assert published["model.quadratic_stationary_point"]["required"] == [
        "branch_id",
        "column",
    ]


@pytest.mark.parametrize(
    "operation_id, spec, message",
    [
        (
            "model.joint_f_test",
            {
                "branch_id": "candidate",
                "term_selectors": [{"kind": "formula", "column": "revenue"}],
            },
            "selector kind",
        ),
        (
            "model.joint_f_test",
            {
                "branch_id": "candidate",
                "term_selectors": [
                    {"kind": "linear", "column": "revenue", "formula": "x + z"}
                ],
            },
            "unsupported field",
        ),
        (
            "model.quadratic_stationary_point",
            {"branch_id": "candidate", "column": "unknown"},
            "missing column",
        ),
    ],
)
def test_post_estimation_specs_fail_closed(
    operation_id: str,
    spec: dict,
    message: str,
) -> None:
    with pytest.raises(OperationValidationError, match=message):
        compile_workflow(
            workflow_id="wf-post-estimation-invalid",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=[
                {
                    "step_id": "post_estimation",
                    "operation_id": operation_id,
                    "spec": spec,
                }
            ],
            available_columns=list(_frame().columns),
        )


def test_step_vocabulary_and_validator_share_one_source_of_truth() -> None:
    """Drift here would publish field names the validator then rejects."""

    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items():
        spec = {name: None for name in contract.fields}
        # Unknown-field rejection must accept exactly the published set, so
        # this may fail on *values* but never on an unsupported field name.
        try:
            _validate_step_spec(operation_id, spec)
        except OperationValidationError as exc:
            assert "unsupported field" not in str(exc), (
                f"{operation_id} publishes a field its validator rejects: {exc}"
            )


def test_required_ols_diagnostics_are_derived_from_the_branch_predictors() -> None:
    """The diagnostics gate must follow the model, not one exercise's columns.

    It required ``residuals_vs_pfl``/``fitted_vs_pfl`` for every branch whose id
    was not the literal ``ols_pblack``, so a correct single-predictor branch
    under any other name failed with "missing residual/fitted diagnostics" —
    observed live on a clean project.
    """
    from workbench.agent.workflow_runtime import required_branch_figures

    assert required_branch_figures(["pblack"]) == {
        "residuals_vs_pblack",
        "fitted_vs_pblack",
    }
    # Any other assignment's columns work identically; nothing is privileged.
    assert required_branch_figures(["rnd_share", "export_share"]) == {
        "residuals_vs_rnd_share",
        "fitted_vs_rnd_share",
        "residuals_vs_export_share",
        "fitted_vs_export_share",
    }
    assert required_branch_figures([]) == set()


def test_a_branch_with_dummies_and_a_polynomial_validates_and_expands(tmp_path):
    """Composing dummies and powers must survive the proposal validator."""
    frame = _frame().assign(wave=[1998, 2002, 2006, 2010] * 10)
    plan = [
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "spec": {
                "model_family": "ols",
                "branches": [
                    {
                        "branch_id": "with_terms",
                        "outcome": "revenue",
                        "predictors": ["rnd_share", "headcount"],
                        "categorical": ["wave", "region"],
                        "polynomials": [{"column": "headcount", "degree": 2}],
                    }
                ],
            },
        }
    ]
    draft = compile_workflow(
        workflow_id="wf-terms",
        target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
        preconditions={"context_fingerprint": "fp"},
        steps=plan,
        available_columns=list(frame.columns),
    )

    from workbench.model_terms import expand_branch_terms

    branch = draft.steps[0].spec["branches"][0]
    _, predictors, references = expand_branch_terms(frame, branch)
    assert predictors == [
        "rnd_share", "headcount",
        "wave_2002", "wave_2006", "wave_2010",
        "region_south",
        "headcount_pow2",
    ]
    assert references == {"wave": 1998, "region": "north"}


def test_a_dummy_column_typo_is_caught_by_the_schema_check():
    """Derived-term sources are real columns and must be checked as such."""
    with pytest.raises(OperationValidationError, match="missing column"):
        compile_workflow(
            workflow_id="wf-typo",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=[
                {
                    "step_id": "models",
                    "operation_id": "model.genesis",
                    "spec": {
                        "model_family": "ols",
                        "branches": [
                            {
                                "branch_id": "b",
                                "outcome": "revenue",
                                "predictors": ["rnd_share"],
                                "categorical": ["reigon"],
                            }
                        ]
                    },
                }
            ],
            available_columns=list(_frame().columns),
        )


def test_the_validator_refuses_a_branch_the_executor_could_not_build():
    """Validation and construction share one module, so this cannot drift."""
    with pytest.raises(OperationValidationError, match="both a linear predictor"):
        compile_workflow(
            workflow_id="wf-conflict",
            target={"run_id": "r", "node_ref": "n", "artifact_id": "a"},
            preconditions={"context_fingerprint": "fp"},
            steps=[
                {
                    "step_id": "models",
                    "operation_id": "model.genesis",
                    "spec": {
                        "model_family": "ols",
                        "branches": [
                            {
                                "branch_id": "b",
                                "outcome": "revenue",
                                "predictors": ["rnd_share", "region"],
                                "categorical": ["region"],
                            }
                        ]
                    },
                }
            ],
            available_columns=list(_frame().columns),
        )
