// frontend/src/lineage/graph/GraphNode.tsx
//
// V1.5.0 React Flow node renderer (Step 8, T8.3).
//
// Consumes the V1.5.0 GraphViewNode (no longer the raw backend LineageNode —
// adapter is the single boundary, see graphAdapter.ts). Visual structure:
//   ┌─────┬─────────────────────────────┐
//   │ bar │  KIND               [BADGE] │  ← row1: kind label + trust badge
//   │     │  Title (serif)              │
//   │     │  meta line                  │  ← summary or fallback
//   └─────┴─────────────────────────────┘
//
// ── Design decision (recorded T8.3 REV-2) ───────────────────────────
// The 8px left bar carries STAGE colour (var(--stage-${stage})), not
// trust. Spec §19.5 footnote ("--review left bar for review/needed,
// --caution left bar for caution/failed") and plan §10 T8.3 step 1
// ("background: var(--stage-${stage})") were in conflict; plan wins
// because (a) prototype uiux/graph.jsx L350 is also stage-driven,
// (b) spec L18's "tri-state visually distinguishable" requirement is
// satisfied by selected-outline + trust badge alone. Trust signal
// lives in the row1 badge.
//
// Badge precedence: blocker > caution > review (trust=review OR any decision
// reviewStatus ∈ {needed,failed}) > none. The decision-fallback
// inherits V1.4.1 NodeCard behaviour so a trust=ok node with a
// "needed" DP still flags for review — adapter's normalizeTrust does
// not consider decisions, so this fallback prevents a missed signal.
//
// Selected outline uses var(--ink) (≡ var(--tint) in V1.5.0; named
// separately to track spec/prototype vocabulary — see lineage.css).
// ────────────────────────────────────────────────────────────────────

import type { KeyboardEvent, MouseEvent } from "react";
import { Handle, Position } from "reactflow";
import "../tokens/lineage.css";
import type { GraphViewNode, HeadSetNode, Stage, Trust } from "../api/graphViewTypes";
import { ModelNodeBadge } from "../../workbench/ModelNodeBadge";
import { roleAbbrev, roleColorVar, roleLabel, type Role } from "../roles";

/** v1.6.5 (Problem 6) — when a node is a forest model node (carries a
 *  content `nodeHash` and at least one owning run), expose the identity the
 *  badge needs to disambiguate same-named reruns. Returns null otherwise. */
function forestModelIdentity(
  node: GraphViewNode,
): { runId: string; nodeHash: string; role: "source" | "rerun" } | null {
  const isModel = node.kind === "model" || node.stage === "model";
  if (!isModel) return null;
  const hs = node as Partial<HeadSetNode>;
  if (!hs.nodeHash || !hs.runs || hs.runs.length === 0) return null;
  const role = hs.rerunFrom || hs.runRerunFrom ? "rerun" : "source";
  return { runId: hs.runs[0], nodeHash: hs.nodeHash, role };
}

// T8.5 + V1.5.2 P6: 5-level highlight model. Plan §8.
//
// Priority high → low:
//   1. selected         — strongest ring (drawer's active tab)
//   2. focus            — pin/focus ring (when focus key ≠ selected)
//   3. focus-upstream   — above related but below focus itself
//   4. related          — selected's immediate neighbours (V1.5.0 behaviour)
//   5. dim              — everything else
//
// Search hits are NOT a state — they layer on top via `isSearchHit`
// so they never displace selected/focus. When nothing is selected AND
// nothing is focused, every node stays "related" (no dimming) — same
// V1.5.0 default.
export type GraphNodeState =
  | "selected"
  | "focus"
  | "focus-upstream"
  | "related"
  | "dim";

// V1.5.1: edge anchor orientation. Vertical (top→bottom) for TB
// layout; horizontal (left→right) for LR/free layout. Driven by
// GraphCanvas based on the current layout mode — embedding it in
// node data (rather than reading a context here) keeps the renderer
// pure and lets React Flow's diffing notice the change.
export type HandleAxis = "vertical" | "horizontal";

