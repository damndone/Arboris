from __future__ import annotations

import pytest

from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow import compile_class3_workflow
from workbench.agent.workflow_contracts import compile_step_bindings


_BINDINGS = {
    "year_column": "year",
    "spending_column": "adj_dppupil_comp",
    "black_column": "pblack",
    "poverty_column": "pfl",
    "enrollment_column": "totreg",
    "all_numeric_columns": ["bdsnew", "year", "pfl", "pblack", "totreg", "adj_dppupil_comp"],
    "group_values": [1998, 2002, 2006, 2010, 2014, 2016],
}


def _compiled():
    return compile_class3_workflow(
        workflow_id="wf-class3",
        target={"run_id": "run-1", "node_ref": "stage:raw", "artifact_id": "raw-1"},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:source-1",
            "active_head_run_id": "run-1",
            "owner_resolution": "single_candidate",
        },
        bindings=_BINDINGS,
        available_columns=[
            "bdsnew", "year", "pfl", "pblack", "totreg", "adj_dppupil_comp"
        ],
    )


def test_class3_compiles_to_nine_server_owned_steps() -> None:
    draft = _compiled()

    assert draft.status == "planned"
    assert [step.step_id for step in draft.steps] == [f"step-{index}" for index in range(1, 10)]
    assert [step.operation_id for step in draft.steps] == [
        "statistical.explore",
        "statistical.explore",
        "statistical.explore",
        "statistical.explore",
        "statistical.derive_boolean",
        "statistical.derived_group_summarize",
        "statistical.explore",
        "model.genesis",
        "report.class3",
    ]
    assert draft.steps[4].depends_on == ("step-4",)
    assert all(
        recipe["threshold_ref"] == {"step_id": "step-4", "artifact_role": "result"}
        for recipe in draft.steps[4].spec["recipes"]
    )
    assert draft.steps[7].spec["covariance"] == "unadjusted"
    assert len(draft.steps[7].spec["branches"]) == 2
    assert all(
        branch["covariance"] == "unadjusted"
        for branch in draft.steps[7].spec["branches"]
    )
    assert set(draft.steps[7].expected_artifacts) >= {
        "coefficient_ci",
        "sample_size",
        "residual_diagnostics",
        "fitted_diagnostics",
    }
    assert set(draft.steps[8].depends_on) == {f"step-{index}" for index in range(1, 9)}
    assert "code.execute" not in {step.operation_id for step in draft.steps}
    assert draft.plan_fingerprint.startswith("sha256:")


def test_compile_rejects_missing_schema_columns_before_artifacts() -> None:
    with pytest.raises(OperationValidationError, match="source columns missing: .*pblack"):
        compile_class3_workflow(
            workflow_id="wf-class3",
            target={"run_id": "run-1", "node_ref": "stage:raw", "artifact_id": "raw-1"},
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "sha256:source-1",
                "active_head_run_id": "run-1",
                "owner_resolution": "single_candidate",
            },
            bindings={**_BINDINGS, "black_column": "pblack"},
            available_columns=["year", "adj_dppupil_comp", "pfl", "totreg"],
        )


def test_compile_bindings_rejects_agent_semantic_fields() -> None:
    with pytest.raises(OperationValidationError, match="unknown field"):
        compile_step_bindings(
            {**_BINDINGS, "quantile_method": "pandas_linear"},
            available_columns=list(_BINDINGS["all_numeric_columns"]),
        )


def test_group_values_are_validated_against_the_data_not_pinned_to_one_exercise():
    """The workflow must serve any panel, not only the 1998-2016 reference set.

    Pinning the six Class 3 years made every other assignment unproposable, so
    the guard is now a data witness: the requested values must actually occur
    in the chosen grouping column.
    """
    other_panel = {**_BINDINGS, "group_values": [2000, 2005, 2010]}

    bound = compile_step_bindings(
        other_panel,
        available_columns=list(_BINDINGS["all_numeric_columns"]) + [_BINDINGS["year_column"]],
        group_value_witness=[2000, 2005, 2010, 2015],
    )

    assert bound["group_values"] == [2000, 2005, 2010]


def test_group_values_absent_from_the_column_fail_closed():
    with pytest.raises(OperationValidationError, match="group_values"):
        compile_step_bindings(
            {**_BINDINGS, "group_values": [2000, 1899]},
            available_columns=list(_BINDINGS["all_numeric_columns"]) + [_BINDINGS["year_column"]],
            group_value_witness=[2000, 2005],
        )


def test_group_values_must_be_unique_and_non_empty():
    for bad in ([], [2000, 2000]):
        with pytest.raises(OperationValidationError, match="group_values"):
            compile_step_bindings(
                {**_BINDINGS, "group_values": bad},
                available_columns=list(_BINDINGS["all_numeric_columns"])
                + [_BINDINGS["year_column"]],
                group_value_witness=[2000, 2005],
            )
