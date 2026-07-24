import * as XLSX from "xlsx";
import type { GraphResponse } from "./lineage/types";
import type { HeadSetResponse } from "./lineage/api/graphViewTypes";
import type { ManualRerunPatch } from "./lineage/detail/sections/manualRerunPatch";

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

export type ArmaGarchTransformPreflight = {
  schema_version: 1;
  source_row_count: number;
  analysis_row_count: number;
  diagnostics: Array<Record<string, unknown>>;
  transform_profiles: Record<string, Record<string, unknown>>;
  recommendation: {
    transform_id: "level" | "log_level" | "diff_1" | "log_return_pct";
    score: number;
    reason: string;
  };
  transform_confirmation_required: true;
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

const API_PREFIX = "/api";

export function apiUrl(path: string): string {
  return `${API_PREFIX}${path}`;
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
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim() !== "") {
      return message;
    }
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

export async function readResponse<T>(response: Response): Promise<T> {
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
  const response = await fetch(apiUrl("/projects"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent, name })
  });
  return readResponse<ProjectResponse>(response);
}

export interface RunExtraParams {
  entityCol?: string;
  timeCol?: string;
  covariance?: string;
  predictionModelType?: string;
  predictionCvFolds?: number;
  predictionSamplingMethod?: string;
  ivEndog?: string[];
  ivInstruments?: string[];
  didMode?: string;
  didCohortCol?: string;
  didTreatCol?: string;
  didPostCol?: string;
  didStatusCol?: string;
  csControlGroup?: string;
  csEstMethod?: string;
  csBasePeriod?: string;
  csAnticipation?: number;
  csClusterVar?: string;
  honestDid?: boolean;
  didTreatmentPath?: string;
  /** v1.6.5 — user-declared focal explanatory columns (role layer). Posted
   *  comma-joined; the backend clears it for structural-focal families. */
  focalX?: string[];
  /** Model-pack-specific options. The backend treats this as a typed JSON
   * object and leaves semantic validation to the registered model handler. */
  modelOptions?: Record<string, unknown>;
}

