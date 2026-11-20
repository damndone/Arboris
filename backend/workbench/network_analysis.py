"""Node centrality of one unweighted network (degree, closeness, betweenness, eigenvector).

The network comes from the frame in one of two forms:
- an adjacency matrix: the declared columns are the matrix, row i is node i and column i is the
  same node, so the matrix is square; ``label_column`` optionally names each row's node;
- an edge list: each row is one tie between ``source_column`` and ``target_column``.

Ties are present or absent (entries 0 or 1; a weighted network is refused rather than read as
binary). An undirected matrix must be symmetric. Self-ties are refused.

Definitions (shortest paths count ties; a node that cannot be reached is left out of the sums):
- degree: number of ties (directed: in and out separately);
- closeness: 1 / (sum of shortest-path lengths to every reachable other node) -- igraph's
  ``closeness()``; ``closeness_normalized`` multiplies it by the number of reachable other nodes
  (igraph ``normalized=TRUE``); ``closeness_wasserman_faust`` further scales by the reachable share
  of the network (networkx ``closeness_centrality``, which equals the normalized value when every
  node is reachable); ``closeness_unreachable_at_n`` counts each unreachable node at distance n, the
  number of nodes (igraph before 0.10, R igraph before 1.3); all four agree on a connected network;
- betweenness: Brandes' count of shortest paths through the node, unnormalized (igraph), halved
  for an undirected network; ``betweenness_normalized`` divides by the number of node pairs that
  exclude the node ((n-1)(n-2)/2 undirected, (n-1)(n-2) directed; networkx);
- eigenvector (undirected only): the leading eigenvector of the adjacency matrix, scaled so the
  largest entry is 1 (igraph ``scale=TRUE``).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import shortest_path

#: A dense n x n matrix and an O(n * ties) path count stay small up to here.
MAX_NODES = 5_000
#: A node outside the leading component has eigenvector centrality 0; eigh leaves about 1e-17 there.
ROUNDING_FLOOR = 1e-12


class NetworkInputError(ValueError):
    """The frame does not describe a network this operation can read."""


def _adjacency(frame: pd.DataFrame, columns: Sequence[str], label_column: str | None) -> tuple[list[str], np.ndarray]:
    if len(frame) != len(columns):
        raise NetworkInputError(
            f"an adjacency matrix is square: {len(columns)} matrix columns but {len(frame)} rows. "
            "List every matrix column, in the same order as the rows, and nothing else")
    try:
        matrix = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise NetworkInputError("adjacency matrix entries must be numbers 0 or 1") from exc
    if np.isnan(matrix).any():
        raise NetworkInputError("the adjacency matrix has missing entries; a tie is 1 and no tie is 0")
    if not np.isin(matrix, (0.0, 1.0)).all():
        shown = sorted({float(value) for value in np.unique(matrix) if value not in (0.0, 1.0)})[:5]
        raise NetworkInputError(
            f"adjacency entries must be 0 or 1; found {shown}. Weighted networks are not supported")
    if label_column is None:
        return [str(column) for column in columns], matrix
    labels = [str(value) for value in frame[label_column]]
    if len(set(labels)) != len(labels):
        raise NetworkInputError(f"{label_column} names a node twice")
    folded = [label.strip().casefold() for label in labels]
    names = [str(column).strip().casefold() for column in columns]
    if folded != names:
        if sorted(folded) == sorted(names):
            raise NetworkInputError(
                f"the matrix columns are not in the order of the rows named by {label_column}; "
                "list the columns in row order")
        raise NetworkInputError(
            f"the matrix column names do not match the node names in {label_column} (ignoring case); "
            "omit label_column to name the nodes by the matrix columns")
    return labels, matrix


def _edge_list(frame: pd.DataFrame, source: str, target: str, directed: bool) -> tuple[list[str], np.ndarray]:
    pairs = frame.loc[:, [source, target]]
    if pairs.isna().any().any():
        raise NetworkInputError("the edge list has rows with a missing source or target")
    ends = [(str(left), str(right)) for left, right in pairs.itertuples(index=False)]
    if any(left == right for left, right in ends):
        raise NetworkInputError("the edge list has a tie from a node to itself; self-ties are not supported")
    names = sorted({name for pair in ends for name in pair})
    index = {name: position for position, name in enumerate(names)}
    matrix = np.zeros((len(names), len(names)))
    for left, right in ends:
        matrix[index[left], index[right]] = 1.0
        if not directed:
            matrix[index[right], index[left]] = 1.0
    return names, matrix


def _betweenness(neighbours: list[np.ndarray]) -> np.ndarray:
    """Brandes (2001) for unweighted ties; ordered pairs, so an undirected caller halves it."""
    n = len(neighbours)
    score = np.zeros(n)
    for source in range(n):
        order, preceding = [], [[] for _ in range(n)]
        paths = np.zeros(n)
        paths[source] = 1.0
        distance = np.full(n, -1)
        distance[source] = 0
        queue = deque([source])
        while queue:
            node = queue.popleft()
            order.append(node)
            for other in neighbours[node]:
                if distance[other] < 0:
                    distance[other] = distance[node] + 1
                    queue.append(other)
                if distance[other] == distance[node] + 1:
                    paths[other] += paths[node]
                    preceding[other].append(node)
        dependency = np.zeros(n)
        for node in reversed(order):
            for before in preceding[node]:
                dependency[before] += paths[before] / paths[node] * (1.0 + dependency[node])
            if node != source:
                score[node] += dependency[node]
    return score


def _number(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def network_centrality(frame: pd.DataFrame, options: Mapping[str, Any]) -> dict[str, Any]:
    directed = bool(options.get("directed", False))
    form = options.get("input_form")
    if form == "adjacency_matrix":
        columns = list(options.get("matrix_columns") or [])
        if len(columns) < 2:
            raise NetworkInputError("an adjacency matrix needs at least two matrix columns")
        names, matrix = _adjacency(frame, columns, options.get("label_column"))
        if np.diag(matrix).any():
            raise NetworkInputError("the adjacency matrix has ties from a node to itself (non-zero diagonal); "
                                    "self-ties are not supported")
        if not directed and not np.array_equal(matrix, matrix.T):
            raise NetworkInputError("the adjacency matrix is not symmetric; set directed true for a directed network")
    elif form == "edge_list":
        names, matrix = _edge_list(frame, str(options.get("source_column")), str(options.get("target_column")), directed)
    else:
        raise NetworkInputError("input_form must be adjacency_matrix or edge_list")
    n = len(names)
    if n > MAX_NODES:
        raise NetworkInputError(f"the network has {n} nodes, above the limit of {MAX_NODES}")
    distances = shortest_path(matrix, method="D", directed=directed, unweighted=True)
    reachable = np.isfinite(distances) & ~np.eye(n, dtype=bool)
    farness = np.where(reachable, distances, 0.0).sum(axis=1)
    count = reachable.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        closeness = np.where(count > 0, 1.0 / farness, np.nan)
    betweenness = _betweenness([np.flatnonzero(row) for row in matrix])
    pairs = (n - 1) * (n - 2)
    if not directed:
        betweenness = betweenness / 2.0
        pairs = pairs / 2
    eigenvector = None
    if not directed:
        values, vectors = np.linalg.eigh(matrix)
        leading = vectors[:, int(np.argmax(values))]
        leading = leading if leading.sum() >= 0 else -leading
        eigenvector = leading / np.abs(leading).max() if np.abs(leading).max() > 0 else leading
        eigenvector = np.where(np.abs(eigenvector) < ROUNDING_FLOOR, 0.0, eigenvector)
    nodes = []
    for index, name in enumerate(names):
        row: dict[str, Any] = {"node": name}
        if directed:
            row["out_degree"] = int(matrix[index].sum())
            row["in_degree"] = int(matrix[:, index].sum())
        else:
            row["degree"] = int(matrix[index].sum())
        row.update({
            "reachable_nodes": int(count[index]),
            "sum_of_distances": _number(farness[index]) if count[index] else None,
            "closeness": _number(closeness[index]),
            "closeness_normalized": _number(closeness[index] * count[index]),
            "closeness_wasserman_faust": _number(closeness[index] * count[index] ** 2 / (n - 1)),
            "closeness_unreachable_at_n": _number(1.0 / (farness[index] + n * (n - 1 - count[index])))
            if farness[index] + n * (n - 1 - count[index]) > 0 else None,
            "betweenness": float(betweenness[index]),
            "betweenness_normalized": float(betweenness[index] / pairs) if pairs else None,
        })
        if eigenvector is not None:
            row["eigenvector"] = float(eigenvector[index])
        nodes.append(row)
    isolated = [name for name, reached in zip(names, count) if reached == 0]
    components = int(len({tuple(np.flatnonzero(np.isfinite(row))) for row in distances})) if not directed else None
    return {
        "nodes": nodes,
        "n_nodes": n,
        "n_ties": int(matrix.sum() if directed else matrix.sum() / 2),
        "directed": directed,
        "connected_components": components,
        "isolated_nodes": isolated,
        **({"closeness_note": "the network is not connected: closeness conventions differ on unreachable nodes; "
                              "the closeness fields give each, with its definition"} if components and components > 1 else {}),
        "definitions": {
            "closeness": "1 / sum of shortest-path lengths to the reachable other nodes (igraph closeness)",
            "closeness_normalized": "closeness x number of reachable other nodes (igraph normalized=TRUE)",
            "closeness_wasserman_faust": "normalized closeness x reachable share (networkx closeness_centrality)",
            "closeness_unreachable_at_n": "1 / sum of distances with each unreachable node at distance n "
                                          "(igraph before 0.10, R igraph before 1.3)",
            "betweenness": "shortest paths through the node, unnormalized" + (", undirected" if not directed else ""),
            "betweenness_normalized": "betweenness / pairs of other nodes (networkx normalized=True)",
            **({"eigenvector": "leading adjacency eigenvector, largest entry 1 (igraph scale=TRUE)"} if not directed else {}),
        },
    }
