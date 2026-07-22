/**
 * v1.8.1 Notebook contracts, as the UI lane consumes them.
 *
 * These are read-only mirrors of the Integration-owned packets locked in
 * `backend/workbench/contracts/agent/notebook_option.py`. Nothing here derives
 * a statistical quantity, a diagnostic or a verdict: every field rendered by
 * this lane is a field the backend stated. The parsers exist so that a packet
 * which does not match the lock fails loudly at the boundary instead of being
 * coerced into a half-populated card (ADR-PD-001 §7C).
 */

export const NOTEBOOK_OPTION_CONTRACT_VERSION = "1.0";
export const OPTION_EXECUTION_CONTRACT_VERSION = "1.0";
export const ARTIFACT_CONTRACT_VERSION = "1.0";
export const ETS_RESULT_CONTRACT_VERSION = "1.0";

export const LIFECYCLE_STATUSES = [
  "proposed",
  "deferred",
  "selected",
  "executing",
  "executed",
  "rejected",
  "archived",
] as const;
export const FRESHNESS_STATUSES = ["fresh", "stale", "revalidating"] as const;
export const VALIDATION_STATUSES = ["valid", "invalid", "unvalidated"] as const;
export const RISK_LEVELS = ["low", "medium", "high"] as const;

export type LifecycleStatus = (typeof LIFECYCLE_STATUSES)[number];
export type FreshnessStatus = (typeof FRESHNESS_STATUSES)[number];
export type ValidationStatus = (typeof VALIDATION_STATUSES)[number];
export type RiskLevel = (typeof RISK_LEVELS)[number];

export class NotebookContractError extends Error {}

type Raw = Record<string, unknown>;

function asRecord(value: unknown, field: string): Raw {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new NotebookContractError(`${field} must be an object`);
  }
  return value as Raw;
}

function requireString(raw: Raw, field: string, path: string): string {
  const value = raw[field];
  if (typeof value !== "string" || value.length === 0) {
    throw new NotebookContractError(`${path}.${field} must be a non-empty string`);
  }
  return value;
}

function requireInt(raw: Raw, field: string, path: string): number {
  const value = raw[field];
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new NotebookContractError(`${path}.${field} must be an integer`);
  }
  return value;
}

function requireNumber(raw: Raw, field: string, path: string): number {
  const value = raw[field];
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new NotebookContractError(`${path}.${field} must be a number`);
  }
  return value;
}

function requireBoolean(raw: Raw, field: string, path: string): boolean {
  const value = raw[field];
  if (typeof value !== "boolean") {
    throw new NotebookContractError(`${path}.${field} must be a boolean`);
  }
  return value;
}

function optionalString(raw: Raw, field: string, path: string): string | null {
  const value = raw[field];
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") {
    throw new NotebookContractError(`${path}.${field} must be a string or null`);
  }
  return value;
}

function optionalInt(raw: Raw, field: string, path: string): number | null {
  const value = raw[field];
  if (value === null || value === undefined) return null;
  return requireInt(raw, field, path);
}

function requireChoice<T extends string>(
  raw: Raw,
  field: string,
  allowed: readonly T[],
  path: string,
): T {
  const value = requireString(raw, field, path);
  if (!(allowed as readonly string[]).includes(value)) {
    throw new NotebookContractError(
      `${path}.${field} must be one of ${allowed.join(", ")}, got ${value}`,
    );
  }
  return value as T;
}

function requireStringArray(raw: Raw, field: string, path: string): string[] {
  const value = raw[field];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new NotebookContractError(`${path}.${field} must be an array of strings`);
  }
  return value as string[];
}

function requireVersion(raw: Raw, expected: string, packet: string): string {
  const value = requireString(raw, "contract_version", packet);
  if (value !== expected) {
    throw new NotebookContractError(
      `${packet} contract_version must be ${expected}, got ${value}`,
    );
  }
  return value;
}

/* ------------------------------------------------------------------ */
/* ArtifactContract@1.0                                                */
/* ------------------------------------------------------------------ */

export interface ExpectedArtifact {
  artifact_id: string;
  artifact_type: string;
  required: boolean;
  count: number;
  step: string | null;
}

