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
import { rolesByVariable, primaryRole } from "./variableRoles";
import { roleEdgeStyle, suppressAggregateEdges, isRoleOp } from "./roleEdges";

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

// v1.6.5 — non-interactive container drawn BEHIND an expanded variable
// cluster so the user sees the variables belong to one logical group. The
// header is the fold-back affordance (click → onExpandGroup, routed by id in
// onNodeClick). Sized by GraphCanvas to the members' bounding box.
function VarContainerNode({ data }: { data: { label: string; gid: string } }) {
  return (
    <div className="ln-var-container" data-testid="var-container">
      <div className="ln-var-container__header">{data.label}</div>
    </div>
  );
}

const nodeTypes = { lineageNode: GraphNode, varContainer: VarContainerNode };

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
  /** V1.5.2 P6 — focus anchor (plan §8 priority #2). When set AND
   *  different from `selectedNodeId`, the node renders with a distinct
   *  focus ring. */
  focusNodeKey?: string | null;
  /** V1.5.2 P6 — caller-computed upstream set of `focusNodeKey`.
   *  GraphCanvas doesn't walk the graph itself; GraphView passes a
   *  ReadonlySet built from RunSnapshotAdapter.upstreamOf so walk
   *  semantics match Drawer chips + AI scope. */
  focusUpstreamKeys?: ReadonlySet<string>;
  /** V1.5.2 P6 — search-hit overlay set (Tier 3). Layered on top of
   *  the state class, never displaces selected/focus. Empty when no
   *  search is active. */
  searchHitKeys?: ReadonlySet<string>;
  /** V1.5.3 F5 — the single "current cursor" search hit (the row the
   *  user is on in the ⌘K palette). Rendered one tier stronger than
   *  the other searchHits so ↑/↓ navigation is visible on the canvas.
   *  null when the palette is closed or has no results. */
  searchCursorKey?: string | null;
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

