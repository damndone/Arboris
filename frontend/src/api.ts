import * as XLSX from "xlsx";

export type ProjectResponse = {
  project_root: string;
};

export type RunStatus = "completed" | "blocked" | string;

export type RunResponse = {
  run_id: string;
  status: RunStatus;
};

export type BatchRunSummary = {
  y: string;
  run_id: string;
  status: string;
  model_id: string | null;
  model_type: string | null;
};

export type BatchRunResponse = {
  status: string;
  runs: BatchRunSummary[];
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
  evidence?: Record<string, unknown>;
  issue_id?: string;
  affected_stage?: string;
  variables?: string[];
  metric?: string;
  value?: number | null;
  threshold?: number | null;
  template_key?: string;
  template_params?: Record<string, unknown>;
  recommended_action_key?: string;
  is_user_action_required?: boolean;
};

export type TrustStatus = "ok" | "usable_with_caution" | "blocked" | "failed";

export type TrustLabel =
  | "analysis_running"
  | "ready_to_interpret"
  | "interpret_with_caution"
  | "not_ready_to_interpret"
  | "run_failed"
  | "lifecycle_unavailable"
  | "legacy_unavailable"
  | "contract_unavailable";

export type DiagnosticSummaryPreview = {
  available: boolean;
  preview_contract_version: string;
  source_schema_version: string;
  preview_status: string;
  contract_warnings: string[];
  run_lifecycle_status: string;
  run_status?: {
    status: TrustStatus;
    status_scope: string;
    safe_to_generate_report: boolean;
    safe_to_interpret: string;
    has_blockers: boolean;
    has_warnings: boolean;
    has_cautions: boolean;
    model_results_available: boolean;
  };
  trust_label: TrustLabel;
  trust_counts?: {
    blockers: number;
    warnings: number;
    cautions: number;
    info: number;
  };
  primary_reasons: Array<{
    reason_id: string;
    reason_key: string;
    severity: string;
    message: string;
    message_params?: Record<string, unknown>;
    affected_variables: string[];
    linked_issue_ids: string[];
  }>;
  model_identity?: {
    primary_model_id: string;
    model_label: string;
    model_type: string;
    y_variable: string;
    n_observations: number;
    x_variables?: string[];
    x_variable_count?: number;
    standard_error_type?: string;
  };
  artifact_manifest?: Record<string, unknown>;
  diagnostic_highlights?: Array<Record<string, unknown>>;
  coefficient_risk?: CoefficientRisk;
  interpretation_restrictions?: Array<Record<string, unknown>>;
  recommended_actions?: Array<Record<string, unknown>>;
};

export type CoefficientRisk = {
  primary_model_id: string;
  models: Array<{
    model_id: string;
    model_label: string;
    is_primary: boolean;
    model_type: string;
    outcome: string;
    risk_groups: Array<{
      variable: string;
      display_name: string;
      variable_kind: string;
      risk_level: string;
      interpretation_guide: string;
      summary: string;
      linked_issue_ids: string[];
      role_summary?: { role: string; status: string; confidence?: number; needs_user_confirmation: boolean };
      terms: Array<{
        term: string;
        display_term: string;
        level: string;
        reference_level: string;
        estimate?: number;
        p_value?: number;
        source_id: string;
      }>;
    }>;
  }>;
};

export type RunDetail = RunSummary & {
  lineage: Array<{ source: string; artifact_id: string }>;
  artifact_counts: Record<string, number>;
  errors: { issues: IssueRecord[] };
  model_results?: ModelResult[];
  diagnostic_summary_preview?: DiagnosticSummaryPreview;
};

