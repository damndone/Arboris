"""The one confirmation entry point for a multi-step statistical workflow.

This file used to validate a server-side preset whose bindings named one
exercise's variables. The preset is gone; what remains is the contract that any
composed plan must satisfy.
"""

from __future__ import annotations

import pytest

from workbench.agent.operations import OperationRegistry, OperationValidationError


def _target() -> dict[str, str]:
    return {
        "run_id": "run-1",
        "node_ref": "stage:source",
        "artifact_id": "raw-1",
    }


def _preconditions() -> dict[str, str]:
    return {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": "sha256:context-1",
        "active_head_run_id": "run-1",
        "owner_resolution": "single_candidate",
    }


def _changes() -> dict[str, object]:
    return {
        "steps": [
            {
                "step_id": "describe",
                "operation_id": "statistical.explore",
                "spec": {
                    "operation": "summarize",
                    "selected_columns": ["outcome", "rate"],
                    "options": {"group_by": "wave"},
                },
            },
            {
                "step_id": "models",
                "operation_id": "model.genesis",
                "depends_on": ["describe"],
                "spec": {
                    "model_family": "ols",
                    "branches": [
                        {
                            "branch_id": "m1",
                            "outcome": "outcome",
                            "predictors": ["rate"],
                        }
                    ],
                },
            },
        ]
    }


def test_registry_exposes_one_confirmation_workflow_entry_point() -> None:
    registry = OperationRegistry()

    definition = registry.require("operation.multi_step")

    assert definition.natural_language_enabled is True
    assert definition.confirmation_policy == "required"
    changes_schema = definition.proposal_schema["properties"]["changes"]
    # A composed step list is the only accepted form; there is no named preset
    # a specific assignment could be privileged through.
    assert changes_schema["required"] == ["steps"]
    assert "bindings" not in changes_schema["properties"]
    assert "workflow_template" not in changes_schema["properties"]
    assert "operation.multi_step" not in {
        item["id"] for item in registry.boundary()["unsupported"]
    }


def test_a_composed_plan_validates() -> None:
    definition = OperationRegistry().require("operation.multi_step")

    definition.validate(
        target=_target(), preconditions=_preconditions(), changes=_changes()
    )


def test_semantic_fields_outside_the_step_contract_are_rejected() -> None:
    """The server owns statistical semantics; a plan may not restate them."""
    definition = OperationRegistry().require("operation.multi_step")

    for forbidden in ("quantile_method", "comparison", "missing_policy", "covariance"):
        changes = _changes()
        changes[forbidden] = "agent-choice"
        with pytest.raises(OperationValidationError, match="unknown field"):
            definition.validate(
                target=_target(), preconditions=_preconditions(), changes=changes
            )


def test_a_plan_without_steps_is_not_a_workflow() -> None:
    definition = OperationRegistry().require("operation.multi_step")

    for changes in ({}, {"steps": []}):
        with pytest.raises(OperationValidationError):
            definition.validate(
                target=_target(), preconditions=_preconditions(), changes=changes
            )


def test_the_grouping_column_is_whatever_the_plan_names() -> None:
    """No panel, wave set, or column name is privileged by the contract."""
    definition = OperationRegistry().require("operation.multi_step")

    for column, values in (
        ("wave", [1, 2, 3]),
        ("survey_year", [2000, 2005, 2010, 2015]),
        ("cohort", ["a", "b"]),
    ):
        changes = _changes()
        changes["steps"][0]["spec"]["options"] = {
            "group_by": column,
            "group_values": values,
        }
        changes["steps"][0]["spec"]["selected_columns"] = ["outcome"]
        definition.validate(
            target=_target(), preconditions=_preconditions(), changes=changes
        )
