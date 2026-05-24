import "../tokens/lineage.css";
import type { DecisionPoint } from "../types";
import { getDPDisplay } from "./decisionRegistry";

export interface DecisionCardProps {
  dp: DecisionPoint;
  expanded: boolean;
  onToggle: () => void;
}

export function DecisionCard({ dp, expanded, onToggle }: DecisionCardProps) {
  const display = getDPDisplay(dp.decision_id);
  const params = dp.reason?.chosen_params ?? {};
  const selected = display.displaySelected(dp.selected);
  const why = display.whyShort(params);
  const alts = display.displayAlternatives(params).join(" · ");
  const needsReview = ["needed", "failed"].includes(
    dp.contestability.review_status,
  );

  return (
    <button
      onClick={onToggle}
      className="ln-card"
      style={{
        background: "var(--bg-card-2)",
        borderRadius: 12,
        padding: "14px 16px",
        marginBottom: 10,
        width: "100%",
        textAlign: "left",
        border: 0,
        cursor: "pointer",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: 8,
        color: "inherit",
        font: "inherit",
      }}
    >
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontSize: 15,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          {needsReview && (
            <span data-testid="dp-warn-icon" style={{ color: "var(--orange)" }}>
              ⚠
            </span>
          )}
          {display.title}
        </div>
        <div
          style={{
            marginTop: 8,
            color: "var(--label-secondary)",
            fontSize: 13,
          }}
        >
          <div>
            <span style={{ color: "var(--label-tertiary)" }}>Selected: </span>
            <strong style={{ color: "var(--label)" }}>{selected}</strong>
          </div>
          {why && (
            <div style={{ marginTop: 3 }}>
              <span style={{ color: "var(--label-tertiary)" }}>Why: </span>
              {why}
            </div>
          )}
          {alts && (
            <div style={{ marginTop: 3 }}>
              <span style={{ color: "var(--label-tertiary)" }}>
                Alternatives:{" "}
              </span>
              {alts}
            </div>
          )}
        </div>
      </div>
      <span
        style={{
          color: "var(--label-tertiary)",
          fontSize: 16,
          transition: "transform 0.15s",
          transform: expanded ? "rotate(90deg)" : "none",
        }}
      >
        ›
      </span>
    </button>
  );
}
