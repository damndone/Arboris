import { apiUrl, readResponse } from "../api";
import type { PipelineDraftResponse } from "../api";
import type { DomainMemoryPreferences } from "./domainMemoryContracts";

const jsonHeaders = { "Content-Type": "application/json" };

export interface NotebookRecord {
  notebook_id: string;
  project_id?: string;
  run_family_id: string;
  title: string;
  created_by: string;
  created_at?: string;
  active_head_run_id: string | null;
  focused_run_id?: string | null;
  last_attempt_run_id?: string | null;
  analysis_contract?: Record<string, unknown>;
  user_focus?: Record<string, unknown>;
  available_capabilities?: string[];
}

export type NotebookInteractionMode = "plan" | "action";

export interface NotebookFocusInput {
  goal?: string;
  interaction_mode?: NotebookInteractionMode;
}

export interface NotebookContextResponse {
  context_id: string;
  context_profile: string;
  generation_context_hash: string;
  freshness_dependency_fingerprint: string;
  artifact_type_counts: Record<string, number>;
  omissions: Array<Record<string, unknown>>;
  budget_report: Record<string, unknown>;
  source_manifest: Array<Record<string, unknown>>;
  trace_id?: string | null;
  [key: string]: unknown;
}

function domainMemoryQuery(preferences?: DomainMemoryPreferences): string {
  if (!preferences) return "";
  const params = new URLSearchParams({
    domain_memory_use: String(preferences.cross_project_domain_memory_use),
    domain_memory_iteration: String(preferences.cross_project_domain_memory_iteration),
  });
  return `?${params.toString()}`;
}

export interface NotebookOptionsResponse {
  context: NotebookContextResponse;
  options: unknown[];
  materializations?: Record<string, Record<string, unknown>>;
  execution_results?: Record<string, Record<string, unknown>>;
  trace_id: string;
}

export interface NotebookPlanningRequest {
  attemptId: string;
  signal?: AbortSignal;
}

export interface NotebookTraceResponse {
  trace_id: string;
  events: Array<Record<string, unknown>>;
}

export interface NotebookCreateInput {
  title: string;
  created_by: string;
  from_run_id?: string | null;
  analysis_contract?: Record<string, unknown>;
  user_focus?: Record<string, unknown>;
  available_capabilities?: string[];
}

export interface NotebookProjectionDataset {
  upload_sha256: string;
  filename: string;
  sheet_names: string[];
}

export interface NotebookMaterializationResponse extends PipelineDraftResponse {
  materialization: Record<string, unknown>;
  trace_id?: string;
}

function notebookPath(
  projectRoot: string,
  path: string,
): string {
  const separator = path.includes("?") ? "&" : "?";
  return apiUrl(`${path}${separator}project_root=${encodeURIComponent(projectRoot)}`);
}

async function readNotebookResponse<T>(
  projectRoot: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  return readResponse<T>(await fetch(notebookPath(projectRoot, path), init));
}

export function listNotebooks(projectRoot: string): Promise<NotebookRecord[]> {
  return readNotebookResponse<NotebookRecord[]>(projectRoot, "/notebooks");
}

export function createNotebook(
  projectRoot: string,
  input: NotebookCreateInput,
): Promise<NotebookRecord> {
  return readNotebookResponse<NotebookRecord>(projectRoot, "/notebooks", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function ensureNotebookProjection(
  projectRoot: string,
  input:
    | { from_run_id: string; created_by?: string; title?: string }
    | { dataset: NotebookProjectionDataset; created_by?: string; title?: string },
): Promise<NotebookRecord> {
  return readNotebookResponse<NotebookRecord>(projectRoot, "/notebooks/projection", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ created_by: "user", title: "Analysis Notebook", ...input }),
  });
}

export function ensureNotebookDatasetProjection(
  projectRoot: string,
  input: { from_run_id: string; created_by?: string; title?: string },
): Promise<NotebookRecord> {
  return readNotebookResponse<NotebookRecord>(
    projectRoot,
    "/notebooks/projection/from-run-dataset",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        created_by: "user",
        title: "New analysis from source data",
        ...input,
      }),
    },
  );
}

