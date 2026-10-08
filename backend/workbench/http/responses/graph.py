"""The lineage graph: per-run graph, family head-set and project forest.

Nodes, edges and branches are derived from the graph dataclasses in
``workbench.graph_model`` (their JSON form is their fields); routes add
response-time fields on top.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from ...graph_model import BranchRef, Edge, Node
from ...lineage.compare_nodes import CompareNodeRecord
from ...lineage.node_index import CasRef
from ...lineage.rerun_provenance import RunRerunFrom
from .common import view_of
from .system import EditableControlSpec

class NodeArtifact(TypedDict):
    """A serve-time preview of a dataset node's artifact (profile, cleaning
    actions, confirmed explorations) for Ask AI and the fact table."""

    name: str
    mime: str
    artifact_id: NotRequired[str]
    sha256: NotRequired[str | None]
    summary: NotRequired[dict[str, Any]]
    preview: NotRequired[Any]


GraphNodeView = view_of(
    Node,
    "GraphNodeView",
    # Editable operation nodes (response-time decoration, never persisted).
    editable=NotRequired[bool],
    op_type=NotRequired[str],
    schema_id=NotRequired[str],
    editable_schema=NotRequired[list[EditableControlSpec]],
    editable_schema_source=NotRequired[Literal["run_inputs", "capabilities"]],
    # Dataset and model decorations (serve-time previews for Ask AI and facts).
    artifacts=NotRequired[list[NodeArtifact]],
    stats=NotRequired[dict[str, Any]],
)


class ForestNodeView(GraphNodeView):  # type: ignore[valid-type,misc]
    """A head-set or forest node: one per content key across the runs that share it."""

    producing_stage: str | None
    cas_ref: CasRef | None
    runs: list[str]
    presentation_created_at: str
    produced_by_rerun_request_id: NotRequired[str]
    # Node-level provenance: the source this node was rerun from, or, when
    # runs sharing the node disagree, every record (and no source).
    rerun_from: NotRequired[RunRerunFrom]
    rerun_from_conflicts: NotRequired[list[RunRerunFrom]]
GraphEdgeView = view_of(Edge, "GraphEdgeView")
GraphBranchView = view_of(BranchRef, "GraphBranchView")


class GraphStats(TypedDict):
    node_count: int
    edge_count: int
    leaf_count: int
    has_dp_count: int


class RunGraph(TypedDict):
    schema_version: int
    run_id: str
    nodes: dict[str, GraphNodeView]
    edges: dict[str, GraphEdgeView]
    branches: dict[str, GraphBranchView]
    legacy: bool
    stats: GraphStats


class ForestEdge(TypedDict):
    source: str
    target: str
    op: str | None
    params: dict[str, Any] | None


class ForestHead(TypedDict):
    run_id: str
    head_node_hash: str | None
    from_node: str | None
    rerun_of: str | None
    rerun_from: RunRerunFrom | None
    rerun_reason: str | None
    status: str | None
    created_at: str | None


class ForestFamily(TypedDict):
    family_root: str
    members: list[str]


class ForestGraph(TypedDict):
    """A family head-set (``view=headset``) or the whole project forest
    (``GET /graph``, which adds ``families``)."""

    schema_version: int
    nodes: dict[str, ForestNodeView]
    edges: list[ForestEdge]
    heads: list[ForestHead]
    families: NotRequired[list[ForestFamily]]
    legacy: bool


CompareNodeView = view_of(CompareNodeRecord, "CompareNodeView")


class CompareNodeList(TypedDict):
    compare_nodes: list[CompareNodeView]


class CompareNodeDeleted(TypedDict):
    deleted: str
