import { apiUrl, readResponse } from "../../api";

export type AnalysisLoopRunFacts = {
  run_id: string;
  status: string | null;
  model: string | null;
  contract_version: string | null;
  covariance: string | null;
  covariance_product?: string | null;
  covariance_wire: string | null;
  entity_col: string | null;
  stable_result_ids: string[];
  primary_estimand: Record<string, unknown> | null;
  analysis_sample: {
    row_count?: number | null;
    row_order?: string[];
  } | null;
  fingerprints: Record<string, unknown>;
};

export type AnalysisLoopPacketBundle = {
  child_run_id: string;
  source_run_id: string;
  plan_diff: Record<string, unknown> | null;
  validation_packet: Record<string, unknown>;
  compare_packet: Record<string, unknown> | null;
};

export type AnalysisLoopPacketsResponse = {
  status: "absent" | "pending" | "complete" | "blocked" | "failed" | string;
  run: AnalysisLoopRunFacts;
  source_run: AnalysisLoopRunFacts | { run_id: string; status: string };
  packet: AnalysisLoopPacketBundle | null;
  children: AnalysisLoopPacketBundle[];
};

export function fetchAnalysisLoopPackets(
  projectRoot: string,
  runId: string,
): Promise<AnalysisLoopPacketsResponse> {
  const query = new URLSearchParams({ project_root: projectRoot });
  return request<AnalysisLoopPacketsResponse>(
    apiUrl(`/analysis-loop/packets/${encodeURIComponent(runId)}?${query.toString()}`),
  );
}

async function request<T>(url: string): Promise<T> {
  const response = await fetch(url);
  return readResponse<T>(response);
}
