from __future__ import annotations

import pytest


def _generic_auto_spec() -> dict[str, object]:
    return {
        "input_mode": "frame",
        "column_bindings": {"outcome": "y", "features": ["x"]},
        "options": {},
    }


def test_generic_model_auto_with_compiler_source_resolves_trusted_dispatcher() -> None:
    from workbench.agent.workflow_contracts import workflow_dispatcher_key

    spec = {
        **_generic_auto_spec(),
        "source": {"from_step": "prepared", "output": "produced_dataset"},
    }

    assert (
        workflow_dispatcher_key("model.auto", spec=spec)
        == "workbench.agent.workflow_runtime.workflow_capability"
    )


def test_selector_model_auto_variant_remains_resolvable() -> None:
    from workbench.agent.workflow_contracts import workflow_dispatcher_key

    assert (
        workflow_dispatcher_key(
            "model.auto",
            spec={
                "branches": [
                    {"branch_id": "ols", "outcome": "y", "predictors": ["x"]}
                ]
            },
        )
        == "workbench.agent.workflow_runtime.model_auto"
    )


def test_model_auto_unknown_field_still_fails_closed() -> None:
    from workbench.agent.operations import OperationValidationError
    from workbench.agent.workflow_contracts import validate_workflow_steps

    with pytest.raises(OperationValidationError, match="unsupported field.*unexpected"):
        validate_workflow_steps(
            [
                {
                    "step_id": "auto",
                    "operation_id": "model.auto",
                    "spec": {**_generic_auto_spec(), "unexpected": True},
                }
            ]
        )
