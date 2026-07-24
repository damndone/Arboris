import { apiUrl, readResponse } from "../api";

export type StatisticalExplorationOperation =
  | "summarize"
  | "summarize_detail"
  | "misstable"
  | "corr"
  | "derive_boolean"
  | "scatter";

export type StatisticalFilterOperator = "eq" | "neq" | "lt" | "lte" | "gt" | "gte" | "in" | "not_in";

export interface StatisticalFilter {
  column: string;
  operator: StatisticalFilterOperator;
  value: unknown;
}

export interface StatisticalExplorationRequest {
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  operation: StatisticalExplorationOperation;
  selected_columns: string[];
  filters: StatisticalFilter[];
  options?: Record<string, unknown>;
  derived_definitions?: Array<Record<string, unknown>>;
}

export interface StatisticalExplorationResult {
  schema_version?: string;
  operation?: StatisticalExplorationOperation;
  source_row_count?: number;
  filtered_row_count?: number;
  missing_policy?: string;
  variables?: Record<string, unknown> | string[];
  groups?: Array<Record<string, unknown>>;
  correlation_n?: number;
  matrix?: unknown[][];
  [key: string]: unknown;
}

export interface StatisticalExplorationPreview {
  status: "ready" | "blocked";
  fingerprint: string;
  source_sha256: string;
  source_artifact_id: string;
  result: StatisticalExplorationResult;
}

export interface StatisticalExplorationPreviewResponse {
  spec: Record<string, unknown>;
  preview: StatisticalExplorationPreview;
}

export interface StatisticalExplorationConfirmResponse {
  status: string;
  exploration: {
    artifact_id: string;
    path?: string;
    transcript_artifact_id?: string;
    transcript_path?: string;
    fingerprint?: string;
    source_sha256?: string;
  };
  result?: StatisticalExplorationResult;
}

function projectQuery(projectRoot: string): string {
  const params = new URLSearchParams({ project_root: projectRoot });
  return `?${params.toString()}`;
}

export async function previewStatisticalExploration(
  projectRoot: string,
  request: StatisticalExplorationRequest,
): Promise<StatisticalExplorationPreviewResponse> {
  const response = await fetch(apiUrl(`/statistical-explorations/preview${projectQuery(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return readResponse<StatisticalExplorationPreviewResponse>(response);
}

export async function confirmStatisticalExploration(
  projectRoot: string,
  request: StatisticalExplorationRequest & { preview_fingerprint: string },
): Promise<StatisticalExplorationConfirmResponse> {
  const response = await fetch(apiUrl(`/statistical-explorations/confirm${projectQuery(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return readResponse<StatisticalExplorationConfirmResponse>(response);
}
