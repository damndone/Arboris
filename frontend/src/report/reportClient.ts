// v1.6.11 slice C — /llm/chat client for cite-chip report generation.
import { apiUrl } from "../api";
import type { CitableFact, FigureFactInput, ReportScope } from "./factTable";

export interface ReportResponse {
  text: string;
  model?: string;
  context_fingerprint?: string | null;
}

export type ReportFigure = FigureFactInput & { path?: string };

export const DEFAULT_REPORT_INSTRUCTION =
  "为这条 lineage 写一份实证分析报告(数据/方法/结果/局限)。";

export async function generateReport(input: {
  facts: CitableFact[];
  scope: ReportScope;
  fingerprints: string[];
  figures?: ReportFigure[];
  instruction?: string;
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
    throw new Error(await extractErrorMessage(response));
  }
  return response.json() as Promise<ReportResponse>;
}

export async function exportReport(input: {
  projectRoot: string;
  runId: string;
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
      body: JSON.stringify({ markdown: input.markdown, figures: input.figures }),
    },
  );
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.blob();
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

async function extractErrorMessage(response: Response): Promise<string> {
  const fallback = `Report generation failed (${response.status})`;
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
