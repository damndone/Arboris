"""The dataset nodes a node reads, from the run's lineage edges."""

from __future__ import annotations

from pathlib import Path

from ..graph_model import NodeKind
from ..graph_store import GraphStore


def input_datasets(project_root: Path | str, run_id: str, node_id: str) -> tuple[NodeKind, list[str], list[str]] | None:
    """``(kind, inputs, datasets)``: the node's kind, the dataset nodes with an edge into it, and every dataset node.

    ``None`` when the run has no readable graph or the node is not in it.
    """

    try:
        graph = GraphStore(Path(project_root) / "runs").read(run_id)
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError):
        return None
    if node_id not in graph.nodes:
        return None
    datasets = sorted(key for key, node in graph.nodes.items() if node.kind == NodeKind.DATASET_STAGE)
    inputs = sorted({edge.source_id for edge in graph.edges.values()
                     if edge.target_id == node_id and edge.source_id in datasets})
    return graph.nodes[node_id].kind, inputs, datasets