function serializeModelOptions(value: Record<string, unknown>): string {
  const activeObjects = new WeakSet<object>();

  const visit = (candidate: unknown, path: string): void => {
    if (
      candidate === null
      || typeof candidate === "string"
      || typeof candidate === "boolean"
    ) {
      return;
    }
    if (typeof candidate === "number") {
      if (!Number.isFinite(candidate)) {
        throw new TypeError(`${path} must contain only finite JSON numbers`);
      }
      return;
    }
    if (Array.isArray(candidate)) {
      if (activeObjects.has(candidate)) {
        throw new TypeError(`${path} must not contain circular JSON values`);
      }
      activeObjects.add(candidate);
      candidate.forEach((item, index) => visit(item, `${path}[${index}]`));
      activeObjects.delete(candidate);
      return;
    }
    if (typeof candidate !== "object") {
      throw new TypeError(`${path} must contain only JSON values`);
    }

    const prototype = Object.getPrototypeOf(candidate);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new TypeError(`${path} must contain only plain JSON objects`);
    }
    if (Object.getOwnPropertySymbols(candidate).length > 0) {
      throw new TypeError(`${path} must not contain symbol keys`);
    }
    if (activeObjects.has(candidate)) {
      throw new TypeError(`${path} must not contain circular JSON values`);
    }
    activeObjects.add(candidate);
    Object.entries(candidate).forEach(([key, item]) => visit(item, `${path}.${key}`));
    activeObjects.delete(candidate);
  };

  visit(value, "modelOptions");
  const serialized = JSON.stringify(value);
  if (typeof serialized !== "string") {
    throw new TypeError("modelOptions must serialize to a JSON object");
  }
  return serialized;
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
  imputation?: string,
  extra?: RunExtraParams,
): Promise<RunResponse> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("model_type", modelType);
  form.append("y", y);
  form.append("x", x);
  if (sheetName) form.append("sheet_name", sheetName);
  if (transpose) form.append("transpose", "true");
  if (imputation) form.append("imputation", imputation);
  if (extra?.entityCol) form.append("entity_col", extra.entityCol);
  if (extra?.timeCol) form.append("time_col", extra.timeCol);
  if (extra?.covariance) form.append("covariance", extra.covariance);
  if (extra?.ivEndog?.length) form.append("iv_endog", JSON.stringify(extra.ivEndog));
  if (extra?.ivInstruments?.length) form.append("iv_instruments", JSON.stringify(extra.ivInstruments));
  if (extra?.didMode) form.append("did_mode", extra.didMode);
  if (extra?.didCohortCol) form.append("did_cohort_col", extra.didCohortCol);
  if (extra?.didTreatCol) form.append("did_treat_col", extra.didTreatCol);
  if (extra?.didPostCol) form.append("did_post_col", extra.didPostCol);
  if (extra?.didStatusCol) form.append("did_status_col", extra.didStatusCol);
  if (extra?.csControlGroup) form.append("cs_control_group", extra.csControlGroup);
  if (extra?.csEstMethod) form.append("cs_est_method", extra.csEstMethod);
  if (extra?.csBasePeriod) form.append("cs_base_period", extra.csBasePeriod);
  if (extra?.csAnticipation) form.append("cs_anticipation", String(extra.csAnticipation));
  if (extra?.csClusterVar) form.append("cs_cluster_var", extra.csClusterVar);
  if (extra?.honestDid) form.append("honest_did", "true");
  if (extra?.didTreatmentPath) form.append("did_treatment_path", extra.didTreatmentPath);
  if (extra?.focalX?.length) form.append("focal_x", extra.focalX.join(","));
  if (extra?.predictionModelType) form.append("prediction_model_type", extra.predictionModelType);
  if (extra?.predictionCvFolds) form.append("prediction_cv_folds", String(extra.predictionCvFolds));
  if (extra?.predictionSamplingMethod) form.append("prediction_sampling_method", extra.predictionSamplingMethod);
  if (extra?.modelOptions !== undefined) {
    form.append("model_options", serializeModelOptions(extra.modelOptions));
  }
  form.append("file", file);
  const response = await fetch(apiUrl("/runs"), { method: "POST", body: form });
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
  const response = await fetch(apiUrl("/runs/batch"), {
    method: "POST",
    body: form,
  });
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

export async function fetchArmaGarchTransformPreflight(
  projectRoot: string,
  file: File,
  input: {
    timeColumn: string;
    valueColumn: string;
    timeIndexSemantics: string;
    missingValuePolicy: string;
    sheetName?: string;
    transpose?: boolean;
  },
): Promise<ArmaGarchTransformPreflight> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("file", file);
  form.append("time_column", input.timeColumn);
  form.append("value_column", input.valueColumn);
  form.append("time_index_semantics", input.timeIndexSemantics);
  form.append("missing_value_policy", input.missingValuePolicy);
  form.append("sheet_name", input.sheetName ?? "");
  form.append("transpose", input.transpose ? "true" : "false");
  const response = await fetch(apiUrl("/runs/arma-garch/transform-preflight"), {
    method: "POST",
    body: form,
  });
  return readResponse<ArmaGarchTransformPreflight>(response);
}

export async function fetchRuns(projectRoot: string): Promise<RunsListResponse> {
  const url = apiUrl(`/runs?project_root=${encodeURIComponent(projectRoot)}`);
  const response = await fetch(url);
  return readResponse<RunsListResponse>(response);
}

