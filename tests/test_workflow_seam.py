"""P0 composition seam: a step consuming the dataset another step produced.

These invariants belong to the composition itself: the declared source resolves,
the referenced step really produces a dataset, and the downstream step reads
that output rather than the raw data.
"""

from __future__ import annotations

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