export interface GraphNodeProps {
  data: {
    node: GraphViewNode;
    state: GraphNodeState;
    handleAxis?: HandleAxis;
    /** V1.5.2 P6 — search overlay flag. Layered on top of state
     *  (does not displace selected/focus). Tier 3 / transient. */
    isSearchHit?: boolean;
    /** V1.5.3 F5 — the single current ⌘K cursor result. Layered on
     *  top of (and stronger than) isSearchHit so ↑/↓ navigation is
     *  visible. Tier 3 / transient. */
    isSearchCursor?: boolean;
    /** v1.6.5 — primary role for a variable node (drives badge + colour bar). */
    role?: Role;
    /** v1.6.5 — model-node roles tag: "unspecified" | "legacy_unspecified". */
    rolesTag?: string;
    /** v1.6.8 — folded variable groups toggle from inside the custom node. */
    groupId?: string;
    onToggleGroup?: (groupId: string) => void;
  };
  // React Flow also passes its own `selected` for accessibility / focus
  // styles on the wrapper, but our internal outline is driven by
  // data.state so the tri-state stays consistent under all paths.
  selected: boolean;
}

function stageColorVar(stage: Stage): string {
  // Synthetic / pre-V1.5.0 graphs map to a neutral grey via the CSS fallback;
  // the var() call returns the empty string for unknown so the rule's second
  // argument (`--label-tertiary`) kicks in.
  if (stage === "unknown") return "var(--label-tertiary)";
  return `var(--stage-${stage})`;
}

function reviewCount(node: GraphViewNode): number {
  return node.decisions.filter(
    (d) => d.reviewStatus === "needed" || d.reviewStatus === "failed",
  ).length;
}

interface BadgeDescriptor {
  variant: Trust;
  text: string;
}

// v1.6.7 — draft lifecycle visual language (see spec §3). Keyed by
// LifecycleState; real forest nodes have no lifecycleState so this map is
// never consulted for them (their style/appearance stays byte-for-byte).
const LIFECYCLE_STYLE: Record<string, { border: string; opacity: number; glow?: string }> = {
  draft: { border: "2px dashed var(--label-tertiary)", opacity: 0.75 },
  validating: { border: "2px dashed #c98a3a", opacity: 0.9 },
  valid: { border: "2px solid #3a9ac9", opacity: 1 },
  invalid: { border: "2px solid #b03a3a", opacity: 1 },
  pending: { border: "2px solid #c9a03a", opacity: 1, glow: "0 0 14px rgba(201,160,58,.55)" },
  executed: { border: "2px solid #1f6f43", opacity: 1 },
  failed: { border: "2px solid #b03a3a", opacity: 1 },
};

function badgeFor(node: GraphViewNode): BadgeDescriptor | null {
  const reviews = reviewCount(node);
  // v1.6.6 ④: blocker is the strongest variant — checked before caution.
  if (node.trust === "blocker") return { variant: "blocker", text: "Blocker" };
  if (node.trust === "caution") return { variant: "caution", text: "Caution" };
  // Review badge fires for either trust=review OR any decision needs review.
  if (node.trust === "review" || reviews > 0)
    return { variant: "review", text: "Review" };
  return null;
}

