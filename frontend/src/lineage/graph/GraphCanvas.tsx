import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Panel,
  useReactFlow,
  useNodesState,
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

// V1.5.1 T4' — layout mode. "free" is the default (user-arranged after
// initial seed). "LR" / "TB" run dagre with that rankdir on demand and
// snap nodes to the result. Switching back to "free" preserves the most
// recent positions (via useNodesState ownership; see HF5 comment below).
export type LayoutMode = "free" | "LR" | "TB";
export const DEFAULT_LAYOUT: LayoutMode = "free";

interface CanvasToolbarProps {
  containerRef: React.RefObject<HTMLDivElement>;
  layout: LayoutMode;
  onLayout: (mode: LayoutMode) => void;
}

function CanvasToolbar({ containerRef, layout, onLayout }: CanvasToolbarProps) {
  const { fitView } = useReactFlow();
  const onFit = () => fitView({ padding: 0.2, duration: 200 });
  const onFullscreen = async () => {
    const el = containerRef.current;
    if (!el) return;
    // Fullscreen API may be unsupported (older browsers, embedded
    // contexts) or rejected (user gesture missing, security policy).
    // Both branches degrade gracefully — no banner, no throw.
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
  const layoutBtn = (mode: LayoutMode, label: string, title: string) => (
    <button
      type="button"
      onClick={() => onLayout(mode)}
      data-testid={`toolbar-layout-${mode.toLowerCase()}`}
      data-active={layout === mode ? "true" : undefined}
      aria-pressed={layout === mode}
      title={title}
    >
      {label}
    </button>
  );
  return (
    <Panel position="top-left">
      <div
        className="ln-canvas-toolbar"
        data-testid="canvas-toolbar"
        role="group"
        aria-label="Canvas layout"
      >
        {/* V1.5.1 T4' — Free is the default (per user 2026-05-25).
         * Horizontal/Vertical click forces a fresh dagre re-layout with
         * that rankdir; clicking Free again stops forced re-layouts
         * (positions are preserved by useNodesState below). */}
        {layoutBtn("free", "Free", "Free layout — drag nodes anywhere")}
        {layoutBtn("LR", "Horizontal", "Horizontal flow (left → right)")}
        {layoutBtn("TB", "Vertical", "Vertical flow (top → bottom)")}
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
  /** V1.5.1 T4' — controlled layout. Defaults to "free" when omitted. */
  layout?: LayoutMode;
  onLayoutChange?: (mode: LayoutMode) => void;
  /** V1.5.2 P4 — right-click on a node. Receives the node id + the
   *  viewport-coordinate event so a portal context menu can position
   *  itself. Omit to disable right-click in tests / legacy consumers. */
  onNodeContextMenu?: (nodeId: string, x: number, y: number) => void;
}

function layoutDagre<T extends RFNode>(
  nodes: T[],
  edges: RFEdge[],
  rankdir: "TB" | "LR" = "LR",
): T[] {
  // V1.5.1 T4' — default rankdir flipped to LR. The graph reads as a
  // pipeline (source → eda → … → report); horizontal flow matches the
  // editorial prototype's visual rhythm better than vertical for wide
  // screens. Vertical is still selectable via the layout toolbar.
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir, nodesep: 40, ranksep: 60 });
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
  layout: layoutProp,
  onLayoutChange,
  onNodeContextMenu,
}: GraphCanvasProps) {
  // V1.5.1 T4' — layout state. Controlled when `layout` prop is supplied
  // (T4'.1 will hoist to LineageContext), uncontrolled fallback otherwise.
  // `layoutVersion` increments on every user click so the seedNodes
  // useMemo re-runs even when nothing else changed — that's how a
  // "Horizontal" or "Vertical" click forces a fresh dagre snap.
  const [layoutLocal, setLayoutLocal] = useState<LayoutMode>(DEFAULT_LAYOUT);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const layout = layoutProp ?? layoutLocal;
  const handleLayout = useCallback(
    (mode: LayoutMode) => {
      if (onLayoutChange) onLayoutChange(mode);
      else setLayoutLocal(mode);
      setLayoutVersion((v) => v + 1);
    },
    [onLayoutChange],
  );

  // Hoisted out of the main useMemo so a selection-only re-render (which
  // bumps selectedNodeId but not model) doesn't pay an O(n) Map rebuild.
  // [REV-3 #6 — Step 5 adversarial review]
  const nodeById = useMemo(
    () => new Map(model.nodes.map((n) => [n.id, n])),
    [model.nodes],
  );

  // V1.5.0.1 HF5: the seed layout (positions + edges) depends only on
  // graph structure — model.nodes, model.edges, expandedGroups. Selection
  // and the related-set are applied as a decoration overlay (below)
  // without rebuilding positions, so dragged cards don't snap back to
  // dagre on every selection change.
  const { seedNodes, rfEdges, memberToGroup } = useMemo(() => {
    const { kept, groups } = foldVariableClusters(model.nodes, expandedGroups);

    const visible = new Set<string>(kept.map((n) => n.id));
    groups.forEach((g) => visible.add(g.id));

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
      if (!nodeById.has(parsed.parent)) continue;
      expandedMarkers.push({ gid, ...parsed });
      visible.add(gid);
    }

    const memberToGroup = new Map<string, string>();
    groups.forEach((g) =>
      g.member_ids.forEach((m) => memberToGroup.set(m, g.id)),
    );

    const realNodes: RFNode[] = kept.map((n) => ({
      id: n.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      // T8.3: GraphNode consumes V1.5.0 GraphViewNode directly. Selection
      // state is overlaid by the decoratedNodes useMemo, not here.
      data: { node: n, state: "related" },
      selected: false,
    }));
    const groupNodes: RFNode[] = groups.map((g) => ({
      id: g.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: { node: groupAsNode(g), state: "related" },
      selected: false,
    }));
    const markerNodes: RFNode[] = expandedMarkers.map((m) => ({
      id: m.gid,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: {
        node: markerAsNode(m.gid, m.variantLabel, m.parent),
        state: "related",
      },
      selected: false,
    }));

    const candidateEdges: RFEdge[] = [];
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

    // V1.5.1 T4' — rankdir derives from layout mode. "free" still seeds
    // with LR dagre so first paint is sensible; once seeded, HF5's
    // useNodesState ownership lets the user drag freely without snap-back.
    // Clicking Horizontal/Vertical bumps layoutVersion, which re-runs this
    // useMemo and produces a fresh dagre snap.
    const rankdir: "TB" | "LR" = layout === "TB" ? "TB" : "LR";
    const layouted = layoutDagre(
      [...realNodes, ...groupNodes, ...markerNodes],
      uniqEdges,
      rankdir,
    );
    return { seedNodes: layouted, rfEdges: uniqEdges, memberToGroup };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, expandedGroups, nodeById, layout, layoutVersion]);

  // V1.5.0.1 HF5: useNodesState lets React Flow own the live position
  // state, so node drag mutations stick. We re-seed from layoutDagre
  // ONLY when the graph identity changes (i.e., the set of node ids
  // changes). Selection changes do NOT re-seed.
  //
  // V1.5.1 T4': also re-seed when the user clicks a Layout button
  // (Free/Horizontal/Vertical). layoutVersion ticks on every click; we
  // fold it into the seed key so a re-layout actually replaces
  // positions even though node ids are stable.
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(seedNodes);
  const lastSeedKey = useRef<string>("");
  useEffect(() => {
    const key = `v${layoutVersion}:${layout}:${seedNodes.map((n) => n.id).join("|")}`;
    if (key !== lastSeedKey.current) {
      setRfNodes(seedNodes);
      lastSeedKey.current = key;
    }
  }, [seedNodes, setRfNodes, layout, layoutVersion]);

  // T8.5: tri-state highlight + selected flag overlaid on top of the
  // RF-owned node state. Re-runs cheaply on selection change without
  // touching positions.
  // V1.5.1 T4': handleAxis flips edge anchor sides so LR layout edges
  // come out the right side (not bottom) — kills the S-curve look the
  // user flagged 2026-05-25.
  const handleAxis = layout === "TB" ? "vertical" : "horizontal";
  const decoratedNodes = useMemo(() => {
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
    return rfNodes.map((n) => ({
      ...n,
      selected: n.id === selectedNodeId,
      data: { ...n.data, state: stateFor(n.id), handleAxis },
    }));
  }, [rfNodes, selectedNodeId, model.edges, memberToGroup, handleAxis]);

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
      data-graph="true"
      style={{ width: "100%", height: "100%", minHeight: 480 }}
    >
      <ReactFlow
        nodes={decoratedNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        // V1.5.0.1 HF5: free node drag matches the prototype's contract
        // (uiux/app.jsx TWEAK_DEFAULTS layout=free; uiux/panels.jsx empty
        // drawer hint "拖拽 = 重排"). Positions are owned by RF state
        // via useNodesState above; dagre is the initial seed only.
        nodesDraggable={true}
        // V1.5.0.1 HF5: pin edge type to RF's bezier default so a future
        // RF upgrade can't silently switch us to step / smoothstep.
        // Matches uiux/app.jsx TWEAK_DEFAULTS edgeStyle="bezier".
        defaultEdgeOptions={{ type: "default" }}
        onNodesChange={onNodesChange}
        nodesConnectable={false}
        elementsSelectable={true}
        onNodeClick={(_, n) => {
          if (n.id.startsWith("group:")) onExpandGroup(n.id);
          else onSelect(n.id);
        }}
        onNodeContextMenu={(e, n) => {
          // V1.5.2 P4 — open the workbench context menu. Suppress the
          // browser default so the registry menu is the only one shown.
          // Group nodes don't have actions so we ignore them.
          if (n.id.startsWith("group:")) return;
          if (!onNodeContextMenu) return;
          e.preventDefault();
          onNodeContextMenu(n.id, e.clientX, e.clientY);
        }}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseMove={onNodeMouseMove}
        onNodeMouseLeave={onNodeMouseLeave}
        fitView
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
        <CanvasToolbar
          containerRef={rootRef}
          layout={layout}
          onLayout={handleLayout}
        />
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
