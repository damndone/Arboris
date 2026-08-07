"""P0 composition seam: a step declaring its input as another step's output.

This slice covers the declaration itself, which belongs to the composition
rather than to any one operation's spec contract: a well-formed `source` is
accepted and preserved, and every malformed shape is refused by name.
"""

from __future__ import annotations

import pytest

from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow_contracts import validate_workflow_steps


def _numeric_step(step_id: str, output_name: str) -> dict:
    return {
        "step_id": step_id,
        "operation_id": "statistical.derive_numeric",
        "spec": {
            "recipes": [
                {
                    "operator": "multiply",
                    "input_columns": ["size", "weight"],
                    "output_name": output_name,
                }
            ]
        },
    }


def test_step_spec_accepts_a_source_commitment() -> None:
    """A step may declare that its input is another step's output."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "first", "output": "produced_dataset"}
    steps = [_numeric_step("first", "doubled"), downstream]

    ordered = validate_workflow_steps(steps)

    assert [item["step_id"] for item in ordered] == ["first", "second"]
    assert ordered[1]["spec"]["source"] == {
        "from_step": "first",
        "output": "produced_dataset",
    }


def _step_with_source(source: object) -> list[dict]:
    """One otherwise-valid plan whose single step carries the given source."""

    step = _numeric_step("only", "doubled")
    step["spec"]["source"] = source
    return [step]


def test_explicit_null_source_is_rejected_rather_than_dropped() -> None:
    """A written-out `source: null` is a malformed commitment, not an absent one."""

    with pytest.raises(
        OperationValidationError, match=r"step only source must be an object"
    ):
        validate_workflow_steps(_step_with_source(None))


def test_non_object_source_is_rejected() -> None:
    """A bare step id is not a source commitment."""

    with pytest.raises(
        OperationValidationError, match=r"step only source must be an object"
    ):
        validate_workflow_steps(_step_with_source("first"))


def test_source_with_unknown_field_is_rejected() -> None:
    """Naming the unknown field is what lets the author correct it."""

    with pytest.raises(
        OperationValidationError,
        match=r"step only source contains unknown field\(s\): column",
    ):
        validate_workflow_steps(
            _step_with_source(
                {"from_step": "first", "output": "produced_dataset", "column": "size"}
            )
        )


@pytest.mark.parametrize("from_step", ["", 7, None])
def test_source_without_a_usable_from_step_is_rejected(from_step: object) -> None:
    """from_step must actually name a step."""

    with pytest.raises(
        OperationValidationError,
        match=r"step only source\.from_step must name another step in this plan",
    ):
        validate_workflow_steps(
            _step_with_source({"from_step": from_step, "output": "produced_dataset"})
        )


def test_source_output_outside_the_supported_set_is_rejected() -> None:
    """The output key is a closed set, so a near-miss fails loudly."""

    with pytest.raises(
        OperationValidationError,
        match=r"step only source\.output must be one of: produced_dataset",
    ):
        validate_workflow_steps(
            _step_with_source({"from_step": "first", "output": "produced_data"})
        )


def test_malformed_from_step_is_a_format_error_not_an_unknown_step() -> None:
    """A from_step that cannot be a step id must be named as malformed.

    Reporting it as an unresolvable reference would send the author looking for
    a missing step instead of at the id they mistyped.
    """

    with pytest.raises(
        OperationValidationError,
        match=r"step only source\.from_step must name another step in this plan",
    ):
        validate_workflow_steps(
            _step_with_source({"from_step": "not an id!!", "output": "produced_dataset"})
        )


def test_source_commitment_to_an_unknown_step_is_rejected() -> None:
    """A dangling reference is a compile error, not a runtime surprise."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "absent", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match="unknown step"):
        validate_workflow_steps([_numeric_step("first", "doubled"), downstream])


def test_source_commitment_to_itself_is_rejected() -> None:
    """A step cannot be its own input; that is a plan with no starting point."""

    step = _numeric_step("only", "doubled")
    step["spec"]["source"] = {"from_step": "only", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match="refers to itself"):
        validate_workflow_steps([step])


def test_source_commitment_to_a_step_that_produces_no_dataset_is_rejected() -> None:
    """Only steps that persist a dataset can be consumed as an input."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "explored", "output": "produced_dataset"}
    steps = [
        {
            "step_id": "explored",
            "operation_id": "statistical.explore",
            "spec": {"operation": "corr", "selected_columns": ["size", "outcome"]},
        },
        downstream,
    ]

    with pytest.raises(OperationValidationError, match="does not produce a dataset"):
        validate_workflow_steps(steps)


def test_source_commitment_implies_a_dependency() -> None:
    """Declaring an input is declaring an ordering; the DAG must reflect it."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "first", "output": "produced_dataset"}

    ordered = validate_workflow_steps([downstream, _numeric_step("first", "doubled")])

    assert [item["step_id"] for item in ordered] == ["first", "second"]
    assert ordered[1]["depends_on"] == ["first"]


def test_source_commitment_cannot_form_a_cycle() -> None:
    """A reference is a dependency, so the existing cycle refusal covers it."""

    first = _numeric_step("first", "doubled")
    first["spec"]["source"] = {"from_step": "second", "output": "produced_dataset"}
    second = _numeric_step("second", "doubled_again")
    second["spec"]["source"] = {"from_step": "first", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match="cycle"):
        validate_workflow_steps([first, second])
