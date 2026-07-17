import { apiUrl, readResponse } from "../api";

export type DataColumnCastTarget = "numeric" | "string" | "datetime";

export interface DataColumnCastRequest {
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  column: string;
  target_dtype: DataColumnCastTarget;
}

export interface DataColumnCastContext {
  operation_id: "data.column.cast";
  operation_version: "v1";
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  source_artifact_path: string;
  source_sha256: string;
  row_count: number;
  columns: Array<{ name: string; dtype: string }>;
  downstream_invalidation: string[];
}

export interface DataColumnCastPreview {
  operation_id: "data.column.cast";
  operation_version: "v1";
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  column: string;
  target_dtype: DataColumnCastTarget;
  source_sha256: string;
  row_count: number;
  before_dtype: string;
  after_dtype: string;
  success_count: number;
  failure_count: number;
  failure_examples: string[];
  new_missing_count: number;
  schema_fingerprint_before: string;
  schema_fingerprint_after: string;
  fingerprint: string;
  downstream_invalidation: string[];
  status: "ready" | "blocked";
}

export interface DataColumnsCastItem {
  column: string;
  target_dtype: DataColumnCastTarget;
}

export type DataCastOutputFormat = "csv" | "xlsx";

export interface DataColumnsCastRequest {
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  casts: DataColumnsCastItem[];
  output_format?: DataCastOutputFormat;
}

export interface DataColumnCastItemResult {
  column: string;
  target_dtype: DataColumnCastTarget;
  before_dtype: string;
  after_dtype: string;
  success_count: number;
  failure_count: number;
  failure_examples: string[];
  new_missing_count: number;
  status: "ready" | "blocked";
}

export interface DataColumnsCastPreview {
  operation_id: "data.columns.cast";
  operation_version: "v1";
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  casts: DataColumnsCastItem[];
  source_sha256: string;
  row_count: number;
  items: DataColumnCastItemResult[];
  schema_fingerprint_before: string;
  schema_fingerprint_after: string;
  fingerprint: string;
  downstream_invalidation: string[];
  status: "ready" | "blocked";
}

export interface DataColumnsCastPreviewResponse {
  spec: DataColumnsCastRequest & {
    operation_id: "data.columns.cast";
    operation_version: "v1";
  };
  preview: DataColumnsCastPreview;
}

export interface DataColumnCastPreviewResponse {
  spec: DataColumnCastRequest & {
    operation_id: "data.column.cast";
    operation_version: "v1";
  };
  preview: DataColumnCastPreview;
}

export interface DataColumnCastConfirmResponse {
  proposal: Record<string, unknown>;
  operation: Record<string, unknown>;
  status: string;
}

/** Typed projection of the durable operation record bound to a cast child node. */
export interface DataColumnCastOperationRecord {
  record_id: string;
  operation_id: string;
  operation_version: string;
  status: string;
  effect_status: string;
  projection_status: string;
  actor_type: string;
  diff_ref: {
    kind: string;
    // data.column.cast
    column?: string;
    before_dtype?: string;
    after_dtype?: string;
    // data.columns.cast
    casts?: Array<{ column: string; before_dtype: string; after_dtype: string }>;
    // code.execute
    columns_added?: string[];
    columns_removed?: string[];
    dtype_changes?: Array<{ column: string; before_dtype: string; after_dtype: string }>;
    row_count_before?: number;
    row_count_after?: number;
    source_fingerprint: string;
    result_fingerprint: string;
  } | null;
  verification: {
    status: string;
    passed: boolean;
    checks: Record<string, unknown>;
  } | null;
  outputs: Record<string, unknown>;
}

export interface CodeExecuteRequest {
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  code: string;
  language?: "python";
  output_format?: DataCastOutputFormat;
}

export interface CodeDtypeChange {
  column: string;
  before_dtype: string;
  after_dtype: string;
}

