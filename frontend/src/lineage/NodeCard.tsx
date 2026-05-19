import type { ReactNode } from "react";
import "./lineage.css";
import type { LineageNode } from "./types";

export interface NodeCardProps {
  data: { node: LineageNode };
  selected: boolean;
}

function reviewCount(node: LineageNode): number {
  return node.decision_points.filter(
    (dp) =>
      dp.contestability.review_status === "needed" ||
      dp.contestability.review_status === "failed",
  ).length;
}

export function NodeCard({ data, selected }: NodeCardProps) {
  const { node } = data;
  const reviewN = reviewCount(node);
  const trustNeedsBadge =
    node.trust === "warning" || node.trust === "blocker";

  let pill: ReactNode = null;
  if (reviewN > 0) {
    pill = (
      <span className="ln-pill ln-pill--orange" data-testid="node-pill">
        ⚠ Review · {reviewN}
      </span>
    );
  } else if (trustNeedsBadge) {
    pill = (
      <span
        className={`ln-pill ${node.trust === "blocker" ? "ln-pill--red" : "ln-pill--orange"}`}
        data-testid="node-pill"
      >
        ⚠ {node.trust}
      </span>
    );
  }

  return (
    <div
      className={`ln-card ln-node ${selected ? "ln-node--selected" : ""}`}
      style={{ width: 240, padding: 12 }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>{node.display_label}</div>
      {node.summary && (
        <div
          data-testid="node-summary"
          style={{
            color: "var(--label-secondary)",
            fontSize: 12,
            marginTop: 3,
          }}
        >
          {node.summary}
        </div>
      )}
      {pill && <div style={{ marginTop: 8 }}>{pill}</div>}
    </div>
  );
}
