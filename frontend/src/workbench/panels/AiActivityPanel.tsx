// v1.6.12 T2 (V3) — AI activity panel: read-only timeline of every AI
// interaction in this project (Ask AI Q&A + report generations), fed by the
// typed AiActivityRecord log. v1.7 operation records are projected alongside
// this compatibility log without making the panel an additional fact source.
import { useEffect, useState } from "react";
import {
  AI_ACTIVITY_EVENT,
  loadAiActivity,
  type AiActivityRecord,
} from "../../aiActivity/aiActivityLog";
import { renderMarkdown } from "../../report/markdown";
import { useAgentNavigationOptional } from "../agent/agentNavigation";
import { getAgentActivity } from "../agent/agentApi";
import { AgentHierarchyTree } from "../agent/AgentHierarchyTree";
import type {
  AgentActivityItem,
  AgentActivityEventItem,
  AgentHierarchyNode,
  AgentNavigationRef,
} from "../agent/agentTypes";
import type { BottomPanelContext } from "../registry/bottomPanelRegistry";

export function AiActivityPanel({ projectRoot }: BottomPanelContext) {
  const [records, setRecords] = useState<AiActivityRecord[]>(() =>
    loadAiActivity(projectRoot),
  );
  const [operationRecords, setOperationRecords] = useState<AgentActivityItem[]>([]);
  const [eventRecords, setEventRecords] = useState<AgentActivityEventItem[]>([]);
  const [activityHierarchy, setActivityHierarchy] = useState<AgentHierarchyNode | null>(null);
  const navigation = useAgentNavigationOptional();

  useEffect(() => {
    const refresh = () => {
      setRecords((current) => {
        const next = loadAiActivity(projectRoot);
        return JSON.stringify(current) === JSON.stringify(next) ? current : next;
      });
    };
    refresh();
    window.addEventListener(AI_ACTIVITY_EVENT, refresh);
    return () => window.removeEventListener(AI_ACTIVITY_EVENT, refresh);
  }, [projectRoot]);

  useEffect(() => {
    let active = true;
    getAgentActivity(projectRoot)
      .then((response) => {
        if (active) {
          setOperationRecords((current) => (
            response.activities.length === 0 && current.length === 0
              ? current
              : response.activities
          ));
          setEventRecords((current) => (
            (response.events ?? []).length === 0 && current.length === 0
              ? current
              : (response.events ?? [])
          ));
          setActivityHierarchy(response.hierarchy ?? null);
        }
      })
      .catch(() => {
        if (active) {
          setOperationRecords((current) => (current.length === 0 ? current : []));
          setEventRecords((current) => (current.length === 0 ? current : []));
          setActivityHierarchy(null);
        }
      });
    return () => {
      active = false;
    };
  }, [projectRoot]);

  const items: Array<AiActivityRecord | AgentActivityItem | AgentActivityEventItem> = [
    ...records,
    ...operationRecords,
    ...eventRecords,
  ].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

  if (items.length === 0 && !activityHierarchy) {
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
      {activityHierarchy && (
        <div data-testid="ai-activity-hierarchy">
          <AgentHierarchyTree
            root={activityHierarchy}
            openNavigation={navigation ?? undefined}
          />
        </div>
      )}
      {items.map((record) => (
        <ActivityRow
          key={
            record.kind === "operation" || record.kind === "event"
              ? record.activity_id
              : record.id
          }
          record={record}
          openNavigation={navigation}
        />
      ))}
    </div>
  );
}