export interface ArtifactContract {
  contract_version: string;
  expected: ExpectedArtifact[];
  /** The dimensions this contract's validator actually compares. */
  checked_dimensions: string[];
  /**
   * Dimensions the validator cannot compare in v1.8.1. Rendered verbatim so a
   * reader can never mistake "we did not look at payload schemas" for
   * "payload schemas were valid" (spec §5.4).
   */
  not_evaluated_dimensions: string[];
}

export function parseExpectedArtifact(value: unknown, index: number): ExpectedArtifact {
  const path = `expected[${index}]`;
  const raw = asRecord(value, path);
  if ("schema_ref" in raw) {
    // Spec §5.3: accepting the field and quietly not checking it would let a
    // caller believe a schema requirement had been handled.
    throw new NotebookContractError(
      `ARTIFACT_SCHEMA_CONTRACT_UNSUPPORTED: ${path} declares schema_ref, which v1.8.1 cannot evaluate`,
    );
  }
  return {
    artifact_id: requireString(raw, "artifact_id", path),
    artifact_type: requireString(raw, "artifact_type", path),
    required: requireBoolean(raw, "required", path),
    count: requireInt(raw, "count", path),
    step: optionalString(raw, "step", path),
  };
}

export function parseArtifactContract(value: unknown): ArtifactContract {
  const raw = asRecord(value, "artifact_contract");
  requireVersion(raw, ARTIFACT_CONTRACT_VERSION, "ArtifactContract");
  const expected = raw.expected;
  if (!Array.isArray(expected)) {
    throw new NotebookContractError("artifact_contract.expected must be an array");
  }
  const parsed = expected.map(parseExpectedArtifact);
  const ids = parsed.map((item) => item.artifact_id);
  if (new Set(ids).size !== ids.length) {
    throw new NotebookContractError("artifact_contract.expected artifact_id values must be unique");
  }
  return {
    contract_version: ARTIFACT_CONTRACT_VERSION,
    expected: parsed,
    checked_dimensions: requireStringArray(raw, "checked_dimensions", "artifact_contract"),
    not_evaluated_dimensions: requireStringArray(
      raw,
      "not_evaluated_dimensions",
      "artifact_contract",
    ),
  };
}

/* ------------------------------------------------------------------ */
/* NotebookOptionRevision@1.0                                          */
/* ------------------------------------------------------------------ */

export interface NotebookOptionRevision {
  contract_version: string;
  option_id: string;
  option_revision: number;
  notebook_id: string;
  run_family_id: string;
  generation_context_id: string;
  /** What the agent saw. Never used to gate execution (spec §4.0). */
  generation_context_hash: string;
  /** The only fingerprint that gates execution (spec §4.0). */
  freshness_dependency_fingerprint: string;
  typed_proposal_id: string;
  typed_proposal_revision: number;
  artifact_contract: ArtifactContract;
  rationale: string;
  assumptions: string[];
  risk_level: RiskLevel;
  lifecycle_status: LifecycleStatus;
  freshness_status: FreshnessStatus;
  validation_status: ValidationStatus;
  rank: number;
  batch_id: string;
  created_at: string;
  supersedes_option_revision: number | null;
}

export function parseNotebookOptionRevision(value: unknown): NotebookOptionRevision {
  const raw = asRecord(value, "notebook_option_revision");
  requireVersion(raw, NOTEBOOK_OPTION_CONTRACT_VERSION, "NotebookOptionRevision");
  const path = "notebook_option_revision";
  return {
    contract_version: NOTEBOOK_OPTION_CONTRACT_VERSION,
    option_id: requireString(raw, "option_id", path),
    option_revision: requireInt(raw, "option_revision", path),
    notebook_id: requireString(raw, "notebook_id", path),
    run_family_id: requireString(raw, "run_family_id", path),
    generation_context_id: requireString(raw, "generation_context_id", path),
    generation_context_hash: requireString(raw, "generation_context_hash", path),
    freshness_dependency_fingerprint: requireString(
      raw,
      "freshness_dependency_fingerprint",
      path,
    ),
    typed_proposal_id: requireString(raw, "typed_proposal_id", path),
    typed_proposal_revision: requireInt(raw, "typed_proposal_revision", path),
    artifact_contract: parseArtifactContract(raw.artifact_contract),
    rationale: requireString(raw, "rationale", path),
    assumptions: requireStringArray(raw, "assumptions", path),
    risk_level: requireChoice(raw, "risk_level", RISK_LEVELS, path),
    lifecycle_status: requireChoice(raw, "lifecycle_status", LIFECYCLE_STATUSES, path),
    freshness_status: requireChoice(raw, "freshness_status", FRESHNESS_STATUSES, path),
    validation_status: requireChoice(raw, "validation_status", VALIDATION_STATUSES, path),
    rank: requireInt(raw, "rank", path),
    batch_id: requireString(raw, "batch_id", path),
    created_at: requireString(raw, "created_at", path),
    supersedes_option_revision: optionalInt(raw, "supersedes_option_revision", path),
  };
}

