// frontend/src/lineage/graph/GraphTooltip.tsx
//
// V1.5.0 hover tooltip (Step 8, T8.4). Screen-space, portaled to
// document.body so React Flow's canvas zoom transform doesn't scale
// or shift the tooltip — pixel position derives from raw clientX/Y.
//
// The parent (GraphCanvas) owns the 240ms hover delay, mouse-position
// tracking, and selection-suppression — this component is a pure
// presentational portal.
//
// Content (plan T8.4 step 3): title, kind, id, runtime (if known),
// up to 2 stats samples, trust badge, keyboard hint. Forward-compat
// slots (runtime, stats) gracefully omit rows when undefined.

import { createPortal } from "react-dom";
import "../tokens/lineage.css";
import type { GraphViewNode, Trust } from "../api/graphViewTypes";

export interface GraphTooltipProps {
  node: GraphViewNode | null;
  x: number; // clientX from MouseEvent (screen-space)
  y: number; // clientY from MouseEvent
}

const TRUST_LABEL: Record<Trust, string> = {
  ok: "OK",
  review: "Review",
  caution: "Caution",
  blocker: "Blocker", // v1.6.6 ④
};

function formatStatValue(v: unknown): string {
  if (typeof v === "number") return v.toLocaleString();
  if (typeof v === "string") return v;
  return String(v);
}

export function GraphTooltip({ node, x, y }: GraphTooltipProps) {
  if (!node) return null;
  const statsEntries = node.stats
    ? Object.entries(node.stats).slice(0, 2)
    : [];

  const content = (
    <div
      className="ln-graph-tooltip"
      role="tooltip"
      data-testid="graph-tooltip"
      style={{ left: x + 18, top: y + 14 }}
    >
      <div className="ln-graph-tooltip__title">{node.title}</div>
      <div className="ln-graph-tooltip__sub">{node.kind}</div>
      <div className="ln-graph-tooltip__row">
        <span className="ln-graph-tooltip__k">id</span>
        <span className="ln-graph-tooltip__v">{node.id}</span>
      </div>
      {typeof node.runtimeMs === "number" && (
        <div className="ln-graph-tooltip__row">
          <span className="ln-graph-tooltip__k">runtime</span>
          <span className="ln-graph-tooltip__v">{node.runtimeMs} ms</span>
        </div>
      )}
      {statsEntries.map(([k, v]) => (
        <div key={k} className="ln-graph-tooltip__row">
          <span className="ln-graph-tooltip__k">{k}</span>
          <span className="ln-graph-tooltip__v">{formatStatValue(v)}</span>
        </div>
      ))}
      <div className="ln-graph-tooltip__row">
        <span className="ln-graph-tooltip__k">trust</span>
        <span className="ln-graph-tooltip__v">{TRUST_LABEL[node.trust]}</span>
      </div>
      {node.trustReason && (
        <div className="ln-graph-tooltip__row">
          <span className="ln-graph-tooltip__k">why</span>
          <span className="ln-graph-tooltip__v">{node.trustReason}</span>
        </div>
      )}
      <div className="ln-graph-tooltip__hint">Click to inspect</div>
    </div>
  );

  return createPortal(content, document.body);
}
