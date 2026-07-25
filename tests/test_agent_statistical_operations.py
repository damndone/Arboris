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


def _bindings() -> dict[str, object]:
    return {
        "year_column": "year",
        "spending_column": "adj_dppupil_comp",
        "black_column": "pblack",
        "poverty_column": "pfl",
        "enrollment_column": "totreg",
        "all_numeric_columns": ["bdsnew", "year", "middle", "pfl", "pblack", "totreg", "adj_dppupil_comp"],
        "group_values": [1998, 2002, 2006, 2010, 2014, 2016],
    }


def _changes() -> dict[str, object]:
    return {
        "workflow_template": "class3-stata-v1",
        "bindings": _bindings(),
    }


def test_registry_exposes_one_confirmation_workflow_entry_point() -> None:
    registry = OperationRegistry()

    definition = registry.require("operation.multi_step")

    assert definition.natural_language_enabled is True
    assert definition.confirmation_policy == "required"
    changes_schema = definition.proposal_schema["properties"]["changes"]
    # Either an Agent-composed plan or the legacy preset binding, never neither.
    assert changes_schema["anyOf"] == [
        {"required": ["steps"]},
        {"required": ["workflow_template", "bindings"]},
    ]
    assert "operation.multi_step" not in {
        item["id"] for item in registry.boundary()["unsupported"]
    }


def test_workflow_validator_accepts_only_evidence_backed_bindings() -> None:
    definition = OperationRegistry().require("operation.multi_step")

    definition.validate(target=_target(), preconditions=_preconditions(), changes=_changes())

    for forbidden in ("quantile_method", "comparison", "missing_policy", "covariance"):
        changes = _changes()
        changes[forbidden] = "agent-choice"
        with pytest.raises(OperationValidationError, match="unknown field"):
            definition.validate(
                target=_target(), preconditions=_preconditions(), changes=changes
            )


def test_workflow_validator_accepts_any_panel_but_rejects_a_malformed_group_set() -> None:
    """Group values are the assignment's, not one fixed exercise's.

    Existence is proved later against the real column (see
    ``compile_step_bindings(group_value_witness=...)``); what the proposal
    validator owns is shape, so a duplicated or empty set still fails here.
    """
    definition = OperationRegistry().require("operation.multi_step")

    for accepted in ([1998, 2002, 2006], [2000, 2005, 2010, 2015], ["w1", "w2"]):
        changes = _changes()
        changes["bindings"] = {**changes["bindings"], "group_values": accepted}
        definition.validate(
            target=_target(), preconditions=_preconditions(), changes=changes
        )

    for rejected in ([], [1998, 1998]):
        changes = _changes()
        changes["bindings"] = {**changes["bindings"], "group_values": rejected}
        with pytest.raises(OperationValidationError, match="group_values"):
            definition.validate(
                target=_target(), preconditions=_preconditions(), changes=changes
            )
