import * as XLSX from "xlsx";

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

export type IssueRecord = {
  severity?: string;
  code?: string;
  message?: string;
};

export type RunDetail = RunSummary & {
  lineage: Array<{ source: string; artifact_id: string }>;
  artifact_counts: Record<string, number>;
  errors: { issues: IssueRecord[] };
  model_results?: ModelResult[];
};

export type CoefficientRecord = {
  estimate?: number | null;
  std_error?: number | null;
  p_value?: number | null;
  source_id?: string;
};

export type ModelResult = {
  model_id: string;
  model_type?: string;
  r_squared?: number | null;
  pseudo_r2?: number | null;
  llf?: number | null;
  aic?: number | null;
  bic?: number | null;
  nobs?: number;
  coefficients: Record<string, CoefficientRecord>;
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

export type ColumnRole = "y" | "x" | "id" | "time" | "ignore";
export type ColumnDtype = "numeric" | "string" | "datetime" | "other";

export type ColumnPreview = {
  name: string;
  dtype: ColumnDtype;
  missingRate: number;
  uniqueCount: number;
  mean?: number;
  std?: number;
  suggestedRole: ColumnRole;
};

export type FilePreview = {
  fileName: string;
  sheetNames: string[];
  selectedSheet: string;
  rowCount: number;
  columnCount: number;
  columns: ColumnPreview[];
  previewRows: Record<string, unknown>[];
  suggestedY: string | null;
  suggestedX: string[];
};

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
  file: File,
  modelType: string = "auto",
  sheetName?: string,
  transpose?: boolean,
): Promise<RunResponse> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("model_type", modelType);
  form.append("y", y);
  form.append("x", x);
  if (sheetName) form.append("sheet_name", sheetName);
  if (transpose) form.append("transpose", "true");
  form.append("file", file);
  const response = await fetch("/runs", { method: "POST", body: form });
  return readResponse<RunResponse>(response);
}

function isMissing(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function isDateLike(value: unknown): boolean {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return true;
  if (typeof value !== "string" || value.trim() === "") return false;
  return !Number.isNaN(Date.parse(value));
}

function inferDtype(values: unknown[]): ColumnDtype {
  const present = values.filter((value) => !isMissing(value));
  if (present.length === 0) return "other";
  if (present.every((value) => asNumber(value) !== null)) return "numeric";
  if (present.every(isDateLike)) return "datetime";
  if (present.every((value) => typeof value === "string")) return "string";
  return "other";
}

function inferRole(name: string, dtype: ColumnDtype): ColumnRole {
  const lower = name.toLowerCase();
  if (/(^|_|\b)(date|time|year|month|timestamp)(_|$|\b)/.test(lower)) return "time";
  if (/(^|_|\b)(id|code|key|firm|user)(_|$|\b)/.test(lower)) return "id";
  if (/(^|_|\b)(y|dependent|outcome|target|result)(_|$|\b)/.test(lower)) return "y";
  if (dtype === "numeric") return "x";
  return "ignore";
}

function columnStats(name: string, rows: Record<string, unknown>[]): ColumnPreview {
  const values = rows.map((row) => row[name]);
  const present = values.filter((value) => !isMissing(value));
  const dtype = inferDtype(values);
  const numeric = present
    .map(asNumber)
    .filter((value): value is number => value !== null);
  const mean =
    dtype === "numeric" && numeric.length > 0
      ? numeric.reduce((sum, value) => sum + value, 0) / numeric.length
      : undefined;
  const variance =
    mean !== undefined && numeric.length > 1
      ? numeric.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
        (numeric.length - 1)
      : undefined;

  return {
    name,
    dtype,
    missingRate: values.length === 0 ? 0 : (values.length - present.length) / values.length,
    uniqueCount: new Set(present.map((value) => String(value))).size,
    mean,
    std: variance === undefined ? undefined : Math.sqrt(variance),
    suggestedRole: inferRole(name, dtype),
  };
}

export async function previewFile(
  file: File,
  sheetName?: string,
  transpose?: boolean,
): Promise<FilePreview> {
  const buffer =
    typeof file.arrayBuffer === "function"
      ? await file.arrayBuffer()
      : await new Promise<ArrayBuffer>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result as ArrayBuffer);
          reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
          reader.readAsArrayBuffer(file);
        });
  const workbook = XLSX.read(buffer, { type: "array", cellDates: true });
  const selectedSheet = sheetName ?? workbook.SheetNames[0];
  const sheet = workbook.Sheets[selectedSheet];
  let rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, {
    defval: null,
    raw: true,
  });
  if (transpose && rows.length > 0) {
    const transposed: Record<string, unknown>[] = [];
    const keys = Object.keys(rows[0]);
    for (const key of keys) {
      const row: Record<string, unknown> = {};
      for (const src of rows) {
        row[String(src[key] ?? "")] = src[key];
      }
      transposed.push(row);
    }
    rows = transposed;
  }
  const columnNames =
    rows.length > 0
      ? Object.keys(rows[0])
      : XLSX.utils.sheet_to_json<string[]>(sheet, { header: 1 })[0] ?? [];
  const columns = columnNames.map((name) => columnStats(String(name), rows));
  const suggestedY =
    columns.find((column) => column.suggestedRole === "y" && column.dtype === "numeric")?.name ??
    columns.find(
      (column) =>
        column.dtype === "numeric" &&
        column.suggestedRole !== "id" &&
        column.suggestedRole !== "time",
    )?.name ??
    null;
  const suggestedX = columns
    .filter(
      (column) =>
        column.dtype === "numeric" &&
        column.name !== suggestedY &&
        column.suggestedRole !== "id" &&
        column.suggestedRole !== "time",
    )
    .map((column) => column.name);

  return {
    fileName: file.name,
    sheetNames: workbook.SheetNames,
    selectedSheet,
    rowCount: rows.length,
    columnCount: columns.length,
    columns,
    previewRows: rows.slice(0, 10),
    suggestedY,
    suggestedX,
  };
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

export type RunProgressEvent = {
  event: "step_start" | "step_complete" | "step_blocked"
       | "workflow_completed" | "workflow_blocked"
       | "workflow_failed" | "workflow_interrupted";
  run_id: string;
  sequence: number;
  timestamp: string;
  step: string | null;
  message: string;
  status: string | null;
};

export type RunProgressCallbacks = {
  onStepStart?: (step: string, msg: string) => void;
  onStepComplete?: (step: string, msg: string) => void;
  onStepBlocked?: (step: string, msg: string) => void;
  onTerminal?: (status: string, msg: string) => void;
  onError?: (err: Error) => void;
};

export function connectRunEvents(
  projectRoot: string,
  runId: string,
  callbacks: RunProgressCallbacks,
): () => void {
  const url = `/runs/${encodeURIComponent(runId)}/events?project_root=${encodeURIComponent(projectRoot)}`;
  const source = new EventSource(url);

  source.addEventListener("step_start", (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onStepStart?.(data.step ?? "", data.message);
  });
  source.addEventListener("step_complete", (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onStepComplete?.(data.step ?? "", data.message);
  });
  source.addEventListener("step_blocked", (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onStepBlocked?.(data.step ?? "", data.message);
  });

  const handleTerminal = (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onTerminal?.(data.status ?? "unknown", data.message);
    source.close();
  };
  source.addEventListener("workflow_completed", handleTerminal);
  source.addEventListener("workflow_blocked", handleTerminal);
  source.addEventListener("workflow_failed", handleTerminal);
  source.addEventListener("workflow_interrupted", handleTerminal);

  source.onerror = () => callbacks.onError?.(new Error("SSE connection error"));
  return () => source.close();
}
