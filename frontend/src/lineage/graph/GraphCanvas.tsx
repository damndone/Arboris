import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, { Background, Controls } from "reactflow";
import type { Node as RFNode, Edge as RFEdge } from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import "../tokens/lineage.css";
import { GraphNode } from "./GraphNode";
import { GraphTooltip } from "./GraphTooltip";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";
import { foldVariableClusters, type GroupNode } from "../folding";

// T8.4: 240ms hover delay before the tooltip mounts. Matches V1.4.1
// NodeTooltip and the prototype (uiux/graph.jsx L228).
export const TOOLTIP_HOVER_DELAY_MS = 240;

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

    // memberToGroup collapses each variable inside a folded cluster
    // to its group id so edge logic + tri-state highlighting can
    // address groups by their member ids interchangeably.
    const memberToGroup = new Map<string, string>();
    groups.forEach((g) =>
      g.member_ids.forEach((m) => memberToGroup.set(m, g.id)),
    );

    // T8.5: compute the "related" set for tri-state highlighting.
    //   inIds  = edge.source ∀ edges where edge.target === selectedNodeId
    //   outIds = edge.target ∀ edges where edge.source === selectedNodeId
    //   related = inIds ∪ outIds ∪ {selectedNodeId}
    // Edges run over model.edges (logical, pre-folding); memberToGroup
    // remaps endpoints so a selected group highlights via any of its
    // members' real edges.
    const related = new Set<string>();
    if (selectedNodeId !== null) {
      related.add(selectedNodeId);
      for (const e of model.edges) {
        const src = memberToGroup.get(e.source) ?? e.source;
        const tgt = memberToGroup.get(e.target) ?? e.target;
        if (tgt === selectedNodeId) related.add(src);
        if (src === selectedNodeId) related.add(tgt);
      }
    }
    const stateFor = (id: string): "selected" | "related" | "dim" => {
      if (selectedNodeId === null) return "related";
      if (id === selectedNodeId) return "selected";
      if (related.has(id)) return "related";
      return "dim";
    };

    const realNodes: RFNode[] = kept.map((n) => ({
      id: n.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      // T8.3: GraphNode now consumes the V1.5.0 GraphViewNode directly.
      // Adapter is the only consumer of backend LineageNode shape.
      // T8.5: also carries the tri-state highlight state.
      data: { node: n, state: stateFor(n.id) },
      selected: n.id === selectedNodeId,
    }));
    const groupNodes: RFNode[] = groups.map((g) => ({
      id: g.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: { node: groupAsNode(g), state: stateFor(g.id) },
      selected: false,
    }));
    const markerNodes: RFNode[] = expandedMarkers.map((m) => ({
      id: m.gid,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: {
        node: markerAsNode(m.gid, m.variantLabel, m.parent),
        state: stateFor(m.gid),
      },
      selected: false,
    }));

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

  // ── T8.4 hover tooltip ──────────────────────────────────────────
  // Tracks the candidate node under the cursor + screen-space coords.
  // After TOOLTIP_HOVER_DELAY_MS the candidate becomes the visible
  // hover state. Suppressed entirely when a node is selected (the
  // DetailDrawer takes over) and for synthetic group/marker pseudo-
  // nodes (no useful tooltip content). Portaled to document.body via
  // GraphTooltip so canvas zoom doesn't shift the pixel position.
  const [hover, setHover] = useState<{
    node: GraphViewNode;
    x: number;
    y: number;
  } | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
    },
    [],
  );

  const onNodeMouseEnter = useCallback(
    (event: React.MouseEvent, rfNode: RFNode) => {
      if (selectedNodeId !== null) return;
      if (rfNode.id.startsWith("group:")) return;
      const vm = nodeById.get(rfNode.id);
      if (!vm) return;
      const clientX = event.clientX;
      const clientY = event.clientY;
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
      hoverTimer.current = setTimeout(() => {
        setHover({ node: vm, x: clientX, y: clientY });
      }, TOOLTIP_HOVER_DELAY_MS);
    },
    [nodeById, selectedNodeId],
  );

  const onNodeMouseMove = useCallback(
    (event: React.MouseEvent) => {
      // Once visible, follow the cursor. Before visible, the pending
      // setTimeout already captured the original entry coords — that's
      // intentional; rapid swipes shouldn't continuously reset the
      // timer.
      setHover((h) =>
        h === null ? null : { ...h, x: event.clientX, y: event.clientY },
      );
    },
    [],
  );

  const onNodeMouseLeave = useCallback(() => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
    setHover(null);
  }, []);

  // Selection clears any in-flight hover (the drawer takes over).
  useEffect(() => {
    if (selectedNodeId !== null) {
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
      setHover(null);
    }
  }, [selectedNodeId]);

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
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseMove={onNodeMouseMove}
        onNodeMouseLeave={onNodeMouseLeave}
        fitView
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <GraphTooltip
        node={hover?.node ?? null}
        x={hover?.x ?? 0}
        y={hover?.y ?? 0}
      />
    </div>
  );
}