export function GraphCanvas({
  model,
  selectedNodeId,
  expandedGroups,
  onSelect,
  onExpandGroup,
  layout: layoutProp,
  onLayoutChange,
  onNodeContextMenu,
  focusNodeKey = null,
  focusUpstreamKeys,
  searchHitKeys,
  searchCursorKey = null,
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

    // v1.6.5: which role(s) each variable node holds for the primary model,
    // derived from the role-bearing var→model edges.
    const primaryModelId =
      model.nodes.find((n) => n.kind === "model")?.id ?? "";
    const varRoles = rolesByVariable(model.edges, primaryModelId);

    // v1.6.5: model-node roles tag (spec §5 back-compat). `legacy_unspecified`
    // = run predates the role layer (no role edges at all); `unspecified` =
    // RHS has only the explanatory fallback (no declared focal/covariate split).
    const anyRoleEdges = model.edges.some((e) => isRoleOp(e.op));
    const rhsRoles = new Set(
      [...varRoles.values()].flat().filter((r) =>
        [
          "focal",
          "treatment",
          "covariates",
          "instruments",
          "exposure",
          "explanatory_unspecified",
        ].includes(r),
      ),
    );
    const modelTag = !anyRoleEdges
      ? "legacy_unspecified"
      : rhsRoles.size > 0 &&
          [...rhsRoles].every((r) => r === "explanatory_unspecified")
        ? "unspecified"
        : undefined;

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

    const realNodes: RFNode[] = kept.map((n) => {
      const roles = varRoles.get(n.id);
      return {
        id: n.id,
        type: "lineageNode",
        position: { x: 0, y: 0 },
        // T8.3: GraphNode consumes V1.5.0 GraphViewNode directly. Selection
        // state is overlaid by the decoratedNodes useMemo, not here.
        // v1.6.5: variable nodes carry their primary role for badge/colour.
        data: {
          node: n,
          state: "related",
          ...(roles && roles.length ? { role: primaryRole(roles) } : {}),
          ...(n.kind === "model" && modelTag ? { rolesTag: modelTag } : {}),
        },
        selected: false,
      };
    });
    const groupNodes: RFNode[] = groups.map((g) => ({
      id: g.id,
      type: "lineageNode",
      position: { x: 0, y: 0 },
      data: { node: groupAsNode(g), state: "related" },
      selected: false,
    }));
    const candidateEdges: RFEdge[] = [];
    // v1.6.5: drop the legacy aggregate stage→model fit edge when role edges
    // feed that model (P1: avoids a redundant parallel path), and style the
    // role edges solid/dashed + coloured by role.
    for (const e of suppressAggregateEdges(model.edges)) {
      const src = memberToGroup.get(e.source) ?? e.source;
      const tgt = memberToGroup.get(e.target) ?? e.target;
      if (src === tgt) continue;
      if (!visible.has(src) || !visible.has(tgt)) continue;
      candidateEdges.push({
        id: `${src}->${tgt}`,
        source: src,
        target: tgt,
        animated: false,
        ...(isRoleOp(e.op) ? { style: roleEdgeStyle(e.op!) } : {}),
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
      [...realNodes, ...groupNodes],
      uniqEdges,
      rankdir,
    );

    // v1.6.5: for each expanded variable group, draw a titled container box
    // behind its member variables (their dagre bounding box + padding). This
    // replaces the old stray "(expanded)" marker node (P2/P3). The header is
    // the fold-back affordance (routed by `container:` id in onNodeClick).
    const PAD = 24;
    const HEADER = 28;
    const NODE_W = 240;
    const NODE_H = 80;
    const containerNodes: RFNode[] = [];
    for (const m of expandedMarkers) {
      const wantDropped = m.gid.startsWith("group:dropped-variables:");
      const members = layouted.filter((rn) => {
        const orig = nodeById.get(rn.id);
        if (!orig || orig.kind !== "variable") return false;
        if (orig.parentStageId !== m.parent) return false;
        return rn.id.endsWith(":dropped") === wantDropped;
      });
      if (members.length === 0) continue;
      const xs = members.map((n) => n.position.x);
      const ys = members.map((n) => n.position.y);
      const minX = Math.min(...xs) - PAD;
      const minY = Math.min(...ys) - PAD - HEADER;
      const maxX = Math.max(...xs) + NODE_W + PAD;
      const maxY = Math.max(...ys) + NODE_H + PAD;
      containerNodes.push({
        id: `container:${m.gid}`,
        type: "varContainer",
        position: { x: minX, y: minY },
        data: { label: `${m.variantLabel} (${members.length})`, gid: m.gid },
        style: { width: maxX - minX, height: maxY - minY, zIndex: -1 },
        selectable: false,
        draggable: false,
      });
    }

    // Containers first so React Flow paints them behind the variables.
    return {
      seedNodes: [...containerNodes, ...layouted],
      rfEdges: uniqEdges,
      memberToGroup,
    };
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
    // Selected's immediate neighbours (V1.5.0 behaviour, unchanged).
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
    // V1.5.2 P6 — 5-level state per plan §8.
    const stateFor = (
      id: string,
    ): "selected" | "focus" | "focus-upstream" | "related" | "dim" => {
      if (id === selectedNodeId) return "selected";
      // focus only wins when it's distinct from selected (so a node
      // that is both stays "selected" — the stronger ring wins).
      if (focusNodeKey !== null && id === focusNodeKey) return "focus";
      if (focusUpstreamKeys?.has(id)) return "focus-upstream";
      // Fallback: when nothing is selected AND nothing is focused,
      // every node is "related" (no dimming) — same V1.5.0 default
      // so empty-state graphs look unchanged.
      if (selectedNodeId === null && focusNodeKey === null) return "related";
      if (related.has(id)) return "related";
      return "dim";
    };
    return rfNodes.map((n) => ({
      ...n,
      selected: n.id === selectedNodeId,
      data: {
        ...n.data,
        state: stateFor(n.id),
        handleAxis,
        isSearchHit: searchHitKeys?.has(n.id) ?? false,
        // F5: exactly one node (the palette cursor) gets this flag.
        isSearchCursor: searchCursorKey !== null && n.id === searchCursorKey,
      },
    }));
  }, [
    rfNodes,
    selectedNodeId,
    focusNodeKey,
    focusUpstreamKeys,
    searchHitKeys,
    searchCursorKey,
    model.edges,
    memberToGroup,
    handleAxis,
  ]);

  // Edge decoration: flow-animate the edges touching the selected node (and the focus
  // lineage, e.g. the active forest head) and keep them lit while the selection holds.
  // Positions/structure are untouched — this is a pure overlay like decoratedNodes.
  const decoratedEdges = useMemo(() => {
    const focusSet = focusUpstreamKeys;
    return rfEdges.map((e) => {
      const touchesSelected =
        selectedNodeId !== null &&
        (e.source === selectedNodeId || e.target === selectedNodeId);
      const onFocusLineage = !!focusSet && focusSet.has(e.source) && focusSet.has(e.target);
      if (!touchesSelected && !onFocusLineage) return e;
      return {
        ...e,
        animated: true,
        style: {
          ...(e.style ?? {}),
          stroke: "var(--tint, #0a84ff)",
          strokeWidth: 2,
          opacity: 1,
        },
      };
    });
  }, [rfEdges, selectedNodeId, focusUpstreamKeys]);

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
        edges={decoratedEdges}
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
          else if (n.id.startsWith("container:"))
            onExpandGroup(n.id.slice("container:".length));
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