/* ------------------------------------------------------------------ */
/* OptionExecution@1.0                                                 */
/* ------------------------------------------------------------------ */

export interface OptionExecution {
  contract_version: string;
  option_id: string;
  option_revision: number;
  proposal_id: string;
  proposal_revision: number;
  freshness_dependency_fingerprint: string;
  generation_context_id: string;
  run_id: string | null;
}

export function parseOptionExecution(value: unknown): OptionExecution {
  const raw = asRecord(value, "option_execution");
  requireVersion(raw, OPTION_EXECUTION_CONTRACT_VERSION, "OptionExecution");
  const path = "option_execution";
  return {
    contract_version: OPTION_EXECUTION_CONTRACT_VERSION,
    option_id: requireString(raw, "option_id", path),
    option_revision: requireInt(raw, "option_revision", path),
    proposal_id: requireString(raw, "proposal_id", path),
    proposal_revision: requireInt(raw, "proposal_revision", path),
    freshness_dependency_fingerprint: requireString(
      raw,
      "freshness_dependency_fingerprint",
      path,
    ),
    generation_context_id: requireString(raw, "generation_context_id", path),
    run_id: optionalString(raw, "run_id", path),
  };
}

/* ------------------------------------------------------------------ */
/* ETSResultContract@1.0 (rendered verbatim, never recomputed)          */
/* ------------------------------------------------------------------ */

export interface EtsSpecification {
  error: string;
  trend: string | null;
  seasonal: string | null;
  seasonal_periods: number | null;
  damped_trend: boolean;
  canonical: string;
}

export interface EtsResult {
  contract_version: string;
  model_type: "time_series.ets";
  specification: EtsSpecification;
  endog: string;
  n_obs: number;
  n_excluded: number;
  exclusion_reasons: Record<string, number>;
  params: Record<string, number>;
  aic: number;
  bic: number;
  log_likelihood: number;
  sigma2: number;
  convergence_code: string;
  fit_method: string;
  result_identity: string;
}

function parseNumberMap(value: unknown, path: string): Record<string, number> {
  const raw = asRecord(value, path);
  const out: Record<string, number> = {};
  for (const [key, item] of Object.entries(raw)) {
    if (typeof item !== "number") {
      throw new NotebookContractError(`${path}.${key} must be a number`);
    }
    out[key] = item;
  }
  return out;
}

export function parseEtsResult(value: unknown): EtsResult {
  const raw = asRecord(value, "ets_result");
  requireVersion(raw, ETS_RESULT_CONTRACT_VERSION, "ETSResultContract");
  const path = "ets_result";
  const modelType = requireString(raw, "model_type", path);
  if (modelType !== "time_series.ets") {
    throw new NotebookContractError(
      `${path}.model_type must be time_series.ets, got ${modelType}`,
    );
  }
  const specRaw = asRecord(raw.specification, `${path}.specification`);
  const specPath = `${path}.specification`;
  return {
    contract_version: ETS_RESULT_CONTRACT_VERSION,
    model_type: "time_series.ets",
    specification: {
      error: requireString(specRaw, "error", specPath),
      trend: optionalString(specRaw, "trend", specPath),
      seasonal: optionalString(specRaw, "seasonal", specPath),
      seasonal_periods: optionalInt(specRaw, "seasonal_periods", specPath),
      damped_trend: requireBoolean(specRaw, "damped_trend", specPath),
      canonical: requireString(specRaw, "canonical", specPath),
    },
    endog: requireString(raw, "endog", path),
    n_obs: requireInt(raw, "n_obs", path),
    n_excluded: requireInt(raw, "n_excluded", path),
    exclusion_reasons: parseNumberMap(raw.exclusion_reasons, `${path}.exclusion_reasons`),
    params: parseNumberMap(raw.params, `${path}.params`),
    aic: requireNumber(raw, "aic", path),
    bic: requireNumber(raw, "bic", path),
    log_likelihood: requireNumber(raw, "log_likelihood", path),
    sigma2: requireNumber(raw, "sigma2", path),
    convergence_code: requireString(raw, "convergence_code", path),
    fit_method: requireString(raw, "fit_method", path),
    result_identity: requireString(raw, "result_identity", path),
  };
}