export function getNotebook(
  projectRoot: string,
  notebookId: string,
): Promise<NotebookRecord> {
  return readNotebookResponse<NotebookRecord>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}`,
  );
}

export function updateNotebookFocus(
  projectRoot: string,
  notebookId: string,
  input: NotebookFocusInput,
): Promise<NotebookRecord> {
  return readNotebookResponse<NotebookRecord>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/focus`,
    {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
  );
}

export function compileNotebookContext(
  projectRoot: string,
  notebookId: string,
  preferences?: DomainMemoryPreferences,
): Promise<NotebookContextResponse> {
  return readNotebookResponse<NotebookContextResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/context/compile${domainMemoryQuery(preferences)}`,
    { method: "POST" },
  );
}

export function proposeNotebookOptions(
  projectRoot: string,
  notebookId: string,
  count = 3,
  preferences?: DomainMemoryPreferences,
  planning?: NotebookPlanningRequest,
): Promise<NotebookOptionsResponse> {
  return readNotebookResponse<NotebookOptionsResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/propose${domainMemoryQuery(preferences)}`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        count,
        ...(planning ? { attempt_id: planning.attemptId } : {}),
      }),
      signal: planning?.signal,
    },
  );
}

export function cancelNotebookPlanning(
  projectRoot: string,
  notebookId: string,
  attemptId: string,
): Promise<{ attempt_id: string; status: "cancelled" | "not_active" }> {
  return readNotebookResponse(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/planning/${encodeURIComponent(attemptId)}`,
    { method: "DELETE" },
  );
}

export function listNotebookOptions(
  projectRoot: string,
  notebookId: string,
  preferences?: DomainMemoryPreferences,
): Promise<NotebookOptionsResponse> {
  return readNotebookResponse<NotebookOptionsResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options${domainMemoryQuery(preferences)}`,
  );
}

export function getNotebookTrace(
  projectRoot: string,
  notebookId: string,
  traceId: string,
): Promise<NotebookTraceResponse> {
  return readNotebookResponse<NotebookTraceResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/traces/${encodeURIComponent(traceId)}`,
  );
}

export type NotebookDecision = {
  decision:
    | "selected"
    | "deferred"
    | "rejected"
    | "edited"
    | "requested_more_options"
    | "requested_explanation";
  actor: string;
  edited_fields?: string[];
  note_ref?: string;
};

export function recordNotebookDecision(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  body: NotebookDecision,
): Promise<Record<string, unknown>> {
  return readNotebookResponse<Record<string, unknown>>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/decision`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}

export function confirmNotebookOption(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  body: {
    option_revision: number;
    proposal_id: string;
    proposal_revision: number;
  },
): Promise<Record<string, unknown>> {
  return readNotebookResponse<Record<string, unknown>>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/confirm`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}

export function materializeNotebookOption(
  projectRoot: string,
  notebookId: string,
  optionId: string,
): Promise<NotebookMaterializationResponse> {
  return readNotebookResponse<NotebookMaterializationResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/materialize`,
    { method: "POST", headers: jsonHeaders },
  );
}

export function confirmAndExecuteNotebookOption(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  body: {
    option_revision: number;
    proposal_id: string;
    proposal_revision: number;
  },
): Promise<{ dispatch: Record<string, unknown>; trace_id: string }> {
  return readNotebookResponse<{ dispatch: Record<string, unknown>; trace_id: string }>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/confirm-and-execute`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}

export function authorizeNotebookOptionExecution(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  authorization: Record<string, unknown>,
): Promise<{ authorization: Record<string, unknown>; trace_id: string }> {
  return readNotebookResponse<{ authorization: Record<string, unknown>; trace_id: string }>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/authorize-execution`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ authorization }),
    },
  );
}

export function completeNotebookOptionExecution(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  body: {
    execution_status: string;
    run_id?: string;
    error_code?: string;
  },
): Promise<Record<string, unknown>> {
  return readNotebookResponse<Record<string, unknown>>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/execute`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}
