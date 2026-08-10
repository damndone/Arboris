"""Numerical and safety contracts for declaration-owned gap adapters."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def test_a_statistical_family_adapter_is_explicit_and_bounded() -> None:
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("test.correlations")
    request = {
        "operation_id": operation.operation_id,
        "input_mode": "frame",
        "column_bindings": {"columns": ["x", "y"]},
        "options": {},
    }
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 5.0, 8.0]})

    result = operation.execute(frame, operation.validate(request))
    operation.validate_result(result)

    assert result["operation_id"] == "test.correlations"
    assert result["family"] == "correlations"
    assert result["source_columns"] == ["x", "y"]
    assert result["result"]["test_type"] == "correlations"
    assert result["assumptions"]


def test_statistical_adapter_rejects_unbound_reference_mean() -> None:
    """An explicit one-sample target must not be silently dropped."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("test.evidence")
    with pytest.raises(ValueError, match="reference_means.*columns"):
        operation.validate(
            {
                "operation_id": operation.operation_id,
                "input_mode": "frame",
                "column_bindings": {"columns": ["x", "y"]},
                "options": {"reference_means": {"missing": 0.0}},
            }
        )


def test_statistical_adapter_rejects_malformed_paired_columns() -> None:
    """A malformed pair must fail closed instead of being ignored by the executor."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("test.evidence")
    with pytest.raises(ValueError, match="paired_columns"):
        operation.validate(
            {
                "operation_id": operation.operation_id,
                "input_mode": "frame",
                "column_bindings": {"columns": ["x", "y"]},
                "options": {"paired_columns": [["x"]]},
            }
        )


def test_prediction_adapter_uses_oos_protocol_and_declares_noncausal_output() -> None:
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("prediction.prediction_ridge")
    request = operation.validate(
        {
            "operation_id": operation.operation_id,
            "input_mode": "frame",
            "column_bindings": {"outcome": "y", "features": ["x1", "x2"]},
            "options": {"random_seed": 7, "cv_folds": 3},
        }
    )
    frame = pd.DataFrame(
        {
            "y": np.linspace(1.0, 12.0, 12),
            "x1": np.linspace(0.0, 11.0, 12),
            "x2": np.tile([0.0, 1.0], 6),
        }
    )

    result = operation.execute(frame, request)
    operation.validate_result(result)

    assert result["protocol"] == "predictive_research_v1"
    assert result["prediction_is_causal"] is False
    assert result["evaluation"]["oos_n"] > 0


def test_prediction_adapter_rejects_a_continuous_target_for_resampling() -> None:
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("resample.smote")
    with pytest.raises(ValueError, match="discrete target"):
        operation.execute(
            pd.DataFrame({"y": [0.1, 0.2, 0.3, 0.4], "x": [1, 2, 3, 4]}),
            operation.validate(
                {
                    "operation_id": operation.operation_id,
                    "input_mode": "frame",
                    "column_bindings": {"outcome": "y", "features": ["x"]},
                    "options": {"random_seed": 7},
                }
            ),
        )


def test_prediction_adapter_rejects_a_group_binding_for_iid_protocol() -> None:
    """A grouped-only binding must not be accepted and then ignored by IID."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("prediction.prediction_ridge")
    with pytest.raises(ValueError, match="group_column.*grouped"):
        operation.validate(
            {
                "operation_id": operation.operation_id,
                "input_mode": "frame",
                "column_bindings": {"outcome": "y", "features": ["x"]},
                "options": {
                    "data_structure": "iid",
                    "group_column": "unit",
                },
            }
        )


def test_prediction_adapter_rejects_an_absent_group_column() -> None:
    """A grouped request must report a typed source error, not leak a KeyError."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("prediction.prediction_ridge")
    request = operation.validate(
        {
            "operation_id": operation.operation_id,
            "input_mode": "frame",
            "column_bindings": {"outcome": "y", "features": ["x"]},
            "options": {"data_structure": "grouped", "group_column": "missing_group"},
        }
    )
    with pytest.raises(ValueError, match="source column.*absent"):
        operation.execute(
            pd.DataFrame({"y": np.linspace(1.0, 12.0, 12), "x": np.arange(12.0)}),
            request,
        )


def test_prediction_adapter_rejects_a_missing_group_identity() -> None:
    """Grouped prediction must not turn a missing group into the string ``nan``."""

    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("prediction.prediction_ridge")
    request = operation.validate(
        {
            "operation_id": operation.operation_id,
            "input_mode": "frame",
            "column_bindings": {"outcome": "y", "features": ["x"]},
            "options": {
                "data_structure": "grouped",
                "group_column": "unit",
                "cv_folds": 2,
            },
        }
    )
    frame = pd.DataFrame(
        {
            "y": np.linspace(1.0, 24.0, 24),
            "x": np.arange(24.0),
            "unit": [f"unit-{index % 6}" for index in range(24)],
        }
    )
    frame.loc[3, "unit"] = None

    with pytest.raises(ValueError, match="group column.*missing"):
        operation.execute(frame, request)


def test_auto_model_rejects_implicit_complete_case_row_removal() -> None:
    """Auto model selection must not silently discard rows with missing inputs."""

    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("model.auto")
    request = operation.validate(
        {
            "operation_id": operation.operation_id,
            "input_mode": "frame",
            "column_bindings": {"outcome": "y", "features": ["x"]},
            "options": {},
        }
    )
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, None, 4.0, 5.0, 6.0],
            "x": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )

    with pytest.raises(ValueError, match="missing"):
        operation.execute(frame, request)


def test_time_series_adapter_rejects_options_that_override_bound_columns() -> None:
    """Time-series source bindings are server-owned, not option overrides."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("model.time_series.ets")
    with pytest.raises(ValueError, match="server-owned binding"):
        operation.validate(
            {
                "operation_id": operation.operation_id,
                "input_mode": "frame",
                "column_bindings": {"time": "when", "value": "value"},
                "options": {
                    "time_index_semantics": "observation_order",
                    "value_column": "attacker_value",
                },
            }
        )


def test_time_series_adapter_rejects_undeclared_options() -> None:
    """An option absent from the selected pack contract must not be ignored."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("model.time_series.ets")
    with pytest.raises(ValueError, match="unsupported option"):
        operation.validate(
            {
                "operation_id": operation.operation_id,
                "input_mode": "frame",
                "column_bindings": {"time": "when", "value": "value"},
                "options": {
                    "time_index_semantics": "observation_order",
                    "typo_policy": "ignore",
                },
            }
        )


def test_imputation_adapter_rejects_unimplemented_multiple_imputation_count() -> None:
    """An option the adapter cannot execute must fail rather than be ignored."""
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("imputation.mice")
    with pytest.raises(ValueError, match="m"):
        operation.validate(
            {
                "operation_id": operation.operation_id,
                "input_mode": "frame",
                "column_bindings": {"columns": ["x", "y"]},
                "options": {"m": 5},
            }
        )
