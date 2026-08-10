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

import type { DomainMemoryRetrievalProjection } from "./domainMemoryContracts";

export const NOTEBOOK_OPTION_CONTRACT_VERSION = "1.1";
export const NOTEBOOK_OPTION_V12_CONTRACT_VERSION = "1.2";
export const NOTEBOOK_OPTION_V13_CONTRACT_VERSION = "1.3";
export const NOTEBOOK_OPTION_V14_CONTRACT_VERSION = "1.4";
export const NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION = "1.0";
export const OPTION_EXECUTION_CONTRACT_VERSION = "1.1";
export const OPTION_EXECUTION_LEGACY_CONTRACT_VERSION = "1.0";
export const RECOMMENDATION_DECISION_CONTRACT_VERSION = "1.0";
export const OPTION_MATERIALIZATION_CONTRACT_VERSION = "1.0";
export const ARTIFACT_CONTRACT_VERSION = "1.0";
export const ETS_RESULT_CONTRACT_VERSION = "1.1";

export const LIFECYCLE_STATUSES = [
  "proposed",
  "deferred",
  "selected",
  "executing",
  "executed",
  "rejected",
  "archived",
  "materialized",
] as const;
export const LEGACY_LIFECYCLE_STATUSES = [
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
export const RECOMMENDATION_OUTCOMES = [
  "recommended",
  "tied",
  "insufficient_evidence",
] as const;

export type LifecycleStatus = (typeof LIFECYCLE_STATUSES)[number];
export type FreshnessStatus = (typeof FRESHNESS_STATUSES)[number];
export type ValidationStatus = (typeof VALIDATION_STATUSES)[number];
export type RiskLevel = (typeof RISK_LEVELS)[number];
export type RecommendationOutcome = (typeof RECOMMENDATION_OUTCOMES)[number];

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

function requirePositiveInt(raw: Raw, field: string, path: string): number {
  const value = requireInt(raw, field, path);
  if (value < 1) {
    throw new NotebookContractError(`${path}.${field} must be an integer >= 1`);
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

function optionalNonEmptyString(raw: Raw, field: string, path: string): string | null {
  const value = raw[field];
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || value.length === 0) {
    throw new NotebookContractError(`${path}.${field} must be a non-empty string or null`);
  }
  return value;
}

function optionalInt(raw: Raw, field: string, path: string): number | null {
  const value = raw[field];
  if (value === null || value === undefined) return null;
  return requireInt(raw, field, path);
}

function optionalPositiveInt(raw: Raw, field: string, path: string): number | null {
  const value = raw[field];
  if (value === null || value === undefined) return null;
  return requirePositiveInt(raw, field, path);
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

function requireKnownKeys(
  raw: Raw,
  required: readonly string[],
  optional: readonly string[],
  path: string,
): void {
  const allowed = new Set([...required, ...optional]);
  const unknown = Object.keys(raw).filter((key) => !allowed.has(key));
  const missing = required.filter((key) => !(key in raw));
  if (unknown.length > 0) {
    throw new NotebookContractError(`${path} has unknown field(s): ${unknown.sort().join(", ")}`);
  }
  if (missing.length > 0) {
    throw new NotebookContractError(`${path} is missing required field(s): ${missing.join(", ")}`);
  }
}

function requireExactKeys(raw: Raw, keys: readonly string[], path: string): void {
  requireKnownKeys(raw, keys, [], path);
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
  requireExactKeys(raw, ["artifact_id", "artifact_type", "required", "count", "step"], path);
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
  requireExactKeys(
    raw,
    ["contract_version", "expected", "checked_dimensions", "not_evaluated_dimensions"],
    "artifact_contract",
  );
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
/* NotebookOptionRevision@1.0 and @1.1                                 */
/* ------------------------------------------------------------------ */

interface NotebookOptionRevisionBase {
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

export interface EvidenceRef {
  evidence_id: string;
  result_hash: string;
  source_refs: string[];
}

/** Immutable provenance for a server-applied, user-reviewable Draft default. */
export interface MemoryDefaultSource {
  memory_id: string;
  revision: number;
  target_ref: string;
  target_label?: string;
  method_risk?: RiskLevel;
  restore_value?: string | null;
}

export type CapabilityExecutionMode =
  | "materialize_only"
  | "confirm_and_execute"
  | "experimental_confirm_and_execute";

/** Common consumer shape. New parser outputs are the narrower union below. */
export interface NotebookOptionRevision extends NotebookOptionRevisionBase {
  contract_version: "1.0" | "1.1" | "1.2" | "1.3" | "1.4";
  lifecycle_projection: LifecycleStatus | "legacy_unverified";
  materializable: boolean;
  evidence_refs?: EvidenceRef[];
  comparative_claims?: string[];
  recommendation_decision_id?: string;
  recommendation_status?: RecommendationOutcome;
  capability_resolution_binding_ref?: string;
  execution_modes?: ReadonlyArray<CapabilityExecutionMode>;
  confirmAndExecute?: boolean;
  /** Server-declared high-risk local execution; never inferred from UI state. */
  experimentalExecution?: boolean;
  memory_default_sources?: MemoryDefaultSource[];
}

export interface LegacyNotebookOptionRevision extends NotebookOptionRevision {
  contract_version: "1.0";
  lifecycle_status: (typeof LEGACY_LIFECYCLE_STATUSES)[number];
  lifecycle_projection: "legacy_unverified";
  materializable: false;
  evidence_refs?: never;
  comparative_claims?: never;
  recommendation_decision_id?: never;
  recommendation_status?: never;
}

export interface NotebookOptionRevisionV11 extends NotebookOptionRevision {
  contract_version: "1.1";
  evidence_refs: EvidenceRef[];
  comparative_claims: string[];
  recommendation_decision_id: string;
  recommendation_status: RecommendationOutcome;
  lifecycle_projection: LifecycleStatus;
  materializable: true;
}

export interface NotebookOptionRevisionV12 extends Omit<NotebookOptionRevisionV11, "contract_version"> {
  contract_version: "1.2";
  capability_resolution_binding_ref: string;
  execution_modes: ReadonlyArray<CapabilityExecutionMode>;
  confirmAndExecute: boolean;
  experimentalExecution: boolean;
}

export interface NotebookOptionRevisionV13 extends Omit<
  NotebookOptionRevisionV11,
  "contract_version" | "memory_default_sources"
> {
  contract_version: "1.3";
  memory_default_sources: MemoryDefaultSource[];
}

export interface NotebookOptionRevisionV14 extends Omit<
  NotebookOptionRevisionV11,
  "contract_version" | "memory_default_sources"
> {
  contract_version: "1.4";
  memory_default_sources: Array<
    MemoryDefaultSource & {
      target_label: string;
      method_risk: RiskLevel;
      restore_value: string | null;
    }
  >;
}

export type ParsedNotebookOptionRevision =
  | LegacyNotebookOptionRevision
  | NotebookOptionRevisionV11
  | NotebookOptionRevisionV12
  | NotebookOptionRevisionV13
  | NotebookOptionRevisionV14;

const OPTION_BASE_REQUIRED_KEYS = [
  "option_id",
  "option_revision",
  "notebook_id",
  "run_family_id",
  "generation_context_id",
  "generation_context_hash",
  "freshness_dependency_fingerprint",
  "typed_proposal_id",
  "typed_proposal_revision",
  "artifact_contract",
  "risk_level",
  "lifecycle_status",
  "freshness_status",
  "validation_status",
  "rank",
  "batch_id",
  "created_at",
] as const;

const OPTION_BASE_OPTIONAL_KEYS = [
  "rationale",
  "assumptions",
  "supersedes_option_revision",
] as const;

const OPTION_BASE_KEYS = [...OPTION_BASE_REQUIRED_KEYS, ...OPTION_BASE_OPTIONAL_KEYS] as const;

function parseOptionBase(raw: Raw): NotebookOptionRevisionBase {
  const path = "notebook_option_revision";
  return {
    option_id: requireString(raw, "option_id", path),
    option_revision: requirePositiveInt(raw, "option_revision", path),
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
    typed_proposal_revision: requirePositiveInt(raw, "typed_proposal_revision", path),
    artifact_contract: parseArtifactContract(raw.artifact_contract),
    rationale: "rationale" in raw ? requireString(raw, "rationale", path) : "",
    assumptions: "assumptions" in raw ? requireStringArray(raw, "assumptions", path) : [],
    risk_level: requireChoice(raw, "risk_level", RISK_LEVELS, path),
    lifecycle_status: requireChoice(raw, "lifecycle_status", LIFECYCLE_STATUSES, path),
    freshness_status: requireChoice(raw, "freshness_status", FRESHNESS_STATUSES, path),
    validation_status: requireChoice(raw, "validation_status", VALIDATION_STATUSES, path),
    rank: requirePositiveInt(raw, "rank", path),
    batch_id: requireString(raw, "batch_id", path),
    created_at: requireString(raw, "created_at", path),
    supersedes_option_revision:
      "supersedes_option_revision" in raw
        ? optionalPositiveInt(raw, "supersedes_option_revision", path)
        : null,
  };
}

function parseEvidenceRef(value: unknown, index: number): EvidenceRef {
  const path = `notebook_option_revision.evidence_refs[${index}]`;
  const raw = asRecord(value, path);
  requireExactKeys(raw, ["evidence_id", "result_hash", "source_refs"], path);
  return {
    evidence_id: requireString(raw, "evidence_id", path),
    result_hash: requireString(raw, "result_hash", path),
    source_refs: requireStringArray(raw, "source_refs", path),
  };
}

function parseMemoryDefaultSource(
  value: unknown,
  index: number,
  requireDisplayMetadata = false,
): MemoryDefaultSource {
  const path = `notebook_option_revision.memory_default_sources[${index}]`;
  const raw = asRecord(value, path);
  const keys = ["memory_id", "revision", "target_ref"];
  if (requireDisplayMetadata) {
    requireExactKeys(
      raw,
      [...keys, "target_label", "method_risk", "restore_value"],
      path,
    );
  } else {
    requireExactKeys(raw, keys, path);
  }
  const source: MemoryDefaultSource = {
    memory_id: requireString(raw, "memory_id", path),
    revision: requirePositiveInt(raw, "revision", path),
    target_ref: requireString(raw, "target_ref", path),
  };
  if (requireDisplayMetadata) {
    source.target_label = requireString(raw, "target_label", path);
    source.method_risk = requireChoice(raw, "method_risk", RISK_LEVELS, path);
    source.restore_value = optionalString(raw, "restore_value", path);
  }
  return source;
}

export function parseNotebookOptionRevision(value: unknown): ParsedNotebookOptionRevision {
  const raw = asRecord(value, "notebook_option_revision");
  const hasVersion = "contract_version" in raw;
  const version = hasVersion
    ? requireString(raw, "contract_version", "NotebookOptionRevision")
    : NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION;
  if (version === NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION) {
    requireKnownKeys(
      raw,
      hasVersion
        ? ["contract_version", ...OPTION_BASE_REQUIRED_KEYS]
        : OPTION_BASE_REQUIRED_KEYS,
      OPTION_BASE_OPTIONAL_KEYS,
      "notebook_option_revision",
    );
    const base = parseOptionBase(raw);
    return {
      ...base,
      contract_version: NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION,
      lifecycle_status: requireChoice(
        raw,
        "lifecycle_status",
        LEGACY_LIFECYCLE_STATUSES,
        "notebook_option_revision",
      ),
      lifecycle_projection: "legacy_unverified",
      materializable: false,
    };
  }
  if (
    version !== NOTEBOOK_OPTION_CONTRACT_VERSION &&
    version !== NOTEBOOK_OPTION_V12_CONTRACT_VERSION &&
    version !== NOTEBOOK_OPTION_V13_CONTRACT_VERSION &&
    version !== NOTEBOOK_OPTION_V14_CONTRACT_VERSION
  ) {
    // Keep the v1.8.1 rejection wording for the historical 2.0 probe while
    // accepting the explicit v1.2 successor below.
    const supported = version === "2.0" ? "1.0 or 1.1" : "1.0, 1.1, 1.2, 1.3, or 1.4";
    throw new NotebookContractError(
      `NotebookOptionRevision contract_version must be ${supported}, got ${version}`,
    );
  }
  const isV12 = version === NOTEBOOK_OPTION_V12_CONTRACT_VERSION;
  const isV13 = version === NOTEBOOK_OPTION_V13_CONTRACT_VERSION;
  const isV14 = version === NOTEBOOK_OPTION_V14_CONTRACT_VERSION;
  requireExactKeys(
    raw,
    [
      "contract_version",
      ...OPTION_BASE_KEYS,
      "evidence_refs",
      "comparative_claims",
      "recommendation_decision_id",
      "recommendation_status",
      ...(isV12 ? ["capability_resolution_binding_ref", "execution_modes"] : []),
      ...(isV13 || isV14 ? ["memory_default_sources"] : []),
    ],
    "notebook_option_revision",
  );
  const evidence = raw.evidence_refs;
  if (!Array.isArray(evidence)) {
    throw new NotebookContractError("notebook_option_revision.evidence_refs must be an array");
  }
  const base = parseOptionBase(raw);
  const baseOption = {
    ...base,
    contract_version: "1.1" as const,
    evidence_refs: evidence.map(parseEvidenceRef),
    comparative_claims: requireStringArray(raw, "comparative_claims", "notebook_option_revision"),
    recommendation_decision_id: requireString(
      raw,
      "recommendation_decision_id",
      "notebook_option_revision",
    ),
    recommendation_status: requireChoice(
      raw,
      "recommendation_status",
      RECOMMENDATION_OUTCOMES,
      "notebook_option_revision",
    ),
    lifecycle_projection: base.lifecycle_status,
    materializable: true as const,
  };
  if (isV13 || isV14) {
    const sources = raw.memory_default_sources;
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new NotebookContractError(
        "notebook_option_revision.memory_default_sources must be a non-empty array",
      );
    }
    const parsedSources = sources.map((source, index) =>
      parseMemoryDefaultSource(source, index, isV14),
    );
    const sourceKeys = parsedSources.map(
      (source) => `${source.memory_id}:${source.revision}:${source.target_ref}`,
    );
    if (new Set(sourceKeys).size !== sourceKeys.length) {
      throw new NotebookContractError(
        "notebook_option_revision.memory_default_sources must be unique",
      );
    }
    if (isV14) {
      return {
        ...baseOption,
        contract_version: "1.4",
        memory_default_sources: parsedSources.map((source) => ({
          ...source,
          target_label: source.target_label as string,
          method_risk: source.method_risk as RiskLevel,
          restore_value: source.restore_value ?? null,
        })),
      };
    }
    return {
      ...baseOption,
      contract_version: "1.3",
      memory_default_sources: parsedSources,
    };
  }
  if (!isV12) return baseOption;

  const bindingRef = requireString(
    raw,
    "capability_resolution_binding_ref",
    "notebook_option_revision",
  );
  const executionModes = requireStringArray(raw, "execution_modes", "notebook_option_revision");
  const isExperimental = executionModes.includes("experimental_confirm_and_execute");
  if (
    executionModes.length === 0 ||
    executionModes[0] !== "materialize_only" ||
    new Set(executionModes).size !== executionModes.length ||
    executionModes.some(
      (mode) =>
        mode !== "materialize_only" &&
        mode !== "confirm_and_execute" &&
        mode !== "experimental_confirm_and_execute",
    ) ||
    executionModes.filter((mode) => mode !== "materialize_only").length > 1
  ) {
    throw new NotebookContractError(
      "notebook_option_revision.execution_modes must start with materialize_only and use known modes",
    );
  }
  if (isExperimental && base.risk_level !== "high") {
    throw new NotebookContractError(
      "experimental_confirm_and_execute is reserved for high-risk capabilities",
    );
  }
  return {
    ...baseOption,
    contract_version: "1.2",
    capability_resolution_binding_ref: bindingRef,
    execution_modes: executionModes as CapabilityExecutionMode[],
    confirmAndExecute:
      executionModes.includes("confirm_and_execute") || isExperimental,
    experimentalExecution: isExperimental,
  };
}

/* ------------------------------------------------------------------ */
/* RecommendationDecision@1.0                                          */
/* ------------------------------------------------------------------ */

export interface RecommendationDecision {
  contract_version: "1.0";
  recommendation_decision_id: string;
  batch_id: string;
  generation_context_hash: string;
  freshness_dependency_fingerprint: string;
  evidence_pack_hashes: string[];
  comparison_protocol_refs: string[];
  candidate_option_ids: string[];
  outcome: RecommendationOutcome;
  recommended_option_id: string | null;
  reason_refs: string[];
}

export function parseRecommendationDecision(value: unknown): RecommendationDecision {
  const raw = asRecord(value, "recommendation_decision");
  const path = "recommendation_decision";
  requireExactKeys(
    raw,
    [
      "contract_version",
      "recommendation_decision_id",
      "batch_id",
      "generation_context_hash",
      "freshness_dependency_fingerprint",
      "evidence_pack_hashes",
      "comparison_protocol_refs",
      "candidate_option_ids",
      "outcome",
      "recommended_option_id",
      "reason_refs",
    ],
    path,
  );
  requireVersion(raw, RECOMMENDATION_DECISION_CONTRACT_VERSION, "RecommendationDecision");
  const candidateOptionIds = requireStringArray(raw, "candidate_option_ids", path);
  if (new Set(candidateOptionIds).size !== candidateOptionIds.length) {
    throw new NotebookContractError(`${path}.candidate_option_ids must be unique`);
  }
  const outcome = requireChoice(raw, "outcome", RECOMMENDATION_OUTCOMES, path);
  const recommendedOptionId = optionalNonEmptyString(raw, "recommended_option_id", path);
  if (outcome === "recommended") {
    if (recommendedOptionId === null || !candidateOptionIds.includes(recommendedOptionId)) {
      throw new NotebookContractError(
        `${path}.recommended_option_id must name exactly one candidate for recommended outcomes`,
      );
    }
  } else if (recommendedOptionId !== null) {
    throw new NotebookContractError(
      `${path}.recommended_option_id must be null for tied or insufficient_evidence outcomes`,
    );
  }
  return {
    contract_version: RECOMMENDATION_DECISION_CONTRACT_VERSION,
    recommendation_decision_id: requireString(raw, "recommendation_decision_id", path),
    batch_id: requireString(raw, "batch_id", path),
    generation_context_hash: requireString(raw, "generation_context_hash", path),
    freshness_dependency_fingerprint: requireString(raw, "freshness_dependency_fingerprint", path),
    evidence_pack_hashes: requireStringArray(raw, "evidence_pack_hashes", path),
    comparison_protocol_refs: requireStringArray(raw, "comparison_protocol_refs", path),
    candidate_option_ids: candidateOptionIds,
    outcome,
    recommended_option_id: recommendedOptionId,
    reason_refs: requireStringArray(raw, "reason_refs", path),
  };
}

/* ------------------------------------------------------------------ */
/* OptionMaterialization@1.0                                           */
/* ------------------------------------------------------------------ */

export interface OptionMaterialization {
  contract_version: "1.0";
  materialization_id: string;
  option_id: string;
  option_revision: number;
  proposal_id: string;
  proposal_revision: number;
  freshness_dependency_fingerprint: string;
  generation_context_id: string;
  draft_id: string;
  draft_hash: string;
  draft_execution_mode: "rerun_child" | "genesis";
  source_run_id: string | null;
  source_model_node_id: string | null;
  source_op_node_id: string | null;
  source_node_hash: string | null;
  source_forest_node_key: string | null;
  source_context_fingerprint: string | null;
  dataset_upload_sha256: string | null;
  run_family_id: string;
}

const SOURCE_PIN_FIELDS = [
  "source_run_id",
  "source_model_node_id",
  "source_op_node_id",
  "source_node_hash",
  "source_forest_node_key",
  "source_context_fingerprint",
] as const;

export function parseOptionMaterialization(value: unknown): OptionMaterialization {
  const raw = asRecord(value, "option_materialization");
  const path = "option_materialization";
  requireExactKeys(
    raw,
    [
      "contract_version",
      "materialization_id",
      "option_id",
      "option_revision",
      "proposal_id",
      "proposal_revision",
      "freshness_dependency_fingerprint",
      "generation_context_id",
      "draft_id",
      "draft_hash",
      "draft_execution_mode",
      ...SOURCE_PIN_FIELDS,
      "dataset_upload_sha256",
      "run_family_id",
    ],
    path,
  );
  requireVersion(raw, OPTION_MATERIALIZATION_CONTRACT_VERSION, "OptionMaterialization");
  const draftExecutionMode = requireChoice(raw, "draft_execution_mode", ["rerun_child", "genesis"], path);
  const pins = Object.fromEntries(
    SOURCE_PIN_FIELDS.map((field) => [field, optionalNonEmptyString(raw, field, path)]),
  ) as Pick<OptionMaterialization, (typeof SOURCE_PIN_FIELDS)[number]>;
  const datasetUploadSha256 = optionalNonEmptyString(raw, "dataset_upload_sha256", path);
  if (draftExecutionMode === "rerun_child") {
    if (datasetUploadSha256 !== null || SOURCE_PIN_FIELDS.some((field) => pins[field] === null)) {
      throw new NotebookContractError(`${path}.rerun_child requires all source pins and no upload hash`);
    }
  } else if (datasetUploadSha256 === null || SOURCE_PIN_FIELDS.some((field) => pins[field] !== null)) {
    throw new NotebookContractError(`${path}.genesis requires an upload hash and no source pins`);
  }
  return {
    contract_version: OPTION_MATERIALIZATION_CONTRACT_VERSION,
    materialization_id: requireString(raw, "materialization_id", path),
    option_id: requireString(raw, "option_id", path),
    option_revision: requirePositiveInt(raw, "option_revision", path),
    proposal_id: requireString(raw, "proposal_id", path),
    proposal_revision: requirePositiveInt(raw, "proposal_revision", path),
    freshness_dependency_fingerprint: requireString(raw, "freshness_dependency_fingerprint", path),
    generation_context_id: requireString(raw, "generation_context_id", path),
    draft_id: requireString(raw, "draft_id", path),
    draft_hash: requireString(raw, "draft_hash", path),
    draft_execution_mode: draftExecutionMode,
    ...pins,
    dataset_upload_sha256: datasetUploadSha256,
    run_family_id: requireString(raw, "run_family_id", path),
  };
}

/* ------------------------------------------------------------------ */
/* OptionExecution@1.0 and @1.1                                       */
/* ------------------------------------------------------------------ */

interface OptionExecutionBase {
  option_id: string;
  option_revision: number;
  proposal_id: string;
  proposal_revision: number;
  freshness_dependency_fingerprint: string;
  generation_context_id: string;
}

/** Common consumer shape. New parser outputs are the narrower union below. */
export interface OptionExecution extends OptionExecutionBase {
  contract_version: "1.0" | "1.1";
  materialization_id?: string;
  draft_id?: string;
  draft_hash?: string;
  source_run_id?: string;
  run_id: string | null;
}

export interface LegacyOptionExecution extends OptionExecution {
  contract_version: "1.0";
  materialization_id?: never;
  draft_id?: never;
  draft_hash?: never;
  source_run_id?: never;
  run_id: string | null;
}

export interface OptionExecutionV11 extends OptionExecution {
  contract_version: "1.1";
  materialization_id: string;
  draft_id: string;
  draft_hash: string;
  source_run_id: string;
  run_id: string;
}

export type ParsedOptionExecution = LegacyOptionExecution | OptionExecutionV11;

const OPTION_EXECUTION_BASE_KEYS = [
  "option_id",
  "option_revision",
  "proposal_id",
  "proposal_revision",
  "freshness_dependency_fingerprint",
  "generation_context_id",
  "run_id",
] as const;

function parseOptionExecutionBase(raw: Raw): OptionExecutionBase {
  const path = "option_execution";
  return {
    option_id: requireString(raw, "option_id", path),
    option_revision: requirePositiveInt(raw, "option_revision", path),
    proposal_id: requireString(raw, "proposal_id", path),
    proposal_revision: requirePositiveInt(raw, "proposal_revision", path),
    freshness_dependency_fingerprint: requireString(
      raw,
      "freshness_dependency_fingerprint",
      path,
    ),
    generation_context_id: requireString(raw, "generation_context_id", path),
  };
}

export function parseOptionExecution(value: unknown): ParsedOptionExecution {
  const raw = asRecord(value, "option_execution");
  const version = requireString(raw, "contract_version", "OptionExecution");
  const path = "option_execution";
  if (version === OPTION_EXECUTION_LEGACY_CONTRACT_VERSION) {
    requireExactKeys(raw, ["contract_version", ...OPTION_EXECUTION_BASE_KEYS], path);
    return {
      ...parseOptionExecutionBase(raw),
      contract_version: OPTION_EXECUTION_LEGACY_CONTRACT_VERSION,
      run_id: optionalNonEmptyString(raw, "run_id", path),
    };
  }
  if (version !== OPTION_EXECUTION_CONTRACT_VERSION) {
    throw new NotebookContractError(`OptionExecution contract_version must be 1.0 or 1.1, got ${version}`);
  }
  requireExactKeys(
    raw,
    [
      "contract_version",
      ...OPTION_EXECUTION_BASE_KEYS,
      "materialization_id",
      "draft_id",
      "draft_hash",
      "source_run_id",
    ],
    path,
  );
  return {
    ...parseOptionExecutionBase(raw),
    contract_version: OPTION_EXECUTION_CONTRACT_VERSION,
    materialization_id: requireString(raw, "materialization_id", path),
    draft_id: requireString(raw, "draft_id", path),
    draft_hash: requireString(raw, "draft_hash", path),
    source_run_id: requireString(raw, "source_run_id", path),
    run_id: requireString(raw, "run_id", path),
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
  time_index_semantics: string;
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
    time_index_semantics: requireString(raw, "time_index_semantics", path),
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

/**
 * Model-neutral persisted execution projection.
 *
 * A Notebook cannot assume every model has an ETS-shaped result packet.  The
 * model-specific payload stays in Run artifacts; this packet is the durable
 * cross-model evidence that a run happened and whether its declared artifact
 * contract was committable.
 */
export interface NotebookExecutionIssue {
  code: string;
  severity: string;
  artifact_id: string;
  detail: string;
  observed_count: number | null;
}

/** Server-owned view used to validate a contract without hiding ambient run artifacts. */
export interface NotebookArtifactValidationScope {
  mode: string;
  ambient_artifact_ids: string[];
  ambient_artifact_count: number;
}

export interface NotebookExecutionResult {
  option_id: string;
  option_revision: number;
  run_id: string | null;
  execution_status: "pending" | "running" | "succeeded" | "failed";
  committed: boolean;
  artifact_validation: {
    contract_profile: string;
    validation_status: "passed" | "passed_with_warnings" | "failed";
    checked_dimensions: string[];
    not_evaluated_dimensions: string[];
    issues: NotebookExecutionIssue[];
    omitted_issue_count?: number;
  };
  /** Optional for compatibility with execution records written before v1.8.8. */
  artifact_validation_scope?: NotebookArtifactValidationScope;
  /** Server-produced receipt for a multi-branch workflow, never an inferred head. */
  workflow_execution?: WorkflowExecutionReceipt;
}

export interface WorkflowExecutionBranchRun {
  branch_id: string;
  run_id: string;
  artifact_ids: string[];
}

export interface WorkflowExecutionFailure {
  step_id: string;
  operation_id: string;
  status: "failed" | "blocked";
  error_code: string;
}

export interface WorkflowExecutionReceipt {
  workflow_id: string;
  plan_fingerprint: string;
  status: "completed" | "failed";
  branch_runs: WorkflowExecutionBranchRun[];
  post_estimation_artifact_ids: string[];
  /** Absent only on execution records persisted before this projection existed. */
  failed_steps?: WorkflowExecutionFailure[];
}

function parseWorkflowExecutionReceipt(value: unknown, path: string): WorkflowExecutionReceipt {
  const raw = asRecord(value, path);
  requireKnownKeys(
    raw,
    [
      "workflow_id",
      "plan_fingerprint",
      "status",
      "branch_runs",
      "post_estimation_artifact_ids",
    ],
    ["failed_steps"],
    path,
  );
  if (!Array.isArray(raw.branch_runs)) {
    throw new NotebookContractError(`${path}.branch_runs must be an array`);
  }
  return {
    workflow_id: requireString(raw, "workflow_id", path),
    plan_fingerprint: requireString(raw, "plan_fingerprint", path),
    status: requireChoice(raw, "status", ["completed", "failed"], path),
    branch_runs: raw.branch_runs.map((item, index) => {
      const branchPath = `${path}.branch_runs[${index}]`;
      const branch = asRecord(item, branchPath);
      requireExactKeys(branch, ["branch_id", "run_id", "artifact_ids"], branchPath);
      return {
        branch_id: requireString(branch, "branch_id", branchPath),
        run_id: requireString(branch, "run_id", branchPath),
        artifact_ids: requireStringArray(branch, "artifact_ids", branchPath),
      };
    }),
    post_estimation_artifact_ids: requireStringArray(
      raw,
      "post_estimation_artifact_ids",
      path,
    ),
    failed_steps:
      "failed_steps" in raw
        ? (() => {
            if (!Array.isArray(raw.failed_steps)) {
              throw new NotebookContractError(`${path}.failed_steps must be an array`);
            }
            return raw.failed_steps.map((item, index) => {
              const failurePath = `${path}.failed_steps[${index}]`;
              const failure = asRecord(item, failurePath);
              requireExactKeys(
                failure,
                ["step_id", "operation_id", "status", "error_code"],
                failurePath,
              );
              return {
                step_id: requireString(failure, "step_id", failurePath),
                operation_id: requireString(failure, "operation_id", failurePath),
                status: requireChoice(
                  failure,
                  "status",
                  ["failed", "blocked"],
                  failurePath,
                ),
                error_code: requireString(failure, "error_code", failurePath),
              };
            });
          })()
        : [],
  };
}

function parseArtifactValidationScope(
  value: unknown,
  path: string,
): NotebookArtifactValidationScope {
  const raw = asRecord(value, path);
  requireExactKeys(raw, ["mode", "ambient_artifact_ids", "ambient_artifact_count"], path);
  const ambientArtifactCount = requireInt(raw, "ambient_artifact_count", path);
  if (ambientArtifactCount < 0) {
    throw new NotebookContractError(`${path}.ambient_artifact_count must be >= 0`);
  }
  return {
    mode: requireString(raw, "mode", path),
    ambient_artifact_ids: requireStringArray(raw, "ambient_artifact_ids", path),
    ambient_artifact_count: ambientArtifactCount,
  };
}

export function parseNotebookExecutionResult(value: unknown): NotebookExecutionResult {
  const raw = asRecord(value, "notebook_execution_result");
  const path = "notebook_execution_result";
  requireKnownKeys(
    raw,
    [
      "option_id",
      "option_revision",
      "run_id",
      "execution_status",
      "committed",
      "artifact_validation",
    ],
    ["artifact_validation_scope", "workflow_execution"],
    path,
  );
  const validation = asRecord(raw.artifact_validation, `${path}.artifact_validation`);
  requireKnownKeys(
    validation,
    [
      "contract_profile",
      "validation_status",
      "checked_dimensions",
      "not_evaluated_dimensions",
      "issues",
    ],
    ["omitted_issue_count"],
    `${path}.artifact_validation`,
  );
  const issues = Array.isArray(validation.issues)
    ? validation.issues.map((value, index) => {
        const issue = asRecord(value, `${path}.artifact_validation.issues[${index}]`);
        return {
          code: requireString(issue, "code", `${path}.artifact_validation.issues[${index}]`),
          severity: requireString(
            issue,
            "severity",
            `${path}.artifact_validation.issues[${index}]`,
          ),
          artifact_id: requireString(
            issue,
            "artifact_id",
            `${path}.artifact_validation.issues[${index}]`,
          ),
          detail: requireString(
            issue,
            "detail",
            `${path}.artifact_validation.issues[${index}]`,
          ),
          observed_count: optionalInt(
            issue,
            "observed_count",
            `${path}.artifact_validation.issues[${index}]`,
          ),
        };
      })
    : (() => {
        throw new NotebookContractError(`${path}.artifact_validation.issues must be an array`);
      })();
  return {
    option_id: requireString(raw, "option_id", path),
    option_revision: requirePositiveInt(raw, "option_revision", path),
    run_id: optionalNonEmptyString(raw, "run_id", path),
    execution_status: requireChoice(
      raw,
      "execution_status",
      ["pending", "running", "succeeded", "failed"],
      path,
    ),
    committed: requireBoolean(raw, "committed", path),
    artifact_validation: {
      contract_profile: requireString(validation, "contract_profile", `${path}.artifact_validation`),
      validation_status: requireChoice(
        validation,
        "validation_status",
        ["passed", "passed_with_warnings", "failed"],
        `${path}.artifact_validation`,
      ),
      checked_dimensions: requireStringArray(
        validation,
        "checked_dimensions",
        `${path}.artifact_validation`,
      ),
      not_evaluated_dimensions: requireStringArray(
        validation,
        "not_evaluated_dimensions",
        `${path}.artifact_validation`,
      ),
      issues,
      omitted_issue_count:
        optionalInt(validation, "omitted_issue_count", `${path}.artifact_validation`) ?? 0,
    },
    artifact_validation_scope:
      "artifact_validation_scope" in raw
        ? parseArtifactValidationScope(
            raw.artifact_validation_scope,
            `${path}.artifact_validation_scope`,
          )
        : undefined,
    workflow_execution:
      "workflow_execution" in raw
        ? parseWorkflowExecutionReceipt(raw.workflow_execution, `${path}.workflow_execution`)
        : undefined,
  };
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
  /** The backend may meter the bounded context in characters rather than bytes. */
  unit?: "bytes" | "characters";
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
  /** Optional approved hints; never a recommendation or authorization input. */
  domain_memory_projection?: DomainMemoryRetrievalProjection | null;
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

/** Browser-only anchor for the ephemeral selected-text action surface. */
export interface NotebookSelectionAnchor {
  top: number;
  left: number;
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
  mode?: "materialize" | "confirm_and_execute";
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
  /** Persisted results keyed by Option id; model-neutral and reload-safe. */
  executionResults?: Record<string, NotebookExecutionResult>;
  materialization?: OptionMaterialization | null;
  selection: NotebookSelection | null;
}

export interface NotebookErrorPacket {
  code: string;
  message: string;
}

export interface NotebookLoadingView {
  status: "loading";
  // Which bounded step is in flight. Real agent planning can take tens of
  // seconds; distinguishing it from the fast context compile keeps the loading
  // state from reading as a hang.
  phase?: "compiling" | "planning";
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
