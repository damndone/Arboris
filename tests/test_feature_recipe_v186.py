from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.artifacts import sha256_file, write_json
from workbench.data_operations import (
    DataTransformSpecV1,
    FeatureRecipeOperationSpecV1,
    apply_data_transform,
    apply_feature_recipe_operation,
    preview_data_transform,
    preview_feature_recipe,
)
from workbench.graph_model import BranchRef, Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.predictive_research.contracts import FeatureRecipeV1


def _recipe(operation_id: str, *, inputs: tuple[str, ...], output: str, parameters: dict) -> FeatureRecipeV1:
    return FeatureRecipeV1(
        recipe_id=f"recipe_{operation_id}",
        operation_id=operation_id,
        operation_version=1,
        inputs=inputs,
        outputs=(output,),
        output_types=("numeric",),
        parameters=parameters,
        fit_scope="stateless",
        source_artifact="source_data",
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
        recipe=_recipe("interaction", inputs=("x", "z"), output="xz", parameters={"left": "x", "right": "z"}),
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
    graph = json.loads((project / "runs" / run_id / "graph.json").read_text())
    assert effect.child_node_id in graph["nodes"]
    assert graph["nodes"][effect.child_node_id]["annotations"][0]["operation_id"] == "interaction"
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
    tmp_path: Path, operation_id: str, inputs: tuple[str, ...], output: str, parameters: dict,
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
            recipe=_recipe(operation_id, inputs=inputs, output=output, parameters=parameters),
        ),
    )
    assert preview.status == "ready"


def test_feature_recipe_fail_closed_on_unmapped_recode(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"group": [1, 3]}))
    spec = FeatureRecipeOperationSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        recipe=_recipe("recode", inputs=("group",), output="label", parameters={"input": "group", "mapping": {1: "one"}}),
    )
    with pytest.raises(Exception):
        preview_feature_recipe(project, spec)


def test_data_transform_reshape_then_subset_is_persisted_and_traceable(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path, pd.DataFrame({"id": [1, 2], "score_a": [10.0, 20.0], "score_b": [11.0, 21.0]})
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


def test_merge_many_to_many_is_fail_closed_with_next_step(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"id": [1, 1], "left_value": [10, 11]}))
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