export async function fetchRunDetail(
  projectRoot: string,
  runId: string,
): Promise<RunDetail> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}?project_root=${encodeURIComponent(projectRoot)}`,
  );
  const response = await fetch(url);
  return readResponse<RunDetail>(response);
}

/**
 * Wait for a run to reach a terminal status (anything other than
 * `"running"`). Uses SSE when available (real-time, cheap) and falls
 * back to polling `fetchRunDetail` when EventSource is missing or the
 * stream errors. Without this guard the Submit page's auto-navigation
 * lands on the lineage view before graph.json is written.
 *
 * - SSE path: subscribe to /runs/<id>/events, fetch detail once on
 *   the terminal event. Intermediate ticks pass `lastEvent` so UI can
 *   show "currently running: <step>".
 * - Polling path: 500 ms cadence, fetches detail every tick.
 * - Default cap: 30 min (SSE is cheap; the polling fallback inherits
 *   the remaining time on the same deadline).
 *
 * `onTick(detail, lastEvent?)`: `detail` is the freshly fetched
 * `RunDetail` on the polling path, `null` on the SSE path (we skip
 * the per-event fetch). `lastEvent` is populated only on the SSE
 * path. Callers that only care about progress text should read from
 * `lastEvent`.
 */
export type WaitForRunTerminalOpts = {
  intervalMs?: number;
  maxMs?: number;
  onTick?: (detail: RunDetail | null, lastEvent?: RunProgressEvent) => void;
  signal?: AbortSignal;
};

class _SseUnavailable extends Error {
  constructor() {
    super("SSE stream errored; falling back to polling");
    this.name = "SseUnavailable";
  }
}

async function _pollUntilTerminal(
  projectRoot: string,
  runId: string,
  opts: {
    intervalMs: number;
    deadline: number;
    signal?: AbortSignal;
    onTick?: WaitForRunTerminalOpts["onTick"];
  },
): Promise<RunDetail> {
  while (true) {
    if (opts.signal?.aborted) {
      throw new DOMException("waitForRunTerminal aborted", "AbortError");
    }
    const detail = await fetchRunDetail(projectRoot, runId);
    if (detail.status !== "running") return detail;
    opts.onTick?.(detail);
    if (Date.now() >= opts.deadline) {
      throw new Error(
        `Run ${runId} still running after deadline; giving up on poll.`,
      );
    }
    await new Promise<void>((resolve) => setTimeout(resolve, opts.intervalMs));
  }
}

function _subscribeUntilTerminal(
  projectRoot: string,
  runId: string,
  opts: {
    signal?: AbortSignal;
    onTick?: WaitForRunTerminalOpts["onTick"];
  },
): Promise<RunDetail> {
  return new Promise<RunDetail>((resolve, reject) => {
    if (opts.signal?.aborted) {
      reject(new DOMException("waitForRunTerminal aborted", "AbortError"));
      return;
    }
    let close: (() => void) | null = null;
    let settled = false;
    let sequence = 0;
    const onAbort = () => {
      if (settled) return;
      settled = true;
      close?.();
      reject(new DOMException("waitForRunTerminal aborted", "AbortError"));
    };
    opts.signal?.addEventListener("abort", onAbort);

    const cleanup = () => {
      settled = true;
      opts.signal?.removeEventListener("abort", onAbort);
    };

    const emit = (
      event: RunProgressEvent["event"],
      step: string | null,
      message: string,
      status: string | null,
    ) => {
      sequence += 1;
      const lastEvent: RunProgressEvent = {
        event,
        run_id: runId,
        sequence,
        timestamp: new Date().toISOString(),
        step,
        message,
        status,
      };
      opts.onTick?.(null, lastEvent);
    };

    close = connectRunEvents(projectRoot, runId, {
      onStepStart: (step, msg) => emit("step_start", step, msg, null),
      onStepComplete: (step, msg) => emit("step_complete", step, msg, null),
      onStepBlocked: (step, msg) => emit("step_blocked", step, msg, null),
      onTerminal: (status, msg) => {
        if (settled) return;
        // connectRunEvents closes the EventSource for us before
        // returning from its terminal handler; fetch the final detail
        // (graph.json + manifest are flushed by now) and resolve.
        emit("workflow_completed", null, msg, status);
        cleanup();
        fetchRunDetail(projectRoot, runId).then(resolve, reject);
      },
      onError: () => {
        if (settled) return;
        cleanup();
        close?.();
        reject(new _SseUnavailable());
      },
    });
  });
}

export async function waitForRunTerminal(
  projectRoot: string,
  runId: string,
  opts: WaitForRunTerminalOpts = {},
): Promise<RunDetail> {
  const intervalMs = opts.intervalMs ?? 500;
  const maxMs = opts.maxMs ?? 30 * 60 * 1000;
  const deadline = Date.now() + maxMs;
  const pollArgs = {
    intervalMs,
    deadline,
    signal: opts.signal,
    onTick: opts.onTick,
  };

  // Older browsers / jsdom don't ship EventSource. Skip straight to
  // polling so dev/test still work without the SSE path.
  if (typeof EventSource === "undefined") {
    return _pollUntilTerminal(projectRoot, runId, pollArgs);
  }

  try {
    return await _subscribeUntilTerminal(projectRoot, runId, {
      signal: opts.signal,
      onTick: opts.onTick,
    });
  } catch (err) {
    if (err instanceof _SseUnavailable) {
      // SSE stream broke (network blip, proxy stripping `text/event-stream`,
      // etc.). Fall through to the polling loop with whatever time is
      // left on the shared deadline.
      return _pollUntilTerminal(projectRoot, runId, pollArgs);
    }
    throw err;
  }
}

export async function fetchRunArtifacts(
  projectRoot: string,
  runId: string,
): Promise<ArtifactsResponse> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/artifacts?project_root=${encodeURIComponent(projectRoot)}`,
  );
  const response = await fetch(url);
  return readResponse<ArtifactsResponse>(response);
}

