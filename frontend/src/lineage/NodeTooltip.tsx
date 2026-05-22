import type { LineageNode } from "./types";

export interface NodeTooltipProps {
  node: LineageNode;
  visible: boolean; // false when node is selected (Inspector open)
}

export function NodeTooltip({ node, visible }: NodeTooltipProps) {
  if (!visible) return null;
  const reviewN = node.decision_points.filter(
    (dp) =>
      dp.contestability.review_status === "needed" ||
      dp.contestability.review_status === "failed",
  ).length;
  return (
    <div
      className="ln-card"
      role="tooltip"
      style={{
        position: "absolute",
        left: 260,
        top: -4,
        width: 200,
        padding: 12,
        background: "var(--bg-card-2)",
        boxShadow: "0 8px 24px rgba(0,0,0,0.55)",
        pointerEvents: "none",
        zIndex: 5,
      }}
    >
      <div style={{ fontWeight: 600 }}>{node.display_label}</div>
      {node.summary && (
        <div
          style={{
            color: "var(--label-secondary)",
            fontSize: 11.5,
            marginTop: 2,
          }}
        >
          {node.summary}
        </div>
      )}
      {reviewN > 0 && (
        <div
          style={{ color: "var(--orange)", fontSize: 11.5, marginTop: 6 }}
        >
          {reviewN}{" "}
          {reviewN === 1 ? "choice needs" : "choices need"} review
        </div>
      )}
      <div
        style={{
          color: "var(--label-tertiary)",
          fontSize: 11,
          marginTop: 6,
          fontStyle: "italic",
        }}
      >
        Tap to inspect
      </div>
    </div>
  );
}
