// v1.6.11 slice C — /llm/chat client for cite-chip report generation.
import { apiUrl } from "../api";
import type { CitableFact, FigureFactInput, ReportScope } from "./factTable";
import type { ReportCapabilityManifestEntry } from "./reportEvidence";

export interface ReportQualitySummary {
  status: "exportable" | "needs_revision" | "insufficient_evidence";
  violations?: Array<{ code: string; message: string; subject?: string } | string>;
  missing_sections?: string[];
  missing_capabilities?: string[];
  missing_evidence?: string[];
  missing_abstract_elements?: string[];
  unavailable_capabilities?: string[];
  results_subsection_count?: number;
  figure_counts?: Record<string, number>;
}

export interface ReportGenerationErrorDetails {
  retry_attempted?: boolean;
  retry_count?: number;
  violations?: Array<{ code: string; message: string; subject?: string } | string>;
  report_quality?: ReportQualitySummary;
  [key: string]: unknown;
}

export class ReportGenerationError extends Error {
  readonly code: string;
  readonly details?: ReportGenerationErrorDetails;

  constructor(code: string, message: string, details?: ReportGenerationErrorDetails) {
    super(formatReportGenerationError(code, message, details));
    this.name = "ReportGenerationError";
    this.code = code;
    this.details = details;
    Object.setPrototypeOf(this, ReportGenerationError.prototype);
  }
}

export interface ReportResponse {
  text: string;
  model?: string;
  context_fingerprint?: string | null;
  report_quality?: ReportQualitySummary;
}

export interface PersistedReportMetadata {
  fact_snapshot_hash?: string;
  artifact_ids?: string[];
  validation_status?: ReportQualitySummary["status"];
}

export interface SaveReportResponse {
  schema_version?: string;
  record?: PersistedReportMetadata;
}

export type ReportFigure = FigureFactInput & { path?: string };

export const DEFAULT_REPORT_INSTRUCTION =
  "Write an evidence-grounded report about the current analysis.";

export const REPORT_PROMPT_PLACEHOLDER =
  "Tell the agent what you want to explore or change…";

export async function generateReport(input: {
  facts: CitableFact[];
  scope: ReportScope;
  fingerprints: string[];
  figures?: ReportFigure[];
  instruction?: string;
  reportStandard?: "journal_full_v1";
  requiredCapabilities?: string[];
  capabilityManifest?: ReportCapabilityManifestEntry[];
  excludedFactIds?: string[];
}): Promise<ReportResponse> {
  const response = await fetch(apiUrl("/llm/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "workbench_report_v1",
      question: input.instruction?.trim() || DEFAULT_REPORT_INSTRUCTION,
      packet: {
        packet_version: "workbench-report/v1",
        report_scope: input.scope,
        fact_table: input.facts,
        context_fingerprints: input.fingerprints,
        figures: input.figures ?? [],
        report_standard: input.reportStandard,
        required_capabilities: input.requiredCapabilities ?? [],
        capability_manifest: input.capabilityManifest ?? [],
        excluded_fact_ids: input.excludedFactIds ?? [],
      },
      response_guardrails: {
        advisory_text_only: true,
        executable_actions_allowed: false,
        citations_required: true,
        cite_marker_format: "[[c:ID]]",
      },
    }),
  });
  if (!response.ok) {
    throw await extractErrorMessage(response);
  }
  return response.json() as Promise<ReportResponse>;
}

export async function exportReport(input: {
  projectRoot: string;
  runId: string;
  reportId?: string;
  format: "html" | "docx" | "tex" | "pdf-print";
  markdown: string;
  figures: ReportFigure[];
}): Promise<Blob> {
  const response = await fetch(
    apiUrl(
      `/runs/${encodeURIComponent(input.runId)}/report/export?project_root=${encodeURIComponent(input.projectRoot)}&format=${encodeURIComponent(input.format)}`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: input.markdown, figures: input.figures, report_id: input.reportId }),
    },
  );
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.blob();
}

export type ResultTableSection =
  | "coefficients"
  | "regression_table"
  | "table_1"
  | "statistical_evidence"
  | "model_family_evidence";