/* ------------------------------------------------------------------ */
/* Artifact contract outcome (post-execution verdict, backend-supplied) */
/* ------------------------------------------------------------------ */

export interface ObservedArtifact {
  artifact_id: string;
  observed_count: number;
  satisfied: boolean;
  issue_code: string | null;
}

/**
 * Spec §5.3: execution success and contract satisfaction are two dimensions.
 * Both come from the backend; the UI never infers one from the other.
 */
export interface ArtifactContractOutcome {
  execution_status: "pending" | "running" | "succeeded" | "failed";
  validation_status: "pending" | "passed" | "passed_with_warnings" | "failed";
  validation_profile: string;
  checked_dimensions: string[];
  not_evaluated_dimensions: string[];
  observed: ObservedArtifact[];
}

/* ------------------------------------------------------------------ */
/* Visible slice: what the agent saw, and what happened                */
/*                                                                     */
/* PROVISIONAL — see CCR-C1. `NotebookPlanningContextV1` (spec §12.3)   */
/* and `agent-trace-event/v1` (spec §13.2) have no canonical fixture in */
/* tests/fixtures/contracts/v181/. The shapes below are read from the   */
/* spec text; they must be replaced by the locked packet when Gate 2/3  */
/* land.                                                                */
/* ------------------------------------------------------------------ */

export interface ContextOmission {
  section: string;
  included_count: number;
  available_count: number;
  reason: string;
  /** Per-type breakdown of what was dropped, e.g. 36 time_series_json. */
  omitted_by_type: { artifact_type: string; count: number }[];
}

export interface BudgetSection {
  section: string;
  used_bytes: number;
  budget_bytes: number;
}

export interface BudgetReport {
  sections: BudgetSection[];
  total_used_bytes: number;
  total_budget_bytes: number;
}

export interface SourceManifestEntry {
  source_ref: string;
  revision: number;
  selection_reason: string;
  /** True for the sections spec §12.3 forbids truncating. */
  never_truncated: boolean;
}

export interface TraceEvent {
  event_id: string;
  sequence: number;
  event_type: string;
  occurred_at: string;
  summary: string;
}

export interface NotebookContextSlice {
  context_id: string;
  context_profile: string;
  generation_context_hash: string;
  freshness_dependency_fingerprint: string;
  artifact_type_counts: { artifact_type: string; count: number }[];
  omissions: ContextOmission[];
  budget_report: BudgetReport;
  source_manifest: SourceManifestEntry[];
  trace: TraceEvent[];
}

/* ------------------------------------------------------------------ */
/* View model                                                          */
/* ------------------------------------------------------------------ */

export interface NarrativeEntry {
  entry_id: string;
  kind: "user" | "agent" | "system";
  text: string;
  occurred_at: string;
}

export interface NotebookSelection {
  text: string;
  source_label: string;
  source_ref: string;
}

export interface PlanDiffLine {
  field: string;
  from: string | null;
  to: string | null;
}

export interface PendingConfirmation {
  option: NotebookOptionRevision;
  execution: OptionExecution;
  plan_diff: PlanDiffLine[];
}

export interface NotebookData {
  notebook_id: string;
  run_family_id: string;
  narrative: NarrativeEntry[];
  options: NotebookOptionRevision[];
  contextSlice: NotebookContextSlice | null;
  confirmation: PendingConfirmation | null;
  execution: OptionExecution | null;
  result: EtsResult | null;
  outcome?: ArtifactContractOutcome | null;
  selection: NotebookSelection | null;
}

export interface NotebookErrorPacket {
  code: string;
  message: string;
}

export interface NotebookLoadingView {
  status: "loading";
}
export interface NotebookErrorView {
  status: "error";
  error: NotebookErrorPacket;
}
export interface NotebookReadyView {
  status: "ready";
  notebook: NotebookData;
}

export type NotebookView = NotebookLoadingView | NotebookErrorView | NotebookReadyView;

/** Spec §6: an option batch is capped at three. */
export const MAX_OPTIONS_PER_BATCH = 3;