export function artifactDownloadUrl(
  projectRoot: string,
  runId: string,
  artifactId: string,
): string {
  return apiUrl(
    `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}?project_root=${encodeURIComponent(projectRoot)}`,
  );
}

// V1.5.4.1: fetch a single artifact's JSON body (e.g. imputation_summary).
// The artifact endpoint serves the raw file; readResponse parses it.
export async function fetchArtifactJson<T = unknown>(
  projectRoot: string,
  runId: string,
  artifactId: string,
): Promise<T> {
  const response = await fetch(artifactDownloadUrl(projectRoot, runId, artifactId));
  return readResponse<T>(response);
}

export function reportUrl(projectRoot: string, runId: string): string {
  return apiUrl(
    `/runs/${encodeURIComponent(runId)}/report?project_root=${encodeURIComponent(projectRoot)}`,
  );
}

export async function getRunGraph(
  projectRoot: string,
  runId: string,
): Promise<GraphResponse> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/graph?project_root=${encodeURIComponent(projectRoot)}`,
  );
  const response = await fetch(url);
  return readResponse<GraphResponse>(response);
}

export type DraftExecutionMode = "rerun_child" | "new_run" | "genesis";

export type PipelineDraftNode =
  | {
      node_id: string;
      node_type: "input.dataset";
      source_type: "run_input" | "upload";
      run_input_id?: string;
      upload_sha?: string;
      dataset_snapshot_id?: string;
      schema_fingerprint: string;
      input_fingerprint: string;
      row_count?: number;
      column_count?: number;
      columns_summary?: Array<{ name: string; dtype?: string }>;
      status: "bound" | "missing" | "invalid";
    }
  | {
      node_id: string;
      node_type: "model";
      model_family?: string;
      model_type?: string;
      schema_id?: string;
      editable_schema?: unknown[];
      editable_schema_hash?: string;
      source_ref?: Record<string, string>;
      source_params?: Record<string, unknown>;
      params: Record<string, unknown>;
      status?: "pending" | "configured" | "invalid";
    }
  | {
      node_id: string;
      node_type: "input.upload";
      upload: { sha256: string; filename: string };
      sheet_names: string[];
      columns?: string[];
      status: "bound" | "missing" | "invalid";
    }
  | {
      node_id: string;
      node_type: "table";
      params: { sheet_name?: string; transpose?: boolean } & Record<string, unknown>;
      columns: string[];
      status: "pending" | "configured" | "invalid";
    };

export type PipelineDraftV1 = {
  draft_id: string;
  schema_version: "pipeline_draft.v1";
  created_at: string;
  updated_at: string;
  status: string;
  created_from?: Record<string, string>;
  notebook_provenance?: Record<string, string>;
  graph: {
    nodes: PipelineDraftNode[];
    edges: Array<{ from: string; to: string }>;
  };
  default_execution_mode: DraftExecutionMode;
};

export type PipelineDraftResponse = {
  draft: PipelineDraftV1;
  draft_hash: string;
};

export type DraftValidationResult = {
  ok: boolean;
  status: "valid" | "invalid" | "blocked";
  executable: boolean;
  checks: Array<{
    code: string;
    level: "error" | "warning" | "info";
    message: string;
    node_id?: string;
    blocking: boolean;
  }>;
  resolved_execution: {
    genesis?: boolean;
    execution_mode?: DraftExecutionMode;
    compare_source_available?: boolean;
    rerun_from_run_id?: string;
    rerun_from_model_node_id?: string;
    rerun_from_op_node_id?: string;
  };
  validated_execution_mode?: DraftExecutionMode;
  validated_draft_hash?: string;
  validated_at: string;
};

export type DraftExecutionResult = {
  ok: boolean;
  run_id: string;
  draft_id: string;
  executed_draft_hash: string;
  execution_mode: DraftExecutionMode;
  deduped?: boolean;
  produced_lineage: {
    genesis?: boolean;
    execution_mode?: DraftExecutionMode;
    rerun_from_run_id?: string;
    rerun_from_model_node_id?: string;
    rerun_from_op_node_id?: string;
  };
  focus: {
    status: "ready" | "pending_index";
    run_id: string;
    target_model_node_id?: string;
    poll?: {
      genesis?: boolean;
      execution_mode?: DraftExecutionMode;
      rerun_from_run_id?: string;
      rerun_from_model_node_id?: string;
      rerun_from_op_node_id?: string;
    };
  };
};

export type PipelineDraftFromNodeRequest = {
  source_run_id: string;
  source_model_node_id: string;
  source_op_node_id: string;
  source_node_hash: string;
  source_forest_node_key?: string;
  source_context_fingerprint: string;
};

export type PipelineDraftPatchRequest = {
  model_node_id: string;
  base_draft_hash: string;
  params: Record<string, unknown>;
};

export type PipelineDraftExecuteRequest = {
  validated_draft_hash: string;
  execution_mode: DraftExecutionMode;
  idempotency_key?: string;
};

function draftUrl(projectRoot: string, path: string): string {
  return apiUrl(`${path}?project_root=${encodeURIComponent(projectRoot)}`);
}

export async function createPipelineDraftFromNode(
  projectRoot: string,
  body: PipelineDraftFromNodeRequest,
): Promise<PipelineDraftResponse> {
  const response = await fetch(draftUrl(projectRoot, "/pipeline-drafts/from-node"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<PipelineDraftResponse>(response);
}

export async function getPipelineDraft(
  projectRoot: string,
  draftId: string,
): Promise<PipelineDraftResponse> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${encodeURIComponent(draftId)}`),
  );
  return readResponse<PipelineDraftResponse>(response);
}

