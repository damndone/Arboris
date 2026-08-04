// v1.6.11 slice C-3 — report history (localStorage, per project).
//
// Every generated report persists as a typed record: instruction, output,
// model, AND the full fact-table snapshot including user-excluded facts.
// Integrity by construction: the UI lets users OMIT facts, never edit values,
// and each record keeps what was excluded — a curated report is auditable
// against the facts its author chose to leave out.
import type { CitableFact, ReportScope } from "./factTable";
import type { ReportFigure, ReportQualitySummary } from "./reportClient";
import type { ReportCapabilityManifestEntry } from "./reportEvidence";
import type { ReportRevision } from "./reportDocument";

export interface ReportRecord {
  id: string;
  generatedAt: string;
  model?: string;
  instruction: string;
  text: string;
  scope: ReportScope;
  /** Context fingerprints used to detect a stale revision after lineage changes. */
  context_fingerprints?: string[];
  /** Full snapshot — includes facts the user excluded before generation. */
  facts: CitableFact[];
  /** Fact ids the user excluded; disclosed in the UI, kept for audit. */
  excluded_fact_ids: string[];
  /** Figure metadata used by [[fig:artifact_id]] markers in the report. */
  figures?: ReportFigure[];
  /** Figure ids omitted from the sent writer packet; full figures remain above. */
  excluded_figure_ids?: string[];
  /** Original generated prose, retained so an edit can reset without touching evidence. */
  generatedText?: string;
  report_standard?: "journal_full_v1";
  required_capabilities?: string[];
  capability_manifest?: ReportCapabilityManifestEntry[];
  report_quality?: ReportQualitySummary;
  /** Server-derived audit metadata; never accepted as an edit input. */
  fact_snapshot_hash?: string;
  artifact_ids?: string[];
  validation_status?: ReportQualitySummary["status"];
  /** Optional versioned prose revision; source Run/Artifact evidence stays immutable. */
  revision?: ReportRevision;
}

const MAX_RECORDS = 20;

function storageKey(projectRoot: string): string {
  return `workbench:report-history:${projectRoot}`;
}

export function loadReportHistory(projectRoot: string): ReportRecord[] {
  try {
    const raw = window.localStorage.getItem(storageKey(projectRoot));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ReportRecord[]) : [];
  } catch {
    return [];
  }
}

export function saveReportRecord(
  projectRoot: string,
  record: ReportRecord,
): ReportRecord[] {
  const next = [record, ...loadReportHistory(projectRoot)].slice(0, MAX_RECORDS);
  persist(projectRoot, next);
  return next;
}

export function deleteReportRecord(
  projectRoot: string,
  recordId: string,
): ReportRecord[] {
  const next = loadReportHistory(projectRoot).filter((r) => r.id !== recordId);
  persist(projectRoot, next);
  return next;
}

function persist(projectRoot: string, records: ReportRecord[]): void {
  try {
    window.localStorage.setItem(storageKey(projectRoot), JSON.stringify(records));
  } catch {
    /* quota/private-mode — history is best-effort, generation still works */
  }
}

export function makeRecordId(): string {
  return `rpt_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}
