export type ProjectResponse = {
  project_root: string;
};

export type RunStatus = "completed" | "blocked" | string;

export type RunResponse = {
  run_id: string;
  status: RunStatus;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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

async function readResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }
  let detail: unknown;
  let parsedMessage: string | null = null;
  try {
    const body = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      detail = (body as { detail: unknown }).detail;
      parsedMessage = extractDetailMessage(detail);
    }
  } catch {
    // Body was empty or non-JSON — fall through to generic message.
  }
  const message = parsedMessage ?? `Request failed with status ${response.status}`;
  throw new ApiError(response.status, message, detail);
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