export async function patchPipelineDraftParams(
  projectRoot: string,
  draftId: string,
  body: PipelineDraftPatchRequest,
): Promise<PipelineDraftResponse> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${encodeURIComponent(draftId)}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readResponse<PipelineDraftResponse>(response);
}

export async function validatePipelineDraft(
  projectRoot: string,
  draftId: string,
  executionMode: DraftExecutionMode = "rerun_child",
): Promise<DraftValidationResult> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${encodeURIComponent(draftId)}/validate`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ execution_mode: executionMode }),
    },
  );
  return readResponse<DraftValidationResult>(response);
}

export async function executePipelineDraft(
  projectRoot: string,
  draftId: string,
  body: PipelineDraftExecuteRequest,
): Promise<DraftExecutionResult> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${encodeURIComponent(draftId)}/execute`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readResponse<DraftExecutionResult>(response);
}

export type PipelineDraftSummary = {
  draft_id: string;
  status: string;
  model_type?: string | null;
  source_run_id?: string | null;
  source_model_node_id?: string | null;
  source_op_node_id?: string | null;
  source_node_hash?: string | null;
  draft_hash: string;
  updated_at?: string | null;
};

export async function listPipelineDrafts(
  projectRoot: string,
): Promise<PipelineDraftSummary[]> {
  const response = await fetch(draftUrl(projectRoot, "/pipeline-drafts"));
  const body = await readResponse<{ drafts: PipelineDraftSummary[] }>(response);
  return body.drafts;
}

