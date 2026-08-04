"""v1.8.6 data-management operations and Graph-chain acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.artifacts import sha256_file, write_json
from workbench.app import app
from workbench.data_operations import (
    DataColumnCastValidationError,
    DataTransformSpecV1,
    FeatureRecipeOperationSpecV1,
    apply_data_transform,
    apply_feature_recipe_operation,
    preview_data_transform,
    preview_feature_recipe,
)
from workbench.graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from workbench.graph_store import GraphStore
from workbench.predictive_research.contracts import FeatureRecipeV1


def _recipe(run_id: str, artifact_id: str, operation_id: str, *, inputs: tuple[str, ...], output: str, parameters: dict) -> FeatureRecipeV1:
    return FeatureRecipeV1(
        recipe_id=f"recipe_{operation_id}",
        operation_id=operation_id,
        operation_version=1,
        inputs=inputs,
        outputs=(output,),
        output_types=("numeric",),
        parameters=parameters,
        fit_scope="stateless",
        source_artifact=artifact_id,
        lineage_parent="stage:source",
    )


def test_feature_recipe_preview_and_apply_persist_typed_child_and_graph_identity(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"x": [2.0, 3.0], "z": [4.0, 5.0], "denom": [2.0, 5.0], "group": [1, 2]}),
    )
    spec = FeatureRecipeOperationSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        recipe=_recipe(
            run_id,
            artifact_id,
            "interaction",
            inputs=("x", "z"),
            output="xz",
            parameters={"left": "x", "right": "z"},
        ),
    )

    preview = preview_feature_recipe(project, spec)
    assert preview.status == "ready"
    assert preview.output_columns == ("x", "z", "denom", "group", "xz")

    effect = apply_feature_recipe_operation(project, spec, preview)
    assert effect.child_node_id.startswith("feature-recipe:")
    assert effect.recipe_path.endswith("recipe.json")
    child = pd.read_csv(project / "runs" / run_id / effect.artifact_path)
    assert child["xz"].tolist() == [8.0, 15.0]
    recipe_payload = json.loads((project / "runs" / run_id / effect.recipe_path).read_text())
    assert recipe_payload["payload_schema"] == "workbench.prediction.feature-recipe"
    assert recipe_payload["operation_id"] == "interaction"
    graph = json.loads((project / "runs" / run_id / "graph.json").read_text())
    assert effect.child_node_id in graph["nodes"]
    assert graph["nodes"][effect.child_node_id]["annotations"][0]["operation_id"] == "interaction"
    assert graph["nodes"][effect.child_node_id]["node_hash"] == sha256_file(
        project / "runs" / run_id / effect.artifact_path
    )
    node_index = json.loads((project / "runs" / run_id / "node_index.json").read_text())
    assert node_index[effect.child_node_id]["node_hash"] == sha256_file(project / "runs" / run_id / effect.artifact_path)


@pytest.mark.parametrize(
    ("operation_id", "inputs", "output", "parameters"),
    [
        ("log", ("x",), "log_x", {"input": "x", "base": "e"}),
        ("ratio", ("x", "denom"), "ratio_x", {"numerator": "x", "denominator": "denom", "zero_policy": "fail_closed"}),
        ("recode", ("group",), "group_name", {"input": "group", "mapping": {1: "one", 2: "two"}}),
        ("derived_variable", ("x", "z"), "sum_xz", {"operator": "add"}),
    ],
)
def test_feature_recipe_all_registered_operations_are_previewable(
    tmp_path: Path,
    operation_id: str,
    inputs: tuple[str, ...],
    output: str,
    parameters: dict,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"x": [2.0, 3.0], "z": [4.0, 5.0], "denom": [2.0, 5.0], "group": [1, 2]}),
    )
    preview = preview_feature_recipe(
        project,
        FeatureRecipeOperationSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            recipe=_recipe(run_id, artifact_id, operation_id, inputs=inputs, output=output, parameters=parameters),
        ),
    )
    assert preview.status == "ready"


def test_feature_recipe_fail_closed_on_unmapped_recode(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"group": [1, 3]}))
    spec = FeatureRecipeOperationSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        recipe=_recipe(run_id, artifact_id, "recode", inputs=("group",), output="label", parameters={"input": "group", "mapping": {1: "one"}}),
    )
    with pytest.raises(Exception):
        preview_feature_recipe(project, spec)


def test_data_transform_reshape_then_subset_is_persisted_and_traceable(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "score_a": [10.0, 20.0], "score_b": [11.0, 21.0]}),
    )
    reshape = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="reshape",
        parameters={"direction": "wide_to_long", "id_columns": ["id"], "value_columns": ["score_a", "score_b"], "var_name": "metric", "value_name": "score"},
    )
    reshape_preview = preview_data_transform(project, reshape)
    assert reshape_preview.row_count_after == 4
    reshape_effect = apply_data_transform(project, reshape, reshape_preview)
    assert reshape_effect.child_node_id.startswith("data-reshape:")

    subset = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id=reshape_effect.child_node_id,
        source_artifact_id=reshape_effect.artifact_id,
        operation="subset",
        parameters={"columns": ["id", "metric", "score"], "equals": {"metric": "score_a"}},
    )
    subset_preview = preview_data_transform(project, subset)
    assert subset_preview.row_count_after == 2
    subset_effect = apply_data_transform(project, subset, subset_preview)
    assert Path(project / "runs" / run_id / subset_effect.recipe_path).is_file()
    graph = GraphStore(project / "runs").read(run_id)
    assert subset_effect.child_node_id in graph.nodes
    assert graph.nodes[subset_effect.child_node_id].payload_ref == subset_effect.artifact_path
    assert graph.nodes[subset_effect.child_node_id].node_hash == sha256_file(
        project / "runs" / run_id / subset_effect.artifact_path
    )


def test_merge_many_to_many_is_fail_closed_with_next_step(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 1], "left_value": [10, 11]}),
    )
    right_run = "run_right"
    right_root = project / "runs" / right_run
    right_root.mkdir()
    right_path = right_root / "data.csv"
    pd.DataFrame({"id": [1, 1], "right_value": [20, 21]}).to_csv(right_path, index=False)
    right_artifact = "right_data"
    write_json(right_root / "artifacts_index.json", {"schema_version": 1, "artifacts": [{"artifact_id": right_artifact, "path": "data.csv", "artifact_type": "raw_data", "step": "fixture", "sha256": sha256_file(right_path), "inputs": []}]})
    source_node = Node(id="stage:source", kind=NodeKind.DATASET_STAGE, display_label="Source", created_at="2026-07-15T00:00:00+00:00", parent_stage_id=None, branch_id="main", payload_ref="data.csv", summary="right", stage=Stage.SOURCE)
    GraphStore(project / "runs").write(Graph(schema_version=3, run_id=right_run, nodes={source_node.id: source_node}, edges={}, branches={"main": BranchRef("main", None, (source_node.id,))}))
    spec = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="merge",
        parameters={"keys": ["id"], "how": "left"},
        secondary_run_id=right_run,
        secondary_node_id="stage:source",
        secondary_artifact_id=right_artifact,
    )
    with pytest.raises(Exception, match="DATA_MERGE_MANY_TO_MANY_BLOCKED"):
        preview_data_transform(project, spec)


def test_merge_to_reshape_derive_subset_keeps_cross_run_graph_chain_traceable(tmp_path: Path) -> None:
    ids = list(range(1, 17))
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "id": ids,
                "score_a": [10.0 * value for value in ids],
                "score_b": [11.0 * value for value in ids],
                "weight": [2.0 if value % 2 else 3.0 for value in ids],
            }
        ),
    )
    right_run = "run_right"
    right_root = project / "runs" / right_run
    right_root.mkdir()
    right_path = right_root / "data.csv"
    pd.DataFrame({"id": ids, "group": ["control" if value % 2 else "treated" for value in ids]}).to_csv(right_path, index=False)
    right_artifact = "right_data"
    write_json(
        right_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": right_artifact,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(right_path),
                    "inputs": [],
                }
            ],
        },
    )
    right_node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Right source",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary="right source",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=right_run,
            nodes={right_node.id: right_node},
            edges={},
            branches={"main": BranchRef("main", None, (right_node.id,))},
        )
    )

    merge = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="merge",
        parameters={"keys": ["id"], "how": "left"},
        secondary_run_id=right_run,
        secondary_node_id="stage:source",
        secondary_artifact_id=right_artifact,
    )
    merge_effect = apply_data_transform(project, merge, preview_data_transform(project, merge))

    reshape = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id=merge_effect.child_node_id,
        source_artifact_id=merge_effect.artifact_id,
        operation="reshape",
        parameters={
            "direction": "wide_to_long",
            "id_columns": ["id", "group", "weight"],
            "value_columns": ["score_a", "score_b"],
            "var_name": "metric",
            "value_name": "score",
        },
    )
    reshape_effect = apply_data_transform(project, reshape, preview_data_transform(project, reshape))

    derive = FeatureRecipeOperationSpecV1(
        source_run_id=run_id,
        source_node_id=reshape_effect.child_node_id,
        source_artifact_id=reshape_effect.artifact_id,
        recipe=_recipe(
            run_id,
            reshape_effect.artifact_id,
            "interaction",
            inputs=("score", "weight"),
            output="weighted_score",
            parameters={"left": "score", "right": "weight"},
        ),
    )
    derive_effect = apply_feature_recipe_operation(project, derive, preview_feature_recipe(project, derive))

    subset = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id=derive_effect.child_node_id,
        source_artifact_id=derive_effect.artifact_id,
        operation="subset",
        parameters={
            "columns": ["id", "group", "metric", "weighted_score"],
            "equals": {"metric": "score_a"},
        },
    )
    subset_effect = apply_data_transform(project, subset, preview_data_transform(project, subset))

    graph = GraphStore(project / "runs").read(run_id)
    external_id = f"{right_run}:stage:source"
    assert external_id in graph.nodes
    assert graph.nodes[external_id].annotations[0]["external_run_id"] == right_run
    assert any(
        edge.source_id == external_id
        and edge.target_id == merge_effect.child_node_id
        and edge.params["role"] == "secondary_input"
        for edge in graph.edges.values()
    )
    chain = [merge_effect.child_node_id, reshape_effect.child_node_id, derive_effect.child_node_id, subset_effect.child_node_id]
    assert all(node_id in graph.nodes for node_id in chain)
    assert all(
        any(edge.source_id == source_id and edge.target_id == target_id for edge in graph.edges.values())
        for source_id, target_id in zip(chain, chain[1:])
    )
    subset_frame = pd.read_csv(project / "runs" / run_id / subset_effect.artifact_path)
    assert len(subset_frame) == len(ids)
    assert subset_frame["weighted_score"].head(2).tolist() == [20.0, 60.0]

    with TestClient(app) as client:
        model_response = client.post(
            "/data-operations/model-run",
            params={"project_root": str(project)},
            json={
                "source_run_id": run_id,
                "source_node_id": derive_effect.child_node_id,
                "source_artifact_id": derive_effect.artifact_id,
                "model_type": "ols",
                "y": "weighted_score",
                "x": ["weight"],
            },
        )
    assert model_response.status_code == 200, model_response.text
    model_run_id = model_response.json()["run_id"]
    model_manifest_path = project / "runs" / model_run_id / "run_manifest.json"
    for _ in range(400):
        if model_manifest_path.exists():
            model_manifest = json.loads(model_manifest_path.read_text())
            if model_manifest.get("status") in {"completed", "failed", "blocked", "partial"}:
                break
        import time

        time.sleep(0.05)
    assert model_manifest["status"] == "completed", model_manifest
    model_inputs = json.loads((project / "runs" / model_run_id / "run_inputs.json").read_text())
    assert model_inputs["from_node"] == derive_effect.child_node_id


def test_data_node_can_start_a_real_ols_run_with_cross_run_lineage(tmp_path: Path) -> None:
    """The visible data-operation chain must end in an executable model run."""
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "id": list(range(1, 49)),
                "score": [2.0 * index for index in range(1, 49)],
                "weight": [1.0 + float(index % 2) for index in range(1, 49)],
            }
        ),
    )
    spec = FeatureRecipeOperationSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        recipe=_recipe(
            run_id,
            artifact_id,
            "interaction",
            inputs=("score", "weight"),
            output="weighted_score",
            parameters={"left": "score", "right": "weight"},
        ),
    )
    effect = apply_feature_recipe_operation(project, spec, preview_feature_recipe(project, spec))

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/model-run",
            params={"project_root": str(project)},
            json={
                "source_run_id": run_id,
                "source_node_id": effect.child_node_id,
                "source_artifact_id": effect.artifact_id,
                "model_type": "ols",
                "y": "weighted_score",
                "x": ["id"],
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "running"
    child_run_id = payload["run_id"]
    child_inputs = json.loads((project / "runs" / child_run_id / "run_inputs.json").read_text())
    assert child_inputs["rerun_of"] == run_id
    assert child_inputs["from_node"] == effect.child_node_id
    assert child_inputs["source_lineage"]["rerun_from"]["source_artifact_id"] == effect.artifact_id

    manifest_path = project / "runs" / child_run_id / "run_manifest.json"
    for _ in range(400):
        if not manifest_path.exists():
            import time

            time.sleep(0.05)
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("status") in {"completed", "failed", "blocked", "partial"}:
            break
        import time

        time.sleep(0.05)
    assert manifest["status"] == "completed", manifest
    graph = GraphStore(project / "runs").read(child_run_id)
    assert any(node.kind == NodeKind.MODEL for node in graph.nodes.values())


def test_append_rejects_incompatible_schema_under_explicit_policy(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )
    right_run = "run_append_right"
    right_root = project / "runs" / right_run
    right_root.mkdir()
    right_path = right_root / "data.csv"
    pd.DataFrame({"id": [3], "other": [30]}).to_csv(right_path, index=False)
    right_artifact = "append_right_data"
    write_json(
        right_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": right_artifact,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(right_path),
                    "inputs": [],
                }
            ],
        },
    )
    right_node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Append right source",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary="append right source",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=right_run,
            nodes={right_node.id: right_node},
            edges={},
            branches={"main": BranchRef("main", None, (right_node.id,))},
        )
    )

    spec = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="append",
        parameters={
            "schema_policy": "exact",
            "row_growth_policy": {"max_rows": 10},
        },
        secondary_run_id=right_run,
        secondary_node_id="stage:source",
        secondary_artifact_id=right_artifact,
    )
    with pytest.raises(DataColumnCastValidationError, match="DATA_APPEND_SCHEMA_INCOMPATIBLE"):
        preview_data_transform(project, spec)


def test_append_rejects_row_growth_under_explicit_policy(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )
    right_run = "run_append_growth_right"
    right_root = project / "runs" / right_run
    right_root.mkdir()
    right_path = right_root / "data.csv"
    pd.DataFrame({"id": [3, 4, 5], "value": [30, 40, 50]}).to_csv(right_path, index=False)
    right_artifact = "append_growth_right_data"
    write_json(
        right_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": right_artifact,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(right_path),
                    "inputs": [],
                }
            ],
        },
    )
    right_node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Append growth right source",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary="append growth right source",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=right_run,
            nodes={right_node.id: right_node},
            edges={},
            branches={"main": BranchRef("main", None, (right_node.id,))},
        )
    )

    spec = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="append",
        parameters={
            "schema_policy": "exact",
            "row_growth_policy": {"max_rows": 4},
        },
        secondary_run_id=right_run,
        secondary_node_id="stage:source",
        secondary_artifact_id=right_artifact,
    )
    with pytest.raises(DataColumnCastValidationError, match="DATA_APPEND_ROW_GROWTH_BLOCKED"):
        preview_data_transform(project, spec)


def test_merge_enforces_nested_growth_policy_after_how_is_selected(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )
    right_run = "run_merge_growth_right"
    right_root = project / "runs" / right_run
    right_root.mkdir()
    right_path = right_root / "data.csv"
    pd.DataFrame({"id": [2, 3], "extra": [30, 40]}).to_csv(right_path, index=False)
    right_artifact = "merge_growth_right_data"
    write_json(
        right_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": right_artifact,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(right_path),
                    "inputs": [],
                }
            ],
        },
    )
    right_node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Merge growth right source",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary="merge growth right source",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=right_run,
            nodes={right_node.id: right_node},
            edges={},
            branches={"main": BranchRef("main", None, (right_node.id,))},
        )
    )

    spec = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="merge",
        parameters={
            "keys": ["id"],
            "how": "inner",
            "growth_policy": {"max_rows": 0},
        },
        secondary_run_id=right_run,
        secondary_node_id="stage:source",
        secondary_artifact_id=right_artifact,
    )
    with pytest.raises(DataColumnCastValidationError, match="DATA_MERGE_ROW_EXPANSION_BLOCKED"):
        preview_data_transform(project, spec)


def test_merge_rejects_non_scalar_how_with_stable_validation_error(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1], "value": [10]}),
    )
    right_run = "run_merge_invalid_how"
    right_root = project / "runs" / right_run
    right_root.mkdir()
    right_path = right_root / "data.csv"
    pd.DataFrame({"id": [1], "extra": [20]}).to_csv(right_path, index=False)
    right_artifact = "merge_invalid_how_data"
    write_json(
        right_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": right_artifact,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(right_path),
                    "inputs": [],
                }
            ],
        },
    )
    right_node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Invalid how source",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary="invalid how source",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=right_run,
            nodes={right_node.id: right_node},
            edges={},
            branches={"main": BranchRef("main", None, (right_node.id,))},
        )
    )
    spec = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="merge",
        parameters={
            "keys": ["id"],
            "how": ["inner"],
            "growth_policy": {"max_rows": 10},
        },
        secondary_run_id=right_run,
        secondary_node_id="stage:source",
        secondary_artifact_id=right_artifact,
    )
    with pytest.raises(DataColumnCastValidationError, match="merge how must be"):
        preview_data_transform(project, spec)


def test_reshape_long_to_wide_and_subset_row_range_are_explicit_and_stable(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "id": [1, 1, 2, 2],
                "metric": ["score", "cost", "score", "cost"],
                "value": [10.0, 4.0, 20.0, 5.0],
            }
        ),
    )
    reshape = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="reshape",
        parameters={
            "direction": "long_to_wide",
            "index": ["id"],
            "columns": "metric",
            "values": "value",
        },
    )
    reshape_preview = preview_data_transform(project, reshape)
    assert reshape_preview.row_count_after == 2
    assert reshape_preview.output_columns == ("id", "cost", "score")

    subset = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="subset",
        parameters={
            "columns": ["id", "metric", "value"],
            "row_index_range": {"start": 1, "stop": 3},
        },
    )
    subset_preview = preview_data_transform(project, subset)
    assert subset_preview.row_count_after == 2


@pytest.mark.parametrize("row_indices", [[-1], [99], [0, 0]])
def test_subset_rejects_invalid_row_indices_with_stable_error(
    tmp_path: Path,
    row_indices: list[int],
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )
    spec = DataTransformSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        operation="subset",
        parameters={"columns": ["id", "value"], "row_indices": row_indices},
    )
    with pytest.raises(DataColumnCastValidationError, match="DATA_SUBSET_ROW_INDEX_INVALID"):
        preview_data_transform(project, spec)