export type CoefficientRecord = {
  estimate?: number | null;
  std_error?: number | null;
  p_value?: number | null;
  p_value_display?: string | null;
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

export type ExcludedColumn = {
  name: string;
  reason: string;
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
  excludedColumns: ExcludedColumn[];
  transposed?: boolean;
  transpose_warning?: string | null;
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

export async function runBatchWorkflow(
  projectRoot: string,
  mode: string,
  yList: string[],
  x: string[],
  file: File,
): Promise<BatchRunResponse> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("y_list", yList.join(","));
  form.append("x", x.join(","));
  form.append("file", file);
  const response = await fetch("/runs/batch", { method: "POST", body: form });
  return readResponse<BatchRunResponse>(response);
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

function _isDateLike(value: unknown): boolean {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return true;
  if (typeof value === "number" && value > 30000 && value < 50000) return true;
  return false;
}

function inferRole(name: string, dtype: ColumnDtype, uniqueCount: number, totalCount: number, values: unknown[]): ColumnRole {
  const lower = name.toLowerCase();
  const strongTimePattern = /(^|_)(date|timestamp)(_|$)/.test(lower);
  const weakTimePattern = /(^|_|\b)(time|year|month)(_|$|\b)/.test(lower);
  const idNamePattern = /(^|_)id$/.test(lower);
  const codeNamePattern = /(^|_|\b)(code|region|category|group|type|class|level)(_|$|\b)/.test(lower);
  const outcomePattern = /(^|_|\b)(y|outcome|target|label|dependent|result|response)(_|$|\b)/.test(lower);

  // Outcome: name strongly signals y → always classify as y
  if (outcomePattern) return "y";

  // Data can override weak name hints
  const isNumeric = dtype === "numeric";
  const diverseNumeric = isNumeric && uniqueCount > 20;
  const allUnique = uniqueCount === totalCount && totalCount > 0;

  // Strong time names + actual date-like data → time
  if (strongTimePattern && values.some(_isDateLike)) return "time";
  // Weak time names but diverse numeric → predictor (not time)
  if (weakTimePattern && diverseNumeric) return "x";
  // Strong time names but diverse numeric → predictor
  if (strongTimePattern && diverseNumeric) return "x";

  // _id suffix + truly unique per row → id
  if (idNamePattern && allUnique) return "id";
  // code/region/category names → categorical candidate (still usable as x)
  if (codeNamePattern) return "x";

  if (isNumeric) return "x";
  return "ignore";
}

function columnStats(name: string, rows: Record<string, unknown>[]): ColumnPreview {
  const values = rows.map((row) => row[name]);
  const present = values.filter((value) => !isMissing(value));
  const dtype = inferDtype(values);
  const uniqueCount = new Set(present.map((value) => String(value))).size;
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
    uniqueCount,
    mean,
    std: variance === undefined ? undefined : Math.sqrt(variance),
    suggestedRole: inferRole(name, dtype, uniqueCount, values.length, present),
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
    const originalKeys = Object.keys(rows[0]);
    const firstKey = originalKeys[0];
    // Use first column values as new column headers
    const newHeaders = rows.map(row => String(row[firstKey] ?? ""));
    const transposed: Record<string, unknown>[] = [];
    for (const key of originalKeys) {
      const row: Record<string, unknown> = {};
      // Original column header becomes the first cell value (unnamed column)
      row[""] = key;
      for (let i = 0; i < rows.length; i++) {
        row[newHeaders[i]] = rows[i][key];
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
  function isOutcomeCandidate(name: string): boolean {
    const lower = name.toLowerCase();
    return /_y$|_outcome$|_target$|_label$|_response$|_dependent$/.test(lower);
  }

  const suggestedX = columns
    .filter(
      (column) =>
        column.dtype === "numeric" &&
        column.name !== suggestedY &&
        !isOutcomeCandidate(column.name) &&
        column.suggestedRole === "x",
    )
    .map((column) => column.name);

  const excludedColumns: ExcludedColumn[] = columns
    .filter((column) =>
      column.dtype === "numeric" &&
      column.name !== suggestedY &&
      !isOutcomeCandidate(column.name) &&
      column.suggestedRole !== "x"
    )
    .map((column) => {
      const role = column.suggestedRole;
      let reason: string;
      if (role === "id") reason = `auto-detected as identifier (${column.uniqueCount} unique values in ${rows.length} rows)`;
      else if (role === "time") reason = "auto-detected as time/date column";
      else if (role === "ignore") reason = "auto-detected as non-numeric";
      else reason = `excluded (role: ${role})`;
      return { name: column.name, reason };
    });

  const transposeWarning =
    transpose && columns.length > rows.length * 2
      ? `⚠️ Your data has ${columns.length} columns but only ${rows.length} rows. This may mean rows and columns are reversed. Uncheck 'Transpose' if variables should be in columns.`
      : null;

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
    excludedColumns,
    transposed: transpose ?? false,
    transpose_warning: transposeWarning,
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