export async function exportResultTable(input: {
  projectRoot: string;
  runId: string;
  sections?: ResultTableSection[];
}): Promise<Blob> {
  const response = await fetch(
    apiUrl(
      `/runs/${encodeURIComponent(input.runId)}/report/result-table-export?project_root=${encodeURIComponent(input.projectRoot)}`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sections: input.sections ?? [] }),
    },
  );
  if (!response.ok) throw new Error(await extractError(response));
  return response.blob();
}

export async function saveAiReport(input: {
  projectRoot: string;
  runId: string;
  record: object;
}): Promise<SaveReportResponse> {
  const response = await fetch(
    apiUrl(`/runs/${encodeURIComponent(input.runId)}/ai-reports?project_root=${encodeURIComponent(input.projectRoot)}`),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input.record) },
  );
  if (!response.ok) throw new Error(await extractError(response));
  const body: unknown = await response.json();
  if (!body || typeof body !== "object" || Array.isArray(body)) return {};
  const record = (body as { record?: unknown }).record;
  return {
    schema_version: typeof (body as { schema_version?: unknown }).schema_version === "string"
      ? (body as { schema_version: string }).schema_version
      : undefined,
    record: record && typeof record === "object" && !Array.isArray(record)
      ? record as PersistedReportMetadata
      : undefined,
  };
}

export async function fetchAiReports(input: {
  projectRoot: string;
  runId: string;
}): Promise<Array<Record<string, unknown>>> {
  const response = await fetch(
    apiUrl(`/runs/${encodeURIComponent(input.runId)}/ai-reports?project_root=${encodeURIComponent(input.projectRoot)}`),
  );
  if (!response.ok) throw new Error(await extractError(response));
  const body = await response.json() as { reports?: unknown };
  return Array.isArray(body.reports) ? body.reports.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
}

async function extractError(response: Response): Promise<string> {
  const fallback = `Request failed (${response.status})`;
  try {
    const body: unknown = await response.json();
    const error = (body as { error?: { code?: unknown; message?: unknown } }).error;
    const message = error?.message;
    if (typeof message !== "string" || message.trim() === "") return fallback;
    return typeof error?.code === "string" && error.code.trim() !== ""
      ? `${error.code}: ${message}`
      : message;
  } catch {
    return fallback;
  }
}

async function extractErrorMessage(response: Response): Promise<ReportGenerationError> {
  const fallback = `Report generation failed (${response.status})`;
  try {
    const body: unknown = await response.json();
    const error = (body as {
      error?: { code?: unknown; message?: unknown; details?: unknown };
    }).error;
    const message = error?.message;
    const code = typeof error?.code === "string" && error.code.trim() !== ""
      ? error.code
      : "LLM_REPORT_GENERATION_FAILED";
    const details = isReportErrorDetails(error?.details) ? error.details : undefined;
    return new ReportGenerationError(
      code,
      typeof message === "string" && message.trim() !== "" ? message : fallback,
      details,
    );
  } catch {
    return new ReportGenerationError("LLM_REPORT_GENERATION_FAILED", fallback);
  }
}

function isReportErrorDetails(value: unknown): value is ReportGenerationErrorDetails {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function formatReportGenerationError(
  code: string,
  message: string,
  details?: ReportGenerationErrorDetails,
): string {
  const lines = [`${code}: ${message}`];
  if (details?.retry_count && details.retry_count > 0) {
    lines.push(`Workbench made ${details.retry_count} corrective attempt${details.retry_count === 1 ? "" : "s"}.`);
  } else if (details?.retry_attempted) {
    lines.push("Workbench retried the report once.");
  }
  const violations = details?.violations ?? details?.report_quality?.violations ?? [];
  for (const violation of violations) {
    const violationMessage = typeof violation === "string" ? violation : violation?.message;
    if (typeof violationMessage === "string" && violationMessage.trim() !== "") {
      lines.push(`Report issue: ${violationMessage}`);
    }
  }
  const quality = details?.report_quality;
  if (quality?.missing_sections?.length) {
    lines.push(`Missing sections: ${quality.missing_sections.join(", ")}`);
  }
  if (quality?.missing_capabilities?.length) {
    lines.push(`Missing evidence modules: ${quality.missing_capabilities.join(", ")}`);
  }
  if (quality?.missing_evidence?.length) {
    lines.push(`Missing evidence: ${quality.missing_evidence.join(", ")}`);
  }
  return lines.join("\n");
}
