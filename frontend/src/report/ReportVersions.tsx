// Every saved version of this run's report, whoever wrote it: the person by
// hand, the Agent, the report writer, or a workflow. Versions are never edited;
// going back to one saves it again as the newest.

import { useCallback, useEffect, useMemo, useState } from "react";
import { artifactDownloadUrl, fetchRunArtifacts } from "../api";
import { reportHistory, saveReport, type Report } from "../manual/manualApi";
import { ReportReadingView } from "../manual/ReportEvidence";
import { agentTurnActive } from "../workbench/agent/AgentRunControls";
import { useAgentSurfaceOptional } from "../workbench/agent/AgentSurfaceContext";
import type { ReportRecord } from "./reportHistory";

export type ReportVersion =
  | { key: string; kind: "written"; at: string; author: string; record: Report }
  | { key: string; kind: "generated"; at: string; author: string; record: ReportRecord }
  | { key: string; kind: "workflow"; at: string; author: string; artifactId: string };

const WORKFLOW_REPORT = /^workflow_report_.*_html$/;
const time = (at: string) => {
  const parsed = new Date(at);
  return Number.isNaN(parsed.getTime()) ? at : parsed.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

/** Newest first. A version's number follows the order versions were made in. */
export function useReportVersions(projectRoot: string | undefined, runId: string | null, generated: ReportRecord[]) {
  const [written, setWritten] = useState<Report[]>([]);
  const [workflow, setWorkflow] = useState<string[]>([]);
  const agent = useAgentSurfaceOptional();
  const agentBusy = agent ? agentTurnActive(agent) : false;
  const refresh = useCallback(async () => {
    if (!projectRoot || !runId) {
      setWritten([]);
      setWorkflow([]);
      return;
    }
    const [history, artifacts] = await Promise.allSettled([reportHistory(projectRoot, runId), fetchRunArtifacts(projectRoot, runId)]);
    setWritten(history.status === "fulfilled" ? history.value.reports : []);
    setWorkflow(artifacts.status === "fulfilled"
      ? artifacts.value.groups.flatMap((group) => group.items).map((item) => item.artifact_id).filter((id) => WORKFLOW_REPORT.test(id))
      : []);
  }, [projectRoot, runId]);
  // The Agent saves versions from its own turn: look again when one ends.
  useEffect(() => { void refresh().catch(() => undefined); }, [refresh, agentBusy]);
  const versions = useMemo<ReportVersion[]>(() => [
    ...workflow.map((artifactId): ReportVersion => ({ key: `workflow:${artifactId}`, kind: "workflow", at: "", author: "Workflow", artifactId })),
    ...generated.map((record): ReportVersion => ({ key: `generated:${record.id}`, kind: "generated", at: record.generatedAt, author: record.model ?? "Report writer", record })),
    ...written.map((record): ReportVersion => ({ key: `written:${record.id}`, kind: "written", at: record.created_at, author: record.author === "agent" ? "Agent" : "You", record })),
  ].sort((a, b) => a.at.localeCompare(b.at)).reverse(), [generated, workflow, written]);
  return { versions, refresh };
}

export function versionLabel(version: ReportVersion, number: number): string {
  return [`Version ${number}`, version.author, version.at && time(version.at)].filter(Boolean).join(" · ");
}

export function ReportVersionPicker({ versions, selected, onSelect }: { versions: ReportVersion[]; selected: string; onSelect: (key: string) => void }) {
  return (
    <select className="report-versions" aria-label="Report version" value={selected} onChange={(event) => onSelect(event.target.value)}>
      {versions.map((version, index) => (
        <option key={version.key} value={version.key}>{versionLabel(version, versions.length - index)}</option>
      ))}
    </select>
  );
}

/** A saved version that is not the report writer's: read as it was saved. */
export function SavedVersionBody({ version, projectRoot, runId }: { version: Exclude<ReportVersion, { kind: "generated" }>; projectRoot: string; runId: string }) {
  const [page, setPage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const url = version.kind === "workflow" ? artifactDownloadUrl(projectRoot, runId, version.artifactId) : null;
  useEffect(() => {
    if (!url) return undefined;
    const request = new AbortController();
    setPage(null);
    setFailed(false);
    fetch(url, { signal: request.signal })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(String(response.status)))))
      .then(setPage)
      .catch(() => { if (!request.signal.aborted) setFailed(true); });
    return () => request.abort();
  }, [url]);
  if (version.kind === "written") {
    return (
      <div data-testid="report-body" className="report-review-panel__body">
        <h3>{version.record.title}</h3>
        <ReportReadingView text={version.record.text} facts={version.record.facts} />
      </div>
    );
  }
  if (failed) return <p className="report-review-panel__note" role="alert">This report could not be loaded.</p>;
  return page === null
    ? <p className="report-review-panel__note">Loading…</p>
    : <iframe className="report-review-panel__page" srcDoc={page} sandbox="" title="Workflow report" />;
}

/** The newest saved prose becomes a new version with the same words and evidence. */
export async function restoreWritten(projectRoot: string, runId: string, version: Report, newest: Report | null): Promise<void> {
  await saveReport(projectRoot, runId, {
    id: `mrpt_${crypto.randomUUID()}`,
    source_fingerprint: version.source_fingerprint,
    title: version.title,
    text: version.text,
    fact_ids: version.facts.map((fact) => fact.id),
    figure_ids: version.figures.map((figure) => figure.artifact_id),
    parent_report_id: newest && newest.document_id === version.document_id ? newest.id : null,
  });
}
