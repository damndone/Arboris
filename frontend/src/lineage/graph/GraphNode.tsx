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
// Badge precedence: caution > review (trust=review OR any decision
// reviewStatus ∈ {needed,failed}) > none. The decision-fallback
// inherits V1.4.1 NodeCard behaviour so a trust=ok node with a
// "needed" DP still flags for review — adapter's normalizeTrust does
// not consider decisions, so this fallback prevents a missed signal.
//
// Selected outline uses var(--ink) (≡ var(--tint) in V1.5.0; named
// separately to track spec/prototype vocabulary — see lineage.css).
// ────────────────────────────────────────────────────────────────────

import { Handle, Position } from "reactflow";
import "../tokens/lineage.css";
import type { GraphViewNode, Stage, Trust } from "../api/graphViewTypes";

// T8.5: tri-state highlighting. When a node is selected, its
// neighbourhood (incoming + outgoing edges + the selected node itself)
// stays at full opacity; everything else dims. Computed and passed in
// by GraphCanvas; "related" is also the default when nothing is
// selected (all nodes full opacity).
export type GraphNodeState = "selected" | "related" | "dim";

export interface GraphNodeProps {
  data: { node: GraphViewNode; state: GraphNodeState };
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

function badgeFor(node: GraphViewNode): BadgeDescriptor | null {
  const reviews = reviewCount(node);
  if (node.trust === "caution") return { variant: "caution", text: "Caution" };
  // Review badge fires for either trust=review OR any decision needs review.
  if (node.trust === "review" || reviews > 0)
    return { variant: "review", text: "Review" };
  return null;
}

export function GraphNode({ data }: GraphNodeProps) {
  const { node, state } = data;
  const badge = badgeFor(node);
  const colorVar = stageColorVar(node.stage);
  const isSelected = state === "selected";
  const isDim = state === "dim";

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

  return (
    <div
      className={`ln-graph-node${isSelected ? " ln-graph-node--selected" : ""}${isDim ? " ln-graph-node--dim" : ""}`}
      data-testid="graph-node"
      data-stage={node.stage}
      data-trust={node.trust}
      data-state={state}
      style={{ ["--node-color" as string]: colorVar }}
    >
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={false}
        style={handleStyle}
      />
      <div className="ln-graph-node__bar" />
      <div className="ln-graph-node__body">
        <div className="ln-graph-node__row1">
          <span className="ln-graph-node__kind">{node.kind}</span>
          {badge && (
            <span
              className={`ln-graph-node__badge ln-graph-node__badge--${badge.variant}`}
              data-testid="node-badge"
            >
              {badge.text}
            </span>
          )}
        </div>
        <div className="ln-graph-node__title">{node.title}</div>
        {node.summary && (
          <div className="ln-graph-node__meta" data-testid="node-summary">
            {node.summary}
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        style={handleStyle}
      />
    </div>
  );
}