export function GraphNode({ data }: GraphNodeProps) {
  const {
    node,
    state,
    handleAxis = "horizontal",
    isSearchHit = false,
    isSearchCursor = false,
    role,
    rolesTag,
    groupId,
    onToggleGroup,
  } = data;
  const badge = badgeFor(node);
  const colorVar = stageColorVar(node.stage);
  const isSelected = state === "selected";
  const isFocus = state === "focus";
  const isFocusUpstream = state === "focus-upstream";
  const isDim = state === "dim";
  // V1.5.1: edges enter on the upstream-facing side and leave on the
  // downstream-facing side. Without this, an LR layout produced
  // S-shaped curves (bottom→top across horizontally-spaced cards).
  const targetPos =
    handleAxis === "vertical" ? Position.Top : Position.Left;
  const sourcePos =
    handleAxis === "vertical" ? Position.Bottom : Position.Right;

  // React Flow needs explicit handles on custom nodes for edges to attach. We
  // hide them visually (they're just connection anchors, not interactive).
  const handleStyle = {
    background: "transparent",
    border: 0,
    width: 1,
    height: 1,
    minWidth: 1,
    minHeight: 1,
  };
  const canToggleGroup = Boolean(groupId && onToggleGroup);
  const toggleGroup = () => {
    if (!groupId || !onToggleGroup) return;
    onToggleGroup(groupId);
  };
  const onToggleClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!canToggleGroup) return;
    event.stopPropagation();
    toggleGroup();
  };
  const onToggleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!canToggleGroup) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    event.stopPropagation();
    toggleGroup();
  };

  return (
    <div
      role={canToggleGroup ? "button" : undefined}
      tabIndex={canToggleGroup ? 0 : undefined}
      aria-label={canToggleGroup ? node.title : undefined}
      onClick={onToggleClick}
      onKeyDown={onToggleKeyDown}
      className={[
        "ln-graph-node",
        isSelected && "ln-graph-node--selected",
        isFocus && "ln-graph-node--focus",
        isFocusUpstream && "ln-graph-node--focus-upstream",
        isDim && "ln-graph-node--dim",
        isSearchHit && "ln-graph-node--search-hit",
        isSearchCursor && "ln-graph-node--search-cursor",
      ]
        .filter(Boolean)
        .join(" ")}
      // v1.6.7: draft nodes get a distinct testid so tests/queries can
      // target them; real forest nodes keep "graph-node" unchanged.
      data-testid={node.isDraft ? "graph-node-lifecycle" : "graph-node"}
      data-stage={node.stage}
      data-trust={node.trust}
      data-state={state}
      data-lifecycle={node.lifecycleState}
      data-search-hit={isSearchHit ? "true" : undefined}
      data-search-cursor={isSearchCursor ? "true" : undefined}
      style={{
        ["--node-color" as string]: role ? roleColorVar(role) : colorVar,
        ...(node.lifecycleState && LIFECYCLE_STYLE[node.lifecycleState]
          ? {
              border: LIFECYCLE_STYLE[node.lifecycleState].border,
              opacity: LIFECYCLE_STYLE[node.lifecycleState].opacity,
              boxShadow: LIFECYCLE_STYLE[node.lifecycleState].glow,
            }
          : {}),
      }}
    >
      <Handle
        type="target"
        position={targetPos}
        isConnectable={false}
        style={handleStyle}
      />
      <div className="ln-graph-node__bar" />
      <div className="ln-graph-node__body">
        <div className="ln-graph-node__row1">
          <span className="ln-graph-node__kind">{node.kind}</span>
          {role && (
            <span
              className="ln-graph-node__role-badge"
              data-testid="node-role-badge"
              data-role={role}
              title={roleLabel(role)}
              style={{ ["--role-color" as string]: roleColorVar(role) }}
            >
              {roleAbbrev(role)}
            </span>
          )}
          {rolesTag && (
            <span
              className="ln-graph-node__roles-tag"
              data-testid="node-roles-tag"
            >
              roles: {rolesTag}
            </span>
          )}
          {badge && (
            <span
              className={`ln-graph-node__badge ln-graph-node__badge--${badge.variant}`}
              data-testid="node-badge"
              // v1.6.6 ④: surface the trust reason as a native tooltip.
              title={node.trustReason || undefined}
            >
              {badge.text}
            </span>
          )}
        </div>
        <div className="ln-graph-node__title">{node.title}</div>
        {(() => {
          const id = forestModelIdentity(node);
          return id ? (
            <div className="ln-graph-node__meta" data-testid="node-model-badge">
              <ModelNodeBadge runId={id.runId} nodeHash={id.nodeHash} role={id.role} />
            </div>
          ) : null;
        })()}
        {node.summary && (
          <div className="ln-graph-node__meta" data-testid="node-summary">
            {node.summary}
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={sourcePos}
        isConnectable={false}
        style={handleStyle}
      />
    </div>
  );
}