export async function deletePipelineDraft(
  projectRoot: string,
  draftId: string,
): Promise<void> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${encodeURIComponent(draftId)}`),
    { method: "DELETE" },
  );
  await readResponse<{ ok: boolean }>(response);
}

// ── v1.6.8 — graph-native genesis (uploads / genesis draft / node patch / project forest) ──

export type UploadResult = { sha256: string; filename: string };

/** Upload a dataset file standalone (POST /uploads, multipart form).
 *  Content-addressable: the server stores by sha256 so genesis draft chains
 *  fully rehydrate after reload. */
export async function uploadDataset(
  projectRoot: string,
  file: File,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("file", file);
  const response = await fetch(apiUrl("/uploads"), {
    method: "POST",
    body: form,
  });
  return readResponse<UploadResult>(response);
}

export type PipelineDraftGenesisRequest = {
  upload_sha256: string;
  filename: string;
  sheet_names: string[];
  columns: string[];
};

/** Create a parentless genesis draft chain (source → table → model). */
export async function createGenesisDraft(
  projectRoot: string,
  body: PipelineDraftGenesisRequest,
): Promise<PipelineDraftResponse> {
  const response = await fetch(draftUrl(projectRoot, "/pipeline-drafts/genesis"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<PipelineDraftResponse>(response);
}

export type DraftNodePatchRequest = {
  params: Record<string, unknown>;
  columns?: string[];
};

/** Configure one genesis draft node in place (PATCH .../nodes/{nodeId}).
 *  `columns` applies to table nodes only. */
export async function patchDraftNode(
  projectRoot: string,
  draftId: string,
  nodeId: string,
  body: DraftNodePatchRequest,
): Promise<PipelineDraftResponse> {
  const response = await fetch(
    draftUrl(
      projectRoot,
      `/pipeline-drafts/${encodeURIComponent(draftId)}/nodes/${encodeURIComponent(nodeId)}`,
    ),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readResponse<PipelineDraftResponse>(response);
}

/** Fetch the project-level forest (GET /graph — union of all family
 *  head-sets; empty forest for zero-run projects). Body shape is parity with
 *  the per-run headset view, so it feeds the same adaptHeadSet. */
export async function fetchProjectForest(
  projectRoot: string,
): Promise<HeadSetResponse> {
  const response = await fetch(
    apiUrl(`/graph?project_root=${encodeURIComponent(projectRoot)}`),
  );
  return readResponse<HeadSetResponse>(response);
}

// ── v1.6.1 — head-set (cross-run forest) graph + node rerun ──

/** Fetch the family head-set (union DAG across the rerun forest). */
export async function getRunGraphHeadSet(
  projectRoot: string,
  runId: string,
): Promise<HeadSetResponse> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/graph?project_root=${encodeURIComponent(
      projectRoot,
    )}&view=headset`,
  );
  const response = await fetch(url);
  return readResponse<HeadSetResponse>(response);
}

export interface NodeWriteOperationRequestV1 {
  request_id: string;
  operation: "rerun";
  context_version: "node-operation-context/v1";
  context_fingerprint: string;
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  forest_node_key: string;
  owner_resolution: string;
  active_head_run_id: string | null;
  op_overrides: Record<string, unknown>;
  manual_patch?: ManualRerunPatch;
  rerun_reason?: string;
}

