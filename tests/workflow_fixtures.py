"""Composed workflow plans for tests, deliberately not any one assignment.

These fixtures replaced a server-side preset whose bindings were one course
exercise's variables. The column names here are generic on purpose: if a test
needs a "poverty rate" or a fixed set of survey years to pass, that test is
describing an exercise rather than a contract.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def fixture_frame() -> pd.DataFrame:
    """A small panel with a grouping column, two rates, and a size measure."""

    return pd.DataFrame(
        {
            "unit_id": [1000 + index for index in range(24)],
            "wave": [1, 2, 3] * 8,
            "outcome": [100.0 + index * 2.5 for index in range(24)],
            "rate_a": [float(index % 17) for index in range(24)],
            "rate_b": [float(index % 13) for index in range(24)],
            "size": [200 + index * 7 for index in range(24)],
        }
    )


FIXTURE_COLUMNS = list(fixture_frame().columns)


def composed_plan() -> list[dict[str, Any]]:
    """A multi-step plan exercising every composable step kind.

    Shaped like real work (group descriptives, detail percentiles, a derived
    split, a group comparison, a scatter, two models, a report) without being
    tied to a particular assignment's wording.
    """

    return [
        {
            "step_id": "grouped",
            "operation_id": "statistical.explore",
            "spec": {
                "operation": "summarize",
                "selected_columns": ["outcome", "rate_a", "rate_b", "size"],
                "options": {"group_by": "wave"},
            },
        },
        {
            "step_id": "missing",
            "operation_id": "statistical.explore",
            "spec": {"operation": "misstable", "selected_columns": ["rate_a", "rate_b"]},
        },
        {
            "step_id": "correlations",
            "operation_id": "statistical.explore",
            "spec": {
                "operation": "corr",
                "selected_columns": ["outcome", "rate_a", "rate_b", "size"],
                "options": {"missing_policy": "listwise"},
            },
        },
        {
            "step_id": "detail",
            "operation_id": "statistical.explore",
            "spec": {"operation": "summarize_detail", "selected_columns": ["size", "rate_b"]},
        },
        {
            "step_id": "split",
            "operation_id": "statistical.derive_boolean",
            "depends_on": ["detail"],
            "spec": {
                "recipes": [
                    {
                        "source_column": "size",
                        "percentile": 25,
                        "comparison": "lte",
                        "output_name": "small_unit",
                    },
                    {
                        "source_column": "size",
                        "percentile": 75,
                        "comparison": "gte",
                        "output_name": "large_unit",
                    },
                ]
            },
        },
        {
            "step_id": "compare",
            "operation_id": "statistical.derived_group_summarize",
            "depends_on": ["split"],
            "spec": {
                "groups": [
                    {
                        "source_column": "size",
                        "percentile": 25,
                        "comparison": "lte",
                        "output_name": "small_unit",
                    },
                    {
                        "source_column": "size",
                        "percentile": 75,
                        "comparison": "gte",
                        "output_name": "large_unit",
                    },
                ],
                "summarize_columns": ["outcome"],
            },
        },
        {
            "step_id": "scatter",
            "operation_id": "statistical.explore",
            "spec": {
                "operation": "scatter",
                "plots": [
                    {"x_column": "rate_b", "y_column": "outcome"},
                    {"x_column": "size", "y_column": "outcome"},
                ],
            },
        },
        {
            "step_id": "models",
            "operation_id": "model.genesis",
            "spec": {
                "model_family": "ols",
                "covariance": "unadjusted",
                "branches": [
                    {"branch_id": "m1", "outcome": "outcome", "predictors": ["rate_a"]},
                    {
                        "branch_id": "m2",
                        "outcome": "outcome",
                        "predictors": ["rate_a", "rate_b"],
                    },
                ],
            },
        },
        {
            "step_id": "report",
            "operation_id": "report.compose",
            "depends_on": [
                "grouped",
                "missing",
                "correlations",
                "detail",
                "split",
                "compare",
                "scatter",
                "models",
            ],
            "spec": {"sections": ["descriptives", "correlations", "models"]},
        },
    ]


def compile_fixture_workflow(
    *,
    workflow_id: str = "wf-fixture",
    source_fingerprint: str = "sha256:source-1",
    steps: list[dict[str, Any]] | None = None,
    target: dict[str, Any] | None = None,
    available_columns: list[str] | None = None,
):
    from workbench.agent.workflow import compile_workflow

    return compile_workflow(
        workflow_id=workflow_id,
        target=target
        or {"run_id": "run-1", "node_ref": "stage:raw", "artifact_id": "raw-1"},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": source_fingerprint,
            "active_head_run_id": "run-1",
            "owner_resolution": "single_candidate",
        },
        steps=composed_plan() if steps is None else steps,
        available_columns=FIXTURE_COLUMNS if available_columns is None else available_columns,
    )
