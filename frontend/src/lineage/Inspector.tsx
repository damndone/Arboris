import { useId } from "react";
import "./lineage.css";
import type { LineageNode } from "./types";
import { getDPDisplay } from "./dpRegistry";

export interface InspectorProps {
  node: LineageNode;
  onClose: () => void;
}

function reviewCount(node: LineageNode): number {
  return node.decision_points.filter(
    (dp) =>
      dp.contestability.review_status === "needed" ||
      dp.contestability.review_status === "failed",
  ).length;
}

function aboutProse(node: LineageNode): string {
  if (node.kind === "model" && node.summary) return node.summary;
  if (node.kind === "dataset_stage" && node.summary) return node.summary;
  if (node.kind === "variable" && node.summary) {
    return `Variable '${node.display_label.replace(/\s*\(.*\)$/, "")}': ${node.summary.toLowerCase()}.`;
  }
  return node.summary ?? node.display_label;
}

export function Inspector({ node, onClose }: InspectorProps) {
  const titleId = useId();
  const reviewN = reviewCount(node);

  type CalloutVariant = "orange" | "red" | "green";
  let variant: CalloutVariant = "green";
  let calloutTitle = "✓ All clear";
  let calloutBody = "";
  if (reviewN > 0) {
    variant = "orange";
    calloutTitle = "⚠ Review required";
    const titles = node.decision_points
      .filter((dp) =>
        ["needed", "failed"].includes(dp.contestability.review_status),
      )
      .map((dp) => getDPDisplay(dp.decision_id).title.toLowerCase());
    calloutBody = `${reviewN} ${reviewN === 1 ? "choice needs" : "choices need"} confirmation: ${titles.join(" and ")}.`;
  } else if (node.trust === "warning" || node.trust === "blocker") {
    variant = "red";
    calloutTitle = `⚠ Trust: ${node.trust}`;
    calloutBody = node.trust_reason ?? "";
  }

  return (
    <div
      role="dialog"
      aria-labelledby={titleId}
      className="lineage-root ln-card"
      style={{ width: 440, padding: 0, borderRadius: 14 }}
    >
      <div
        style={{
          padding: "20px 22px 14px",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <div>
          <div className="ln-section-label" style={{ marginBottom: 2 }}>
            {node.kind.replace(/_/g, " ").toUpperCase()} · {node.id}
          </div>
          <div
            id={titleId}
            style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.3 }}
          >
            {node.display_label}
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="ln-btn-secondary"
          style={{
            width: 28,
            height: 28,
            borderRadius: 14,
            padding: 0,
            fontSize: 14,
          }}
        >
          ✕
        </button>
      </div>

      <div style={{ padding: "0 22px 16px", fontSize: 15, lineHeight: 1.45 }}>
        {aboutProse(node)}
      </div>

      <div style={{ padding: "0 22px 16px" }}>
        <div className={`ln-callout ln-callout--${variant}`} aria-live="polite">
          <div className="ln-callout-title">{calloutTitle}</div>
          {calloutBody && <div className="ln-callout-body">{calloutBody}</div>}
        </div>
      </div>

      <div
        style={{
          padding: "12px 22px 18px",
          color: "var(--label-tertiary)",
          fontSize: 12,
          borderTop: "0.5px solid var(--separator)",
        }}
      >
        {node.payload_ref && (
          <>
            📎 {node.payload_ref}
            <br />
          </>
        )}
        {node.created_at && <>🕐 {node.created_at}</>}
      </div>
    </div>
  );
}