export interface RerunResponseV1 {
  run_id: string;
  new_run_id: string;
  new_active_head_id: string;
  focus: { forest_node_key: string; op_node_id: string; node_hash: string } | null;
  rerun_from: {
    owner_run_id: string;
    op_node_id: string;
    node_hash: string | null;
    forest_node_key: string | null;
  };
  accepted_context?: {
    context_version: "node-operation-context/v1";
    context_fingerprint: string;
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    validated_at: string;
  };
  produced_lineage?: {
    produced_owner_run_id: string;
    produced_op_node_id?: string | null;
    produced_node_hash?: string | null;
    rerun_request_id: string;
    rerun_from: {
      owner_run_id: string;
      op_node_id: string;
      node_hash: string;
      context_fingerprint: string;
      patch_id?: string;
      rerun_request_id: string;
    };
    status: "indexed" | "pending_index";
  } | null;
}

export interface LegacyRerunFromNodeArgs {
  fromNode: string;
  opOverrides: Record<string, unknown>;
  rerunReason?: string;
}

function isNodeWriteOperationRequestV1(
  args: LegacyRerunFromNodeArgs | NodeWriteOperationRequestV1,
): args is NodeWriteOperationRequestV1 {
  return (
    "operation" in args &&
    args.operation === "rerun" &&
    "context_version" in args &&
    args.context_version === "node-operation-context/v1"
  );
}

/** Create a child run by editing one node's operation (POST /runs/{id}/rerun).
 *  Legacy callers may still pass `fromNode`; context-driven callers submit the
 *  validated NodeOperationContext write target. */
export async function rerunFromNode(
  projectRoot: string,
  runId: string,
  args: LegacyRerunFromNodeArgs | NodeWriteOperationRequestV1,
): Promise<RerunResponseV1> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/rerun?project_root=${encodeURIComponent(projectRoot)}`,
  );
  const body = isNodeWriteOperationRequestV1(args)
    ? {
        ...args,
        from_node: args.op_node_id,
        rerun_reason: args.rerun_reason ?? "manual_override",
      }
    : {
        from_node: args.fromNode,
        op_overrides: args.opOverrides,
        rerun_reason: args.rerunReason ?? "manual_override",
      };
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<RerunResponseV1>(response);
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
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/events?project_root=${encodeURIComponent(projectRoot)}`,
  );
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

// ── v1.8 slice C: durable comparison nodes ──
// A comparison is stored server-side and projected into the forest as a node
// joining its two endpoints, so a conclusion survives a reload.

export type CompareNodeEndpoint = {
  run_id: string;
  node_id: string;
  node_hash: string;
  forest_node_key: string;
};

export type CompareNodeRecord = {
  compare_id: string;
  schema_id: string;
  left: CompareNodeEndpoint;
  right: CompareNodeEndpoint;
  relation: "ancestor_descendant" | "unrelated";
  created_at: string;
  packet: Record<string, unknown>;
};

export async function createCompareNode(
  projectRoot: string,
  left: { runId: string; nodeId: string },
  right: { runId: string; nodeId: string },
): Promise<CompareNodeRecord> {
  const response = await fetch(
    apiUrl(`/compare-nodes?project_root=${encodeURIComponent(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        left: { run_id: left.runId, node_id: left.nodeId },
        right: { run_id: right.runId, node_id: right.nodeId },
      }),
    },
  );
  return readResponse<CompareNodeRecord>(response);
}

export async function deleteCompareNode(
  projectRoot: string,
  compareId: string,
): Promise<{ deleted: string }> {
  const response = await fetch(
    apiUrl(
      `/compare-nodes/${encodeURIComponent(compareId)}?project_root=${encodeURIComponent(projectRoot)}`,
    ),
    { method: "DELETE" },
  );
  return readResponse<{ deleted: string }>(response);
}
