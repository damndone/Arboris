// v1.6.12 T2 (V3) — AI activity panel: read-only timeline of every AI
// interaction in this project (Ask AI Q&A + report generations), fed by the
// typed AiActivityRecord log. This panel is the first consumer of the
// operation-record contract that v1.7's propose→confirm→execute→trace loop
// will extend.
import { useEffect, useState } from "react";
import {
  AI_ACTIVITY_EVENT,
  loadAiActivity,
  type AiActivityRecord,
} from "../../aiActivity/aiActivityLog";
import { renderMarkdown } from "../../report/markdown";
import type { BottomPanelContext } from "../registry/bottomPanelRegistry";

export function AiActivityPanel({ projectRoot }: BottomPanelContext) {
  const [records, setRecords] = useState<AiActivityRecord[]>(() =>
    loadAiActivity(projectRoot),
  );

  useEffect(() => {
    setRecords(loadAiActivity(projectRoot));
    const refresh = () => setRecords(loadAiActivity(projectRoot));
    window.addEventListener(AI_ACTIVITY_EVENT, refresh);
    return () => window.removeEventListener(AI_ACTIVITY_EVENT, refresh);
  }, [projectRoot]);

  if (records.length === 0) {
    return (
      <div
        data-testid="ai-activity-empty"
        style={{ padding: 14, fontSize: 12, color: "var(--label-tertiary)" }}
      >
        No AI activity yet — Ask AI answers and generated reports will be
        logged here, per project.
      </div>
    );
  }

  return (
    <div
      data-testid="ai-activity-panel"
      style={{
        padding: "8px 14px",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        fontSize: 12,
      }}
    >
      {records.map((record) => (
        <ActivityRow key={record.id} record={record} />
      ))}
    </div>
  );
}

function ActivityRow({ record }: { record: AiActivityRecord }) {
  const stamp = new Date(record.at).toLocaleString();
  if (record.kind === "report_generate") {
    return (
      <div
        data-testid="ai-activity-report"
        style={{ border: "1px solid var(--separator)", borderRadius: 6, padding: "6px 10px" }}
      >
        <div style={{ color: "var(--label-tertiary)", fontSize: 10.5 }}>
          {stamp} · report{record.model ? ` · ${record.model}` : ""} · run{" "}
          {record.run_id} · {record.fact_count} facts
          {record.excluded_count > 0 ? ` · ${record.excluded_count} excluded` : ""}
        </div>
        <div style={{ marginTop: 3 }}>{record.instruction}</div>
      </div>
    );
  }
  return (
    <div
      data-testid="ai-activity-ask"
      style={{ border: "1px solid var(--separator)", borderRadius: 6, padding: "6px 10px" }}
    >
      <div style={{ color: "var(--label-tertiary)", fontSize: 10.5 }}>
        {stamp} · Ask AI · {record.node_label}
        {record.model ? ` · ${record.model}` : ""}
        {record.status === "error" ? " · failed" : ""}
      </div>
      <div style={{ fontWeight: 600, margin: "3px 0" }}>{record.question}</div>
      {record.status === "answered" ? (
        <details>
          <summary style={{ cursor: "pointer", fontSize: 11 }}>Answer</summary>
          <div style={{ marginTop: 4 }}>{renderMarkdown(record.answer ?? "")}</div>
        </details>
      ) : (
        <div style={{ color: "var(--danger, #b00020)" }}>{record.error}</div>
      )}
    </div>
  );
}
