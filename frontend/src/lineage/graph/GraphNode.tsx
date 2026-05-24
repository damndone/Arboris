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
// The 8px left bar is coloured per stage via `var(--stage-${stage})`; the
// trust badge appears for review / caution only ("ok" → no badge).
// Selected state adds an outline derived from --tint.

import { Handle, Position } from "reactflow";
import "../tokens/lineage.css";
import type { GraphViewNode, Stage, Trust } from "../api/graphViewTypes";

export interface GraphNodeProps {
  data: { node: GraphViewNode };
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

export function GraphNode({ data, selected }: GraphNodeProps) {
  const { node } = data;
  const badge = badgeFor(node);
  const colorVar = stageColorVar(node.stage);

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
      className={`ln-graph-node ${selected ? "ln-graph-node--selected" : ""}`}
      data-testid="graph-node"
      data-stage={node.stage}
      data-trust={node.trust}
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
