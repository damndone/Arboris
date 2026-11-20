"""A model node's schema is the schema of the one dataset stage that feeds it."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from tests.test_agent_data_cast_proposal import _seed_node_index
from tests.test_data_column_cast import _source_project
from workbench.agent.context_tools import InspectDataSchemaRequest, NodeOperationContextProvider
from workbench.graph_model import Edge, NodeKind, Stage
from workbench.graph_store import GraphStore


def _with_model(project, run_id):
    store = GraphStore(project / "runs")
    graph = store.read(run_id)
    source = graph.nodes["stage:source"]
    model = replace(source, id="model:ols_1", kind=NodeKind.MODEL, display_label="OLS", payload_ref=None,
                    stage=Stage.MODEL)
    edge = Edge(id="e:source-model", source_id=source.id, target_id=model.id, op="ols.fit")
    store.write(replace(graph, nodes={**graph.nodes, model.id: model}, edges={**graph.edges, edge.id: edge}))


def test_asking_the_imported_model_node_for_its_schema_reads_its_data(tmp_path):
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"owns_home": [0, 1], "income_k": [41.5, 63.2]}))
    _with_model(project, run_id)
    _seed_node_index(project, run_id, node_id="model:ols_1")
    result = NodeOperationContextProvider(project).inspect_data_schema(InspectDataSchemaRequest(
        request_id="r1", owner_run_id=run_id, op_node_id="model:ols_1", active_head_run_id=run_id))
    schema = result["data_schema"]
    assert schema["available"] is True and schema["dataset_node_id"] == "stage:source"
    assert {column["name"] for column in schema["columns"]} == {"owns_home", "income_k"}
    assert artifact_id not in str(result)
