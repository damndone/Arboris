// frontend/src/workbench/panels/LogsPanel.tsx
//
// V1.5.2 P4 — live Logs panel for the workbench bottom panel.
//
// Subscribes to /runs/<runId>/events via the existing `connectRunEvents`
// SSE helper while mounted. For an in-progress run, events stream as the
// orchestrator emits them; for a completed run, the server replays the
// durable workflow_log.jsonl and closes the stream. This keeps Logs useful
// when the panel is opened after the in-memory event window has expired.

import { useEffect, useRef, useState } from "react";
import {
  connectRunEvents,
  type RunProgressCallbacks,
} from "../../api";
import type { BottomPanelContext } from "../registry/bottomPanelRegistry";

interface LogEntry {
  ts: string;
  kind:
    | "step_start"
    | "step_complete"
    | "step_blocked"
    | "terminal"
    | "info";
  step?: string;
  message: string;
}

export function LogsPanel({ runId, projectRoot }: BottomPanelContext) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [closed, setClosed] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!projectRoot) {
      setEntries([
        {
          ts: new Date().toISOString(),
          kind: "info",
          message: "No project_root — logs subscription skipped.",
        },
      ]);
      return undefined;
    }
    if (typeof EventSource === "undefined") {
      setEntries([
        {
          ts: new Date().toISOString(),
          kind: "info",
          message: "Live logs need EventSource (browser only).",
        },
      ]);
      return undefined;
    }
    const append = (entry: LogEntry) =>
      setEntries((prev) => [...prev, entry]);
    const callbacks: RunProgressCallbacks = {
      onStepStart: (step, msg) =>
        append({
          ts: new Date().toISOString(),
          kind: "step_start",
          step,
          message: msg,
        }),
      onStepComplete: (step, msg) =>
        append({
          ts: new Date().toISOString(),
          kind: "step_complete",
          step,
          message: msg,
        }),
      onStepBlocked: (step, msg) =>
        append({
          ts: new Date().toISOString(),
          kind: "step_blocked",
          step,
          message: msg,
        }),
      onTerminal: (status, msg) => {
        append({
          ts: new Date().toISOString(),
          kind: "terminal",
          message: `${status}: ${msg}`,
        });
        setClosed(true);
      },
      onError: () => setClosed(true),
    };
    const close = connectRunEvents(projectRoot, runId, callbacks);
    return () => {
      close();
    };
  }, [projectRoot, runId]);

  // Auto-scroll to the bottom when new entries arrive.
  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  return (
    <div
      ref={containerRef}
      data-testid="bottom-panel-logs"
      style={{
        flex: 1,
        overflow: "auto",
        padding: "8px 12px",
        fontFamily: "var(--font-mono, monospace)",
        fontSize: 12,
        color: "var(--label-secondary)",
      }}
    >
      {entries.length === 0 && !closed && (
        <div style={{ color: "var(--label-tertiary)" }}>
          Waiting for events…
        </div>
      )}
      {entries.map((e, i) => (
        <div
          key={i}
          data-testid={`log-entry-${e.kind}`}
          style={{
            display: "flex",
            gap: 8,
            padding: "2px 0",
            color:
              e.kind === "terminal"
                ? "var(--label)"
                : e.kind === "step_blocked"
                  ? "var(--review, #ff9f0a)"
                  : "var(--label-secondary)",
          }}
        >
          <span style={{ color: "var(--label-tertiary)" }}>
            {e.ts.slice(11, 19)}
          </span>
          <span style={{ minWidth: 110, color: "var(--label-tertiary)" }}>
            {e.kind}
          </span>
          {e.step && (
            <span style={{ minWidth: 90, color: "var(--tint, #0a84ff)" }}>
              {e.step}
            </span>
          )}
          <span style={{ flex: 1 }}>{e.message}</span>
        </div>
      ))}
      {closed && entries.length > 0 && (
        <div
          style={{
            marginTop: 8,
            color: "var(--label-tertiary)",
            fontStyle: "italic",
          }}
        >
          Stream closed.
        </div>
      )}
    </div>
  );
}
