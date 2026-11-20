"""network.centrality against the published Padgett Florentine marriage network (QRData 403)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.network_analysis import NetworkInputError, network_centrality

FAMILIES = ["ACCIAIUOL", "ALBIZZI", "BARBADORI", "BISCHERI", "CASTELLAN", "GINORI", "GUADAGNI", "LAMBERTES",
            "MEDICI", "PAZZI", "PERUZZI", "PUCCI", "RIDOLFI", "SALVIATI", "STROZZI", "TORNABUON"]
MARRIAGES = [("ACCIAIUOL", "MEDICI"), ("ALBIZZI", "GINORI"), ("ALBIZZI", "GUADAGNI"), ("ALBIZZI", "MEDICI"),
             ("BARBADORI", "CASTELLAN"), ("BARBADORI", "MEDICI"), ("BISCHERI", "GUADAGNI"), ("BISCHERI", "PERUZZI"),
             ("BISCHERI", "STROZZI"), ("CASTELLAN", "PERUZZI"), ("CASTELLAN", "STROZZI"), ("GUADAGNI", "LAMBERTES"),
             ("GUADAGNI", "TORNABUON"), ("MEDICI", "RIDOLFI"), ("MEDICI", "SALVIATI"), ("MEDICI", "TORNABUON"),
             ("PAZZI", "SALVIATI"), ("PERUZZI", "STROZZI"), ("RIDOLFI", "STROZZI"), ("RIDOLFI", "TORNABUON")]


def _matrix_frame() -> pd.DataFrame:
    ties = {frozenset(pair) for pair in MARRIAGES}
    rows = [{"FAMILY": left, **{right.lower(): int(frozenset((left, right)) in ties) for right in FAMILIES}}
            for left in FAMILIES]
    return pd.DataFrame(rows)


def _by_node(result):
    return {row["node"]: row for row in result["nodes"]}


def _matrix_options(**extra):
    return {"input_form": "adjacency_matrix", "matrix_columns": [name.lower() for name in FAMILIES],
            "label_column": "FAMILY", **extra}


def test_centralities_match_the_published_florentine_values():
    result = network_centrality(_matrix_frame(), _matrix_options())
    nodes = _by_node(result)
    assert (result["n_nodes"], result["n_ties"], result["connected_components"], result["isolated_nodes"]) == (
        16, 20, 2, ["PUCCI"])
    medici, guadagni = nodes["MEDICI"], nodes["GUADAGNI"]
    assert (medici["degree"], medici["betweenness"], medici["sum_of_distances"]) == (6, 47.5, 25.0)
    assert guadagni["closeness"] == pytest.approx(1 / 30)
    assert guadagni["closeness_normalized"] == pytest.approx(14 / 30)
    assert guadagni["closeness_unreachable_at_n"] == pytest.approx(1 / (30 + 16))
    assert "not connected" in result["closeness_note"]
    assert guadagni["betweenness"] == pytest.approx(23.1666667)
    assert medici["eigenvector"] == 1.0
    assert nodes["PUCCI"]["closeness"] is None and nodes["PUCCI"]["eigenvector"] == 0.0


def test_an_edge_list_gives_the_same_centralities_as_its_matrix():
    edges = pd.DataFrame(MARRIAGES, columns=["from", "to"])
    from_edges = _by_node(network_centrality(edges, {"input_form": "edge_list", "source_column": "from",
                                                     "target_column": "to"}))
    from_matrix = _by_node(network_centrality(_matrix_frame(), _matrix_options()))
    for name, row in from_edges.items():
        assert row["betweenness"] == pytest.approx(from_matrix[name]["betweenness"])
        assert row["degree"] == from_matrix[name]["degree"]
    assert "PUCCI" not in from_edges
    assert all(row["closeness_unreachable_at_n"] == row["closeness"] for row in from_edges.values())


def test_directed_ties_count_out_paths_and_in_and_out_degree():
    edges = pd.DataFrame({"from": ["a", "b"], "to": ["b", "c"]})
    nodes = _by_node(network_centrality(edges, {"input_form": "edge_list", "source_column": "from",
                                                "target_column": "to", "directed": True}))
    assert (nodes["a"]["out_degree"], nodes["a"]["in_degree"], nodes["a"]["sum_of_distances"]) == (1, 0, 3.0)
    assert nodes["b"]["betweenness"] == 1.0 and nodes["c"]["closeness"] is None
    assert "eigenvector" not in nodes["a"]


@pytest.mark.parametrize("change, message", [
    (lambda frame: frame.iloc[:-1], "an adjacency matrix is square"),
    (lambda frame: frame.assign(medici=2), "entries must be 0 or 1"),
    (lambda frame: frame.assign(acciaiuol=[1] + [0] * 15), "non-zero diagonal"),
])
def test_a_frame_that_is_not_a_binary_network_is_refused(change, message):
    with pytest.raises(NetworkInputError, match=message):
        network_centrality(change(_matrix_frame()), _matrix_options())


def test_an_asymmetric_matrix_must_be_declared_directed():
    frame = _matrix_frame()
    frame.loc[0, "albizzi"] = 1
    with pytest.raises(NetworkInputError, match="not symmetric; set directed true"):
        network_centrality(frame, _matrix_options())
    assert network_centrality(frame, _matrix_options(directed=True))["directed"] is True


def test_matrix_columns_out_of_row_order_are_refused():
    columns = [name.lower() for name in FAMILIES]
    with pytest.raises(NetworkInputError, match="not in the order of the rows"):
        network_centrality(_matrix_frame(), _matrix_options(matrix_columns=[columns[1], columns[0], *columns[2:]]))


def test_the_workflow_capability_reports_only_the_named_nodes_and_names_exact_spelling():
    from workbench.agent.workflow_capability_adapters import WorkflowCapabilityAdapterError
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("network.centrality")
    request = {"operation_id": "network.centrality", "input_mode": "frame",
               "column_bindings": {"matrix_columns": [name.lower() for name in FAMILIES], "label_column": "FAMILY"},
               "options": {"input_form": "adjacency_matrix", "nodes": ["GUADAGNI"]}}
    _, execution = operation.execute_with_context(_matrix_frame(), request)
    assert [row["node"] for row in execution.payload["result"]["nodes"]] == ["GUADAGNI"]
    with pytest.raises(WorkflowCapabilityAdapterError, match="'guadagni' is 'GUADAGNI'"):
        operation.execute_with_context(_matrix_frame(), {**request, "options": {**request["options"], "nodes": ["guadagni"]}})
    with pytest.raises(WorkflowCapabilityAdapterError, match="source_column and target_column belong to input_form edge_list"):
        operation.validate_request({**request, "column_bindings": {**request["column_bindings"], "source_column": "x"}})


def test_rows_in_time_order_can_be_numbered_and_used_as_the_time_of_a_granger_test(tmp_path: Path):
    """QRData 222 and 239: a series with no time column, its rows already in time order."""
    from tests.test_data_column_cast import _source_project
    from workbench.agent.workflow import compile_workflow
    from workbench.agent.workflow_runtime import build_workflow_step_executor

    frame = pd.DataFrame({"cloud": [float((index * 7) % 11) for index in range(40)],
                          "pressure": [float((index * 3) % 13) for index in range(40)]})
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="wf_row_order_time",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "sha256:fixture"},
        steps=[
            {"step_id": "order", "operation_id": "data.row_index", "spec": {"output": "period"}},
            {"step_id": "granger", "operation_id": "time_series.granger", "depends_on": ["order"], "spec": {
                "input_mode": "frame", "source": {"from_step": "order", "output": "produced_dataset"},
                "column_bindings": {"time": "period", "cause": "cloud", "effect": "pressure"},
                "options": {"time_order": "declared_monotonic", "max_lag": 2}}},
        ],
        available_columns=list(frame.columns),
    )
    executor = build_workflow_step_executor(project, draft)
    results = {}
    for step in draft.steps:
        results[step.step_id] = executor(step, results)
    granger = results["granger"].payload["result"]
    assert (granger["status"], granger["n_observations"]) == ("completed", 40)
    assert [lag["lag"] for lag in granger["result"]["lags"]] == [1, 2]
