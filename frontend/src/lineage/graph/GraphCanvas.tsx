import { useMemo } from "react";
import ReactFlow, { Background, Controls } from "reactflow";
import type { Node as RFNode, Edge as RFEdge } from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import "../tokens/lineage.css";
import { GraphNode } from "./GraphNode";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";
import { foldVariableClusters, type GroupNode } from "../folding";

const nodeTypes = { lineageNode: GraphNode };

interface GraphCanvasProps {
  model: GraphViewModel;
  selectedNodeId: string | null;
  expandedGroups: Set<string>;
  onSelect: (nodeId: string) => void;
  onExpandGroup: (groupId: string) => void;
}

function layoutDagre<T extends RFNode>(nodes: T[], edges: RFEdge[]): T[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 60 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: 240, height: 80 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 120, y: pos.y - 40 } };
  });
}

/**
 * Synthesize a GraphViewNode for a folded group pseudo-node. Stage is
 * "unknown" → neutral grey bar. Trust is "ok" → no badge.
 */
function groupAsNode(g: GroupNode): GraphViewNode {
  return {
    id: g.id,
    nodeKey: g.id,
    raw: null,
    stage: "unknown",
    kind: "operation",
    title: g.display_label,
    summary: "Tap to expand",
    parentStageId: g.parentStageId,
    trust: "ok",
    decisions: [],
  };
}

/**
 * Parse a synthesized fold-marker group id back into (variant, parentStageId).
 * Group ids have shape `group:variables:<parent>` or `group:dropped-variables:<parent>`.
 */
function parseGroupId(
  gid: string,
): { variantLabel: string; parent: string } | null {
  const m = gid.match(/^group:(variables|dropped-variables):(.+)$/);
  if (!m) return null;
  return {
    variantLabel: m[1] === "variables" ? "Variables" : "Dropped variables",
    parent: m[2],
  };
}

function markerAsNode(
  gid: string,
  variantLabel: string,
  parent: string,
): GraphViewNode {
  return {
    id: gid,
    nodeKey: gid,
    raw: null,
    stage: "unknown",
    kind: "operation",
    title: `▼ ${variantLabel} (expanded)`,
    summary: "Tap to fold back",
    parentStageId: parent,
    trust: "ok",
    decisions: [],
  };
}

export function GraphCanvas({
  model,
  selectedNodeId,
  expandedGroups,
  onSelect,
  onExpandGroup,
}: GraphCanvasProps) {
  // Hoisted out of the main useMemo so a selection-only re-render (which
  // bumps selectedNodeId but not model) doesn't pay an O(n) Map rebuild.
  // [REV-3 #6 — Step 5 adversarial review]
  const nodeById = useMemo(
    () => new Map(model.nodes.map((n) => [n.id, n])),
    [model.nodes],
  );

  const { rfNodes, rfEdges } = useMemo(() => {
    const { kept, groups } = foldVariableClusters(model.nodes, expandedGroups);

    const visible = new Set<string>(kept.map((n) => n.id));
    groups.forEach((g) => visible.add(g.id));

    // For each currently-expanded group id that folding.ts no longer returns
    // (because its members are inlined), synthesize a fold-back marker node so
    // the user has an affordance to collapse the cluster again. The marker
    // shares the group id, so onExpandGroup's toggle naturally folds it.
    const expandedMarkers: Array<{
      gid: string;
      variantLabel: string;
      parent: string;
    }> = [];
    const stillFolded = new Set(groups.map((g) => g.id));
    for (const gid of expandedGroups) {
      if (stillFolded.has(gid)) continue;
      const parsed = parseGroupId(gid);
      if (!parsed) continue;
      // Only show the marker if the parent stage is itself rendered; otherwise
      // dagre has nowhere to anchor it.
      if (!nodeById.has(parsed.parent)) continue;
      expandedMarkers.push({ gid, ...parsed });
      visible.add(gid);
    }

    const realNodes: RFNode[] = kept.map((n) => ({
      id: n.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      // T8.3: GraphNode now consumes the V1.5.0 GraphViewNode directly.
      // Adapter is the only consumer of backend LineageNode shape.
      data: { node: n },
      selected: n.id === selectedNodeId,
    }));
    const groupNodes: RFNode[] = groups.map((g) => ({
      id: g.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: { node: groupAsNode(g) },
      selected: false,
    }));
    const markerNodes: RFNode[] = expandedMarkers.map((m) => ({
      id: m.gid,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: { node: markerAsNode(m.gid, m.variantLabel, m.parent) },
      selected: false,
    }));

    const memberToGroup = new Map<string, string>();
    groups.forEach((g) =>
      g.member_ids.forEach((m) => memberToGroup.set(m, g.id)),
    );

    const candidateEdges: RFEdge[] = [];

    // Synthetic dashed edges from each expanded group's parent stage to its
    // fold-marker, so dagre places markers next to their siblings rather than
    // floating in a void.
    for (const m of expandedMarkers) {
      candidateEdges.push({
        id: `${m.parent}->${m.gid}`,
        source: m.parent,
        target: m.gid,
        animated: false,
        style: { strokeDasharray: "4 4", opacity: 0.4 },
      });
    }
    for (const e of model.edges) {
      const src = memberToGroup.get(e.source) ?? e.source;
      const tgt = memberToGroup.get(e.target) ?? e.target;
      if (src === tgt) continue;
      if (!visible.has(src) || !visible.has(tgt)) continue;
      candidateEdges.push({
        id: `${src}->${tgt}`,
        source: src,
        target: tgt,
        animated: false,
      });
    }
    const seen = new Set<string>();
    const uniqEdges = candidateEdges.filter((e) => {
      const key = `${e.source}|${e.target}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    const layouted = layoutDagre(
      [...realNodes, ...groupNodes, ...markerNodes],
      uniqEdges,
    );
    return { rfNodes: layouted, rfEdges: uniqEdges };
  }, [model, selectedNodeId, expandedGroups, nodeById]);

  return (
    <div
      className="lineage-root"
      style={{ width: "100%", height: "100%", minHeight: 480 }}
    >
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        onNodeClick={(_, n) => {
          if (n.id.startsWith("group:")) onExpandGroup(n.id);
          else onSelect(n.id);
        }}
        fitView
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
