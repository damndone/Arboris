// v1.6.11 slice C — /llm/chat client for cite-chip report generation.
import { apiUrl } from "../api";
import type { CitableFact, ReportScope } from "./factTable";

export interface ReportResponse {
  text: string;
  model?: string;
  context_fingerprint?: string | null;
}

export const DEFAULT_REPORT_INSTRUCTION =
  "为这条 lineage 写一份实证分析报告(数据/方法/结果/局限)。";

export async function generateReport(input: {
  facts: CitableFact[];
  scope: ReportScope;
  fingerprints: string[];
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

async function extractErrorMessage(response: Response): Promise<string> {
  const fallback = `Report generation failed (${response.status})`;
  try {
    const body: unknown = await response.json();
    const message = (body as { error?: { message?: unknown } }).error?.message;
    return typeof message === "string" && message.trim() !== "" ? message : fallback;
  } catch {
    return fallback;
  }
}
