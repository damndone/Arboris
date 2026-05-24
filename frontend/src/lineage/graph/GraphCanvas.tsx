import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Panel,
  useReactFlow,
} from "reactflow";
import type { Node as RFNode, Edge as RFEdge } from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import "../tokens/lineage.css";
import { GraphNode } from "./GraphNode";
import { GraphTooltip } from "./GraphTooltip";
import type {
  GraphViewModel,
  GraphViewNode,
  Stage,
} from "../api/graphViewTypes";
import { foldVariableClusters, type GroupNode } from "../folding";

// T8.4: 240ms hover delay before the tooltip mounts. Matches V1.4.1
// NodeTooltip and the prototype (uiux/graph.jsx L228).
export const TOOLTIP_HOVER_DELAY_MS = 240;

// T8.6a: stage labels from uiux/panels.jsx::stageLabel (L301-304). All
// 8 V1.5.0 stages have an entry. Synthetic "unknown" doesn't appear in
// the legend by design.
const STAGE_LABEL: Record<Exclude<Stage, "unknown">, string> = {
  source: "原始",
  eda: "探索",
  clean: "清洗",
  transform: "变换",
  model: "模型",
  diag: "诊断",
  viz: "可视化",
  report: "报告",
};
const LEGEND_STAGES: Array<Exclude<Stage, "unknown">> = [
  "source",
  "eda",
  "clean",
  "transform",
  "model",
  "diag",
  "viz",
  "report",
];

// Count of decisions across the whole view model whose reviewStatus
// is "needed" or "failed". Used by the canvas status badge (T8.6a).
// Iterates model.nodes — never affected by folding or viewport.
export function waitingReviewsCount(model: GraphViewModel): number {
  let n = 0;
  for (const node of model.nodes) {
    for (const d of node.decisions) {
      if (d.reviewStatus === "needed" || d.reviewStatus === "failed") n += 1;
    }
  }
  return n;
}

interface CanvasToolbarProps {
  containerRef: React.RefObject<HTMLDivElement>;
}

function CanvasToolbar({ containerRef }: CanvasToolbarProps) {
  const { fitView } = useReactFlow();
  const onFit = () => fitView({ padding: 0.2, duration: 200 });
  const onFullscreen = async () => {
    const el = containerRef.current;
    if (!el) return;
    // Fullscreen API may be unsupported (older browsers, embedded
    // contexts) or rejected (user gesture missing, security policy).
    // Both branches degrade gracefully — no banner, no throw.
    //
    // Target is the lineage-root container. If a future host layout
    // ever wraps GraphCanvas with siblings the user expects to keep
    // visible (e.g. a header bar) we'd hoist the ref upward; for
    // V1.5.0 the lineage view IS the page content so this is fine.
    if (!document.fullscreenEnabled) return;
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await el.requestFullscreen();
      }
    } catch {
      /* user rejected or feature blocked — silent no-op */
    }
  };
  return (
    <Panel position="top-left">
      <div className="ln-canvas-toolbar" data-testid="canvas-toolbar">
        {/* "Auto layout" is currently the only layout mode (dagre runs
         * unconditionally). Render as a disabled pressed indicator
         * rather than a clickable no-op so the affordance honestly
         * reflects current capability. */}
        <button
          type="button"
          disabled
          aria-pressed="true"
          data-testid="toolbar-auto-layout"
          title="Auto layout (always on)"
        >
          Auto
        </button>
        <button
          type="button"
          onClick={onFit}
          data-testid="toolbar-fit"
          title="Fit to screen"
        >
          Fit
        </button>
        <button
          type="button"
          onClick={onFullscreen}
          data-testid="toolbar-fullscreen"
          title="Toggle fullscreen"
        >
          Fullscreen
        </button>
      </div>
    </Panel>
  );
}

function CanvasStatus({ model }: { model: GraphViewModel }) {
  const waiting = waitingReviewsCount(model);
  return (
    <Panel position="top-right">
      <div className="ln-canvas-status" data-testid="canvas-status">
        run_{model.runId} ·{" "}
        <span
          className={
            waiting > 0
              ? "ln-canvas-status__count ln-canvas-status__count--warn"
              : "ln-canvas-status__count"
          }
          data-testid="canvas-status-count"
        >
          waiting {waiting} {waiting === 1 ? "review" : "reviews"}
        </span>
      </div>
    </Panel>
  );
}

function CanvasLegend() {
  const [expanded, setExpanded] = useState(false);
  return (
    <Panel position="bottom-right">
      <div
        className={`ln-canvas-legend${expanded ? " ln-canvas-legend--expanded" : ""}`}
        data-testid="canvas-legend"
        onMouseEnter={() => setExpanded(true)}
        onMouseLeave={() => setExpanded(false)}
      >
        <div className="ln-canvas-legend__chip">Stages</div>
        <div className="ln-canvas-legend__list">
          {LEGEND_STAGES.map((s) => (
            <div key={s} className="ln-canvas-legend__row">
              <span
                className="ln-canvas-legend__swatch"
                style={{ background: `var(--stage-${s})` }}
                data-testid={`legend-swatch-${s}`}
              />
              <span>{STAGE_LABEL[s]}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

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

  // Container ref for the Fullscreen API target (T8.6a). Wraps the
  // whole lineage-root so RF + chrome go fullscreen together.
  const rootRef = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={rootRef}
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
        <CanvasToolbar containerRef={rootRef} />
        <CanvasStatus model={model} />
        <CanvasLegend />
      </ReactFlow>
      <GraphTooltip
        node={hover?.node ?? null}
        x={hover?.x ?? 0}
        y={hover?.y ?? 0}
      />
    </div>
  );
}
