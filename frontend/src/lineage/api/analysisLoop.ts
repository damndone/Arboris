import { apiUrl, readResponse } from "../../api";
import type { ResponseOf, Schema } from "../../apiTypes";

export type AnalysisLoopRunFacts = Schema<"AnalysisLoopRunFacts">;
export type AnalysisLoopPacketBundle = Schema<"AnalysisLoopPacketBundle">;
export type AnalysisLoopPacketsResponse = ResponseOf<"/analysis-loop/packets/{run_id}", "get">;

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
