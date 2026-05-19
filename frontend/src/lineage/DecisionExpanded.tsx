import type { ReactNode } from "react";
import "./lineage.css";
import type { DecisionPoint } from "./types";
import { getDPDisplay } from "./dpRegistry";

export interface DecisionExpandedProps {
  dp: DecisionPoint;
}

export function DecisionExpanded({ dp }: DecisionExpandedProps) {
  const d = getDPDisplay(dp.decision_id);
  const params = dp.reason?.chosen_params ?? {};
  const alts = d.displayAlternatives(params);
  const checks = dp.contestability.assumption_checks_needed;
  const evidence = (d.evidenceFields ?? []).map((k) => ({
    key: k,
    value: params[k],
  }));

  const sec = (label: string, content: ReactNode) => (
    <div style={{ marginTop: 16 }}>
      <div className="ln-section-label" style={{ marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 14, lineHeight: 1.5 }}>{content}</div>
    </div>
  );

  return (
    <div
      className="ln-card"
      style={{
        background: "var(--bg-card-2)",
        borderRadius: 12,
        padding: 18,
      }}
    >
      <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>
        {d.title}
      </div>

      {sec(
        "Selected choice",
        <div style={{ fontSize: 18, fontWeight: 600 }}>
          {d.displaySelected(dp.selected)}
        </div>,
      )}

      {sec("Why this was chosen", d.whyLong(params))}

      {sec(
        "What to confirm",
        <div style={{ color: "var(--orange)" }}>{d.confirmPrompt}</div>,
      )}

      {alts.length > 0 &&
        sec(
          "Alternatives",
          <div style={{ color: "var(--label-secondary)" }}>
            {alts.join(" · ")}
          </div>,
        )}

      {(checks.length > 0 || evidence.length > 0) &&
        sec(
          "Evidence",
          <ul
            style={{
              margin: "4px 0 0 18px",
              color: "var(--label-secondary)",
              fontSize: 13,
            }}
          >
            {evidence.map((e) => (
              <li key={e.key}>
                {e.key}: {String(e.value)}
              </li>
            ))}
            {checks.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>,
        )}

      {sec(
        "Technical",
        <div>
          <code
            style={{
              fontFamily: "ui-monospace, SF Mono, monospace",
              color: "var(--label-secondary)",
              fontSize: 12.5,
            }}
          >
            ID: {dp.decision_id}
          </code>
          <div
            style={{
              color: "var(--label-tertiary)",
              fontSize: 11.5,
              marginTop: 4,
            }}
          >
            Source: {dp.source}
          </div>
        </div>,
      )}
    </div>
  );
}