export interface CodeExecutePreview {
  operation_id: "code.execute";
  operation_version: "v1";
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
  language: "python";
  code: string;
  code_sha256: string;
  output_format: DataCastOutputFormat;
  source_sha256: string;
  row_count_before: number;
  row_count_after: number;
  columns_added: string[];
  columns_removed: string[];
  dtype_changes: CodeDtypeChange[];
  schema_fingerprint_before: string;
  schema_fingerprint_after: string;
  result_fingerprint: string;
  result_preview_rows: Array<Record<string, unknown>>;
  stdout: string;
  fingerprint: string;
  downstream_invalidation: string[];
  status: "ready" | "blocked";
  error: string | null;
}

export interface CodeExecutePreviewResponse {
  spec: CodeExecuteRequest & {
    operation_id: "code.execute";
    operation_version: "v1";
  };
  preview: CodeExecutePreview;
}

export interface CodeExecuteRiskAuthorization {
  authorization_id: string;
  token: string;
  operation_id: "code.execute";
  operation_version: "v1";
  proposal_id: string;
  revision: number;
  fingerprint: string;
  active_head_run_id: string;
  expires_at: string;
  status: "issued";
}

export interface CodeExecuteRiskAuthorizationResponse {
  proposal: Record<string, unknown>;
  risk_authorization: CodeExecuteRiskAuthorization;
  status: "risk_authorized";
}

function projectQuery(projectRoot: string): string {
  return `?project_root=${encodeURIComponent(projectRoot)}`;
}

export async function previewCodeExecute(
  projectRoot: string,
  request: CodeExecuteRequest,
): Promise<CodeExecutePreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/code-execute/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<CodeExecutePreviewResponse>(response);
}

export async function authorizeCodeExecuteRisk(
  projectRoot: string,
  request: CodeExecuteRequest & {
    preview_fingerprint: string;
    session_id?: string;
    acknowledge_risk: true;
  },
): Promise<CodeExecuteRiskAuthorizationResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/code-execute/risk-authorize${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<CodeExecuteRiskAuthorizationResponse>(response);
}

export async function confirmCodeExecute(
  projectRoot: string,
  request: CodeExecuteRequest & {
    preview_fingerprint: string;
    session_id?: string;
    risk_authorization_id: string;
    risk_authorization_token: string;
  },
): Promise<DataColumnCastConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/code-execute/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastConfirmResponse>(response);
}

export async function fetchDataColumnCastContext(
  projectRoot: string,
  sourceRunId: string,
  sourceNodeId: string,
): Promise<DataColumnCastContext> {
  const params = new URLSearchParams({
    project_root: projectRoot,
    source_run_id: sourceRunId,
    source_node_id: sourceNodeId,
  });
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/context?${params.toString()}`),
  );
  return readResponse<DataColumnCastContext>(response);
}

export async function fetchDataColumnCastRecordByChildNode(
  projectRoot: string,
  childNodeId: string,
): Promise<{ operation: DataColumnCastOperationRecord }> {
  const params = new URLSearchParams({
    project_root: projectRoot,
    child_node_id: childNodeId,
  });
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/by-child-node?${params.toString()}`),
  );
  return readResponse<{ operation: DataColumnCastOperationRecord }>(response);
}

export async function previewDataColumnCast(
  projectRoot: string,
  request: DataColumnCastRequest,
): Promise<DataColumnCastPreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastPreviewResponse>(response);
}

export async function previewDataColumnsCast(
  projectRoot: string,
  request: DataColumnsCastRequest,
): Promise<DataColumnsCastPreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/columns-cast/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnsCastPreviewResponse>(response);
}

export async function confirmDataColumnsCast(
  projectRoot: string,
  request: DataColumnsCastRequest & {
    preview_fingerprint: string;
    session_id?: string;
  },
): Promise<DataColumnCastConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/columns-cast/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastConfirmResponse>(response);
}

export async function confirmDataColumnCast(
  projectRoot: string,
  request: DataColumnCastRequest & {
    preview_fingerprint: string;
    session_id?: string;
  },
): Promise<DataColumnCastConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastConfirmResponse>(response);
}