function ActivityRow({
  record,
  openNavigation,
}: {
  record: AiActivityRecord | AgentActivityItem | AgentActivityEventItem;
  openNavigation: ((ref: AgentNavigationRef) => boolean) | null;
}) {
  const stamp = new Date(record.at).toLocaleString();
  if (record.kind === "operation") {
    return <OperationActivityRow record={record} stamp={stamp} openNavigation={openNavigation} />;
  }
  if (record.kind === "event") {
    return <EventActivityRow record={record} stamp={stamp} openNavigation={openNavigation} />;
  }
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

function EventActivityRow({
  record,
  stamp,
  openNavigation,
}: {
  record: AgentActivityEventItem;
  stamp: string;
  openNavigation: ((ref: AgentNavigationRef) => boolean) | null;
}) {
  const detailEntries = Object.entries(record.details).filter(
    ([key]) => key !== "record_id" && key !== "proposal_id",
  );
  return (
    <div
      data-testid="ai-activity-event"
      style={{ border: "1px solid var(--separator)", borderRadius: 6, padding: "6px 10px" }}
    >
      <div style={{ color: "var(--label-tertiary)", fontSize: 10.5 }}>
        #{record.seq} · {stamp} · {record.session.label} · {record.event_type}
      </div>
      <div style={{ marginTop: 3, fontWeight: 600 }}>
        Main · {record.main.label} · Chain {record.chain.id}
      </div>
      {detailEntries.length > 0 && (
        <div style={{ marginTop: 3, color: "var(--label-secondary)" }}>
          {detailEntries.map(([key, value]) => (
            <span key={key} style={{ marginRight: 8 }}>
              {key}: {typeof value === "object" ? JSON.stringify(value) : String(value)}
            </span>
          ))}
        </div>
      )}
      {record.links.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 5 }}>
          {record.links.map((link) => (
            <NavigationButton
              key={`${link.kind}:${link.id}:${link.relation}`}
              navigationRef={link}
              openNavigation={openNavigation}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function OperationActivityRow({
  record,
  stamp,
  openNavigation,
}: {
  record: AgentActivityItem;
  stamp: string;
  openNavigation: ((ref: AgentNavigationRef) => boolean) | null;
}) {
  const changed = record.diff_ref?.changed_fields ?? record.diff_ref?.changed;
  const changedFields = Array.isArray(changed)
    ? changed.filter((value): value is string => typeof value === "string")
    : [];
  const verified = record.verification.passed === true;
  const navigationLinks = record.links.filter((link) => link.kind !== "diff");

  return (
    <div
      data-testid="ai-activity-operation"
      style={{ border: "1px solid var(--separator)", borderRadius: 6, padding: "6px 10px" }}
    >
      <div style={{ color: "var(--label-tertiary)", fontSize: 10.5 }}>
        {stamp} · Main · {record.main.label} · Chain {record.chain.id}
      </div>
      <div style={{ marginTop: 3, fontWeight: 600 }}>
        <NavigationButton navigationRef={record.operation} openNavigation={openNavigation} />
        {" · "}
        <span style={{ color: verified ? "var(--success, #1a7f37)" : "var(--danger, #b00020)" }}>
          {verified ? "verified" : "verification failed"}
        </span>
      </div>
      {(record.effect_status || record.projection_status) && (
        <div style={{ marginTop: 3, color: "var(--label-secondary)" }}>
          {record.effect_status ? `effect ${record.effect_status}` : "effect status unavailable"}
          {" · "}
          {record.projection_status
            ? `projection ${record.projection_status}`
            : "projection status unavailable"}
        </div>
      )}
      <div style={{ marginTop: 3, color: "var(--label-secondary)" }}>
        {record.diff_ref?.kind ? `Diff · ${String(record.diff_ref.kind)}` : "Diff · unavailable"}
        {changedFields.length > 0 ? ` · changed: ${changedFields.join(", ")}` : ""}
      </div>
      {(record.diff || navigationLinks.length > 0) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 5 }}>
          {record.diff && (
            <NavigationButton
              key={`diff:${record.diff.id}`}
              navigationRef={record.diff}
              openNavigation={openNavigation}
            />
          )}
          {navigationLinks.map((link) => (
            <NavigationButton
              key={`${link.kind}:${link.id}:${link.relation}`}
              navigationRef={link}
              openNavigation={openNavigation}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function NavigationButton({
  navigationRef,
  openNavigation,
}: {
  navigationRef: AgentNavigationRef;
  openNavigation: ((ref: AgentNavigationRef) => boolean) | null;
}) {
  return (
    <button
      type="button"
      disabled={!navigationRef.available || openNavigation === null}
      aria-label={`Open ${navigationRef.label}`}
      onClick={() => {
        if (navigationRef.available) openNavigation?.(navigationRef);
      }}
      style={{
        border: 0,
        padding: 0,
        background: "transparent",
        color: "var(--tint, #0a84ff)",
        cursor: navigationRef.available && openNavigation ? "pointer" : "default",
        font: "inherit",
        textAlign: "left",
      }}
    >
      {navigationRef.label}
    </button>
  );
}
