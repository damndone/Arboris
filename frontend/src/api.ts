export type ProjectResponse = {
  project_root: string;
};

export type RunStatus = "completed" | "blocked" | string;

export type RunResponse = {
  run_id: string;
  status: RunStatus;
};

export type RunSummary = {
  run_id: string;
  status: string;
  mode: string;
  started_at: string | null;
  y: string | null;
  x: string[] | null;
};

export type RunDetail = RunSummary & {
  lineage: Array<{ source: string; artifact_id: string }>;
  artifact_counts: Record<string, number>;
  errors: { issues: Array<Record<string, unknown>> };
};

export type ArtifactItem = {
  artifact_id: string;
  path: string;
  artifact_type: string;
  step: string;
  sha256: string;
};

export type ArtifactGroup = {
  artifact_type: string;
  items: ArtifactItem[];
};

export type RunsListResponse = { runs: RunSummary[] };
export type ArtifactsResponse = { groups: ArtifactGroup[] };

export type ApiErrorEnvelope = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};

export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: unknown;

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

type FastApiValidationItem = {
  loc?: unknown;
  msg?: unknown;
};

function formatValidationItem(item: FastApiValidationItem): string {
  const msg = typeof item.msg === "string" ? item.msg : JSON.stringify(item.msg);
  if (Array.isArray(item.loc) && item.loc.length > 0) {
    const loc = item.loc
      .filter((part) => part !== "body")
      .map((part) => String(part))
      .join(".");
    return loc ? `${loc}: ${msg}` : msg;
  }
  return msg;
}

function extractDetailMessage(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim() !== "") {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => formatValidationItem(item as FastApiValidationItem)).join("; ");
  }
  return null;
}

function isEnvelope(body: unknown): body is { error: ApiErrorEnvelope } {
  if (!body || typeof body !== "object") return false;
  const error = (body as { error?: unknown }).error;
  if (!error || typeof error !== "object") return false;
  return "code" in error && "message" in error;
}

async function readResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }
  let detail: unknown;
  let parsedMessage: string | null = null;
  let code: string | null = null;
  try {
    const body = await response.json();
    if (isEnvelope(body)) {
      detail = body.error.details;
      parsedMessage = body.error.message;
      code = body.error.code;
    } else if (body && typeof body === "object" && "detail" in body) {
      detail = (body as { detail: unknown }).detail;
      parsedMessage = extractDetailMessage(detail);
    }
  } catch {
    // Body was empty or non-JSON — fall through to generic message.
  }
  const message = parsedMessage ?? `Request failed with status ${response.status}`;
  throw new ApiError(response.status, message, code, detail);
}

export async function createProject(
  parent: string,
  name: string
): Promise<ProjectResponse> {
  const response = await fetch("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent, name })
  });
  return readResponse<ProjectResponse>(response);
}

export async function runWorkflow(
  projectRoot: string,
  mode: string,
  y: string,
  x: string,
  file: File
): Promise<RunResponse> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("y", y);
  form.append("x", x);
  form.append("file", file);
  const response = await fetch("/runs", { method: "POST", body: form });
  return readResponse<RunResponse>(response);
}

export async function fetchRuns(projectRoot: string): Promise<RunsListResponse> {
  const url = `/runs?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return readResponse<RunsListResponse>(response);
}

export async function fetchRunDetail(
  projectRoot: string,
  runId: string,
): Promise<RunDetail> {
  const url = `/runs/${encodeURIComponent(runId)}?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return readResponse<RunDetail>(response);
}

export async function fetchRunArtifacts(
  projectRoot: string,
  runId: string,
): Promise<ArtifactsResponse> {
  const url = `/runs/${encodeURIComponent(runId)}/artifacts?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return readResponse<ArtifactsResponse>(response);
}

export function artifactDownloadUrl(
  projectRoot: string,
  runId: string,
  artifactId: string,
): string {
  return `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}?project_root=${encodeURIComponent(projectRoot)}`;
}

export function reportUrl(projectRoot: string, runId: string): string {
  return `/runs/${encodeURIComponent(runId)}/report?project_root=${encodeURIComponent(projectRoot)}`;
}
