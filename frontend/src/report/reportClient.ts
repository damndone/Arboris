// v1.6.11 slice C — /llm/chat client for cite-chip report generation.
import { apiUrl } from "../api";
import type { ResponseOf } from "../apiTypes";
import type { CitableFact, FigureFactInput, ReportScope } from "./factTable";
import type { ReportCapabilityManifestEntry } from "./reportEvidence";

/** Report quality as reports and error details carry it, including those
 * stored by earlier versions (hence every field but the status is optional). */
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

export type ReportResponse = ResponseOf<"/llm/chat", "post">;

type SavedReport = ResponseOf<"/runs/{run_id}/ai-reports", "post">;

/** The server-derived audit fields of a saved report; never accepted as edit input. */
export type ReportAudit = Pick<SavedReport["record"], "fact_snapshot_hash" | "artifact_ids" | "validation_status">;

export type ReportFigure = FigureFactInput & { path?: string };

export const DEFAULT_REPORT_INSTRUCTION =
  "Write an evidence-grounded report about the current analysis.";

export const REPORT_PROMPT_PLACEHOLDER =
  "Tell the agent what you want to explore or change…";

// The server owns a 300-second whole-request deadline. The client watchdog is
// deliberately later so the typed server error wins unless the network or
// reverse proxy itself stops making progress.
export const REPORT_CLIENT_TIMEOUT_MS = 315_000;

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
  clientTimeoutMs?: number;
}): Promise<ReportResponse> {
  const timeoutMs = input.clientTimeoutMs ?? REPORT_CLIENT_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new ReportGenerationError(
      "LLM_REPORT_CLIENT_TIMEOUT_INVALID",
      "Report client timeout must be a positive finite duration.",
    );
  }
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(apiUrl("/llm/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
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
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ReportGenerationError(
        "LLM_REPORT_CLIENT_TIMEOUT",
        "Report generation exceeded the client network watchdog.",
        { timeout_ms: timeoutMs },
      );
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
  }
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
}): Promise<ReportAudit> {
  const response = await fetch(
    apiUrl(`/runs/${encodeURIComponent(input.runId)}/ai-reports?project_root=${encodeURIComponent(input.projectRoot)}`),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input.record) },
  );
  if (!response.ok) throw new Error(await extractError(response));
  const { record } = (await response.json()) as SavedReport;
  return {
    fact_snapshot_hash: record.fact_snapshot_hash,
    artifact_ids: record.artifact_ids,
    validation_status: record.validation_status,
  };
}

export async function fetchAiReports(input: {
  projectRoot: string;
  runId: string;
}): Promise<ResponseOf<"/runs/{run_id}/ai-reports", "get">["reports"]> {
  const response = await fetch(
    apiUrl(`/runs/${encodeURIComponent(input.runId)}/ai-reports?project_root=${encodeURIComponent(input.projectRoot)}`),
  );
  if (!response.ok) throw new Error(await extractError(response));
  const body = (await response.json()) as ResponseOf<"/runs/{run_id}/ai-reports", "get">;
  return body.reports;
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
