"""network.centrality as a workflow capability: request schema, validation and execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from ..network_analysis import NetworkInputError, network_centrality

INPUT_FORMS = ("adjacency_matrix", "edge_list")

_STRING = {"type": "string", "minLength": 1}

REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["operation_id", "input_mode", "column_bindings", "options"],
    "properties": {
        "operation_id": {"type": "string", "minLength": 1},
        "input_mode": {"const": "frame"},
        "column_bindings": {
            "type": "object",
            "properties": {
                "matrix_columns": {"type": "array", "items": _STRING, "minItems": 2},
                "label_column": _STRING,
                "source_column": _STRING,
                "target_column": _STRING,
            },
            "required": [],
            "additionalProperties": False,
        },
        "options": {
            "type": "object",
            "properties": {
                "input_form": {"type": "string", "enum": list(INPUT_FORMS)},
                "directed": {"type": "boolean"},
                "nodes": {"type": "array", "items": _STRING, "minItems": 1},
            },
            "required": ["input_form"],
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

SUMMARY = (
    "Node centrality of one unweighted network: degree, closeness (1 / sum of shortest-path lengths, "
    "plus normalized forms), betweenness and, undirected, eigenvector. Input is an adjacency matrix "
    "(column_bindings.matrix_columns in row order, optional label_column naming each row's node) or an "
    "edge list (source_column, target_column); options.input_form says which, options.nodes limits the "
    "reported nodes."
)


def validate_network_request(operation_id: str, request: Mapping[str, Any], common: Any, error: type[Exception]) -> dict[str, Any]:
    normalized = common(operation_id, request)
    bindings, options = normalized["column_bindings"], normalized["options"]
    unknown = sorted(set(bindings) - set(REQUEST_SCHEMA["properties"]["column_bindings"]["properties"]))
    unknown += sorted(set(options) - set(REQUEST_SCHEMA["properties"]["options"]["properties"]))
    if unknown:
        raise error(f"{operation_id} has unsupported field(s): {', '.join(unknown)}")
    form = options.get("input_form")
    if form == "adjacency_matrix":
        columns = bindings.get("matrix_columns")
        if not isinstance(columns, list) or len(columns) < 2 or any(type(item) is not str or not item for item in columns):
            raise error(f"{operation_id} adjacency_matrix needs column_bindings.matrix_columns: every matrix column, in row order")
        if len(set(columns)) != len(columns):
            raise error(f"{operation_id} matrix_columns lists a column twice")
        if {"source_column", "target_column"} & set(bindings):
            raise error(f"{operation_id} source_column and target_column belong to input_form edge_list")
    elif form == "edge_list":
        if any(type(bindings.get(key)) is not str or not bindings.get(key) for key in ("source_column", "target_column")):
            raise error(f"{operation_id} edge_list needs column_bindings.source_column and target_column")
        if {"matrix_columns", "label_column"} & set(bindings):
            raise error(f"{operation_id} matrix_columns and label_column belong to input_form adjacency_matrix")
    else:
        raise error(f"{operation_id} options.input_form must be one of: {', '.join(INPUT_FORMS)}")
    if "directed" in options and type(options["directed"]) is not bool:
        raise error(f"{operation_id} options.directed must be true or false")
    nodes = options.get("nodes")
    if nodes is not None and (not isinstance(nodes, list) or not nodes or any(type(item) is not str or not item for item in nodes)):
        raise error(f"{operation_id} options.nodes must be a non-empty list of node names")
    return normalized


def _columns(request: Mapping[str, Any]) -> list[str]:
    bindings = request["column_bindings"]
    if request["options"]["input_form"] == "adjacency_matrix":
        return [*bindings["matrix_columns"], *([bindings["label_column"]] if bindings.get("label_column") else [])]
    return [bindings["source_column"], bindings["target_column"]]


def execute_network_request(frame: pd.DataFrame, request: Mapping[str, Any], error: type[Exception]) -> dict[str, Any]:
    operation_id = str(request["operation_id"])
    bindings, options = request["column_bindings"], request["options"]
    missing = [column for column in _columns(request) if column not in frame.columns]
    if missing:
        raise error(f"{operation_id} references missing column(s): {', '.join(missing)}")
    try:
        result = network_centrality(frame.loc[:, _columns(request)], {**options, **bindings})
    except NetworkInputError as exc:
        raise error(f"{operation_id}: {exc}") from exc
    wanted = options.get("nodes")
    if wanted:
        names = [row["node"] for row in result["nodes"]]
        unknown = [name for name in wanted if name not in names]
        if unknown:
            close = {name: [other for other in names if other.casefold() == name.casefold()] for name in unknown}
            hints = "; ".join(f"{name!r} is {close[name][0]!r}" for name in unknown if close[name])
            raise error(f"{operation_id} options.nodes names no node: {', '.join(map(repr, unknown))}."
                        + (f" Node names are exact: {hints}." if hints else f" Nodes include: {', '.join(names[:20])}."))
        result["nodes"] = [row for row in result["nodes"] if row["node"] in wanted]
    return {
        "operation_id": operation_id,
        "status": "completed",
        "result": result,
        "assumptions": [
            "Ties are unweighted: an entry is 1 for a tie and 0 for none.",
            "Shortest paths count ties; nodes that cannot be reached are left out of a node's closeness sum.",
            "Undirected networks treat each tie as running both ways; betweenness counts each pair once.",
        ],
    }
