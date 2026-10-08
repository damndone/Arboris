import { apiUrl, readResponse } from "../api";
import type { RequestOf, ResponseOf, Schema } from "../apiTypes";

const jsonHeaders = { "Content-Type": "application/json" };

export type NotebookRecord = Schema<"NotebookView">;
export type NotebookFocusInput = RequestOf<"/notebooks/{notebook_id}/focus", "put">;
export type NotebookInteractionMode = NonNullable<NotebookFocusInput["interaction_mode"]>;
export type NotebookContextResponse = Schema<"PlanningContextView">;
export type NotebookOptionsResponse = Schema<"NotebookOptions">;
export type NotebookTraceResponse = Schema<"NotebookTrace">;
export type NotebookCreateInput = RequestOf<"/notebooks", "post">;
export type NotebookProjectionDataset = Schema<"DatasetProjectionSource">;
export type NotebookMaterializationResponse = Schema<"Materialized">;

export interface NotebookPlanningRequest {
  attemptId: string;
  signal?: AbortSignal;
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

export function listNotebooks(projectRoot: string): Promise<ResponseOf<"/notebooks", "get">> {
  return readNotebookResponse(projectRoot, "/notebooks");
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
  input: Partial<RequestOf<"/notebooks/projection", "post">>,
): Promise<ResponseOf<"/notebooks/projection", "post">> {
  return readNotebookResponse(projectRoot, "/notebooks/projection", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ created_by: "user", title: "Analysis Notebook", ...input }),
  });
}

export function ensureNotebookDatasetProjection(
  projectRoot: string,
  input: Partial<RequestOf<"/notebooks/projection/from-run-dataset", "post">> & { from_run_id: string },
): Promise<ResponseOf<"/notebooks/projection/from-run-dataset", "post">> {
  return readNotebookResponse(
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
): Promise<NotebookContextResponse> {
  return readNotebookResponse<NotebookContextResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/context/compile`,
    { method: "POST" },
  );
}

export function proposeNotebookOptions(
  projectRoot: string,
  notebookId: string,
  count = 3,
  planning?: NotebookPlanningRequest,
): Promise<NotebookOptionsResponse> {
  return readNotebookResponse<NotebookOptionsResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/propose`,
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
): Promise<ResponseOf<"/notebooks/{notebook_id}/planning/{attempt_id}", "delete">> {
  return readNotebookResponse(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/planning/${encodeURIComponent(attemptId)}`,
    { method: "DELETE" },
  );
}

export function listNotebookOptions(
  projectRoot: string,
  notebookId: string,
): Promise<NotebookOptionsResponse> {
  // POST: the server records the compiled context it shows (no GET writes).
  return readNotebookResponse<NotebookOptionsResponse>(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options`,
    { method: "POST" },
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

export type NotebookDecision = RequestOf<"/notebooks/{notebook_id}/options/{option_id}/decision", "post">;

export function recordNotebookDecision(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  body: NotebookDecision,
): Promise<ResponseOf<"/notebooks/{notebook_id}/options/{option_id}/decision", "post">> {
  return readNotebookResponse(
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
  body: RequestOf<"/notebooks/{notebook_id}/options/{option_id}/confirm", "post">,
): Promise<ResponseOf<"/notebooks/{notebook_id}/options/{option_id}/confirm", "post">> {
  return readNotebookResponse(
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
  body: RequestOf<"/notebooks/{notebook_id}/options/{option_id}/confirm-and-execute", "post">,
): Promise<ResponseOf<"/notebooks/{notebook_id}/options/{option_id}/confirm-and-execute", "post">> {
  return readNotebookResponse(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/confirm-and-execute`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}

export function completeNotebookOptionExecution(
  projectRoot: string,
  notebookId: string,
  optionId: string,
  body: RequestOf<"/notebooks/{notebook_id}/options/{option_id}/execute", "post">,
): Promise<ResponseOf<"/notebooks/{notebook_id}/options/{option_id}/execute", "post">> {
  return readNotebookResponse(
    projectRoot,
    `/notebooks/${encodeURIComponent(notebookId)}/options/${encodeURIComponent(optionId)}/execute`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    },
  );
}
