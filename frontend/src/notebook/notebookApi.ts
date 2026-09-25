import { apiUrl, readResponse } from "../api";

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
  goal?: string | null;
  interaction_mode?: NotebookInteractionMode;
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
