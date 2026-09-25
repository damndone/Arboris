import type { CitableFact } from "./factTable";

export type EvidenceGroupId =
  | "data-sample"
  | "model-estimation"
  | "diagnostics-robustness"
  | "time-series"
  | "figures"
  | "post-estimation"
  | "other";

export interface EvidenceGroup {
  id: EvidenceGroupId;
  label: string;
  facts: CitableFact[];
}

interface EvidenceGroupDefinition {
  id: EvidenceGroupId;
  label: string;
  prefixes: string[];
  capability?: string;
  provider_id?: string;
}

const AGGREGATE_PROVIDER_ID = "evidence.post_estimation.aggregate.v1";
const MULTI_PROVIDER_LIMITATION =
  "Facts include multiple registered evidence providers; inspect fact-level provider_id metadata.";

export interface ReportCapabilityManifestEntry {
  capability_id: string;
  provider_id: string;
  availability: "available" | "unavailable" | "not_applicable";
  validation_level: "external_oracle" | "internal_only" | "unverified";
  report_modules: string[];
  limitations: string[];
}

/** Reader-facing provider registry for existing report facts. */
export const EVIDENCE_GROUPS: readonly EvidenceGroupDefinition[] = [
  { id: "data-sample", label: "Data and sample", prefixes: ["sample:", "data:", "ts:data:"], capability: "data", provider_id: "evidence.data.v1" },
  { id: "model-estimation", label: "Model and estimation", prefixes: ["param:", "metric:", "coef:"], capability: "model.estimation", provider_id: "evidence.estimation.v1" },
  { id: "diagnostics-robustness", label: "Diagnostics and robustness", prefixes: ["coef_se:", "coef_p:", "diagnostic:", "decision:"], capability: "diagnostics.robustness", provider_id: "evidence.diagnostics.v1" },
  { id: "time-series", label: "Time series", prefixes: ["ts:"], capability: "time_series", provider_id: "evidence.time_series.v1" },
  { id: "figures", label: "Figures", prefixes: ["figure:"] },
  { id: "post-estimation", label: "Post-estimation", prefixes: ["post_estimation:"], capability: "post_estimation", provider_id: "evidence.post_estimation.v1" },
  { id: "other", label: "Other evidence", prefixes: [] },
];

function groupForField(field: string): EvidenceGroupDefinition {
  const matched = EVIDENCE_GROUPS.find((group) =>
    group.id !== "other" && group.prefixes.some((prefix) => field.startsWith(prefix)),
  );
  return matched ?? EVIDENCE_GROUPS[EVIDENCE_GROUPS.length - 1];
}

export function groupFacts(facts: CitableFact[]): EvidenceGroup[] {
  const groups = new Map<EvidenceGroupId, EvidenceGroup>();
  for (const fact of facts) {
    const definition = groupForField(fact.field);
    const current = groups.get(definition.id);
    if (current) current.facts.push(fact);
    else groups.set(definition.id, { id: definition.id, label: definition.label, facts: [fact] });
  }
  return EVIDENCE_GROUPS.filter((definition) => groups.has(definition.id)).map((definition) => groups.get(definition.id)!);
}

export function groupFactIds(group: EvidenceGroup): string[] {
  return group.facts.map((fact) => fact.id);
}

export function reportCapabilitiesForFacts(facts: CitableFact[]): string[] {
  const fields = facts.map((fact) => fact.field);
  return EVIDENCE_GROUPS.flatMap((definition) => {
    if (!definition.capability) return [];
    return fields.some((field) => definition.prefixes.some((prefix) => field.startsWith(prefix)))
      ? [definition.capability]
      : [];
  });
}

export function reportCapabilityManifestForFacts(facts: CitableFact[]): ReportCapabilityManifestEntry[] {
  const groups = groupFacts(facts);
  return EVIDENCE_GROUPS.flatMap((definition) => {
    if (!definition.capability) return [];
    const group = groups.find((candidate) => candidate.id === definition.id);
    if (!group) return [];
    const providerIds = new Set(group.facts.map((fact) => fact.provider_id).filter((providerId): providerId is string => Boolean(providerId)));
    if (group.facts.some((fact) => !fact.provider_id) && definition.provider_id) providerIds.add(definition.provider_id);
    const sortedProviderIds = [...providerIds].sort();
    return [{
      capability_id: definition.capability,
      provider_id: sortedProviderIds.length > 1 ? AGGREGATE_PROVIDER_ID : sortedProviderIds[0] ?? definition.provider_id ?? `evidence.${definition.id}.v1`,
      availability: "available" as const,
      validation_level: "internal_only" as const,
      report_modules: [definition.id],
      limitations: sortedProviderIds.length > 1 ? [MULTI_PROVIDER_LIMITATION] : [],
    }];
  });
}

export function displayEvidenceLabel(fact: CitableFact): string {
  const label = fact.label || fact.field;
  if (label.length === 0) return label;
  const readable = label.replace(/_/g, " ");
  const withInitial = `${readable.slice(0, 1).toLocaleUpperCase()}${readable.slice(1)}`;
  return withInitial.replace(/\b(rmse|mae|aicc|aic|bic|arma|garch|arch)\b/gi, (token) => token.toUpperCase());
}

export type EvidenceProjectionStatus = "available" | "unavailable" | "degraded" | "blocked";
export type EvidenceSectionStatus = EvidenceProjectionStatus;
export const TYPED_EVIDENCE_RENDERER_KEY = "workbench.consumer_projection.report" as const;
const LEGACY_TYPED_EVIDENCE_RENDERER_KEY = "typed-evidence" as const;

export interface EvidenceIntervalViewModel {
  readonly lower: number;
  readonly upper: number;
  readonly method?: string;
  readonly confidenceLevel?: number;
}

export type EvidenceValidationProvenance = string | Readonly<Record<string, unknown>>;

/** Bounded identity/provenance fields carried by the server projection. */
export interface EvidenceProvenanceViewModel {
  readonly artifactRef?: string;
  readonly artifactId?: string;
  readonly artifactType?: string;
  readonly scopeRef?: string;
  readonly contentHash?: string;
  readonly sourceRef?: string;
  readonly validatorRef?: string | Record<string, unknown>;
  readonly executionRef?: string;
  readonly contractDigest?: string;
  readonly commitId?: string;
  readonly envelopeRef?: string;
  readonly envelopeDigest?: string;
  readonly dataSnapshotRef?: string;
  readonly dataSnapshotDigest?: string;
  readonly lineageRefs?: readonly string[];
  readonly projectionRef?: Record<string, unknown>;
  readonly resultIdentity?: Record<string, unknown>;
  readonly indexed?: boolean;
  readonly admissionStatus?: string;
  readonly projections?: readonly Record<string, unknown>[];
  readonly envelopeDigests?: readonly string[];
}

export interface EvidenceFactViewModel {
  readonly factId: string;
  readonly statisticId: string;
  readonly value: number | string;
  readonly unit?: string | null;
  /** Canonical consumer-facing interval; confidenceInterval is a legacy wire alias. */
  readonly interval?: EvidenceIntervalViewModel;
  readonly caveat?: string;
  readonly availability?: string;
  readonly validationProvenance?: EvidenceValidationProvenance;
  readonly standardError?: number;
  readonly confidenceInterval?: EvidenceIntervalViewModel;
}

export interface EvidenceSectionViewModel {
  readonly key: string;
  readonly label: string;
  readonly status: EvidenceSectionStatus;
}

export interface EvidenceViewModel {
  readonly schemaVersion?: 1;
  readonly projectionId: string;
  readonly consumerId: string;
  readonly consumerVersion: string;
  readonly artifactRef: string;
  readonly envelopeRef: string;
  readonly envelopeDigest: string;
  readonly dataSnapshotRef?: string;
  readonly dataSnapshotDigest?: string;
  readonly projectionDigest?: string;
  readonly actorRef?: string;
  readonly projectRef?: string;
  readonly sessionRef?: string;
  readonly scopeRef?: string;
  readonly runId?: string;
  readonly modelRunId?: string;
  readonly confirmationRef?: string;
  readonly rendererKey?: string;
  readonly contract?: string;
  readonly status: EvidenceProjectionStatus;
  readonly executionStatus: string;
  readonly availability: string;
  readonly completenessStatus: string;
  readonly commitId?: string;
  /** Validation is an independent axis from execution/availability/completeness. */
  readonly validationStatus?: string;
  readonly validationSummary?: Readonly<Record<string, unknown>>;
  readonly validationProvenance?: EvidenceValidationProvenance;
  readonly provenance?: EvidenceProvenanceViewModel;
  readonly lineageRefs?: readonly string[];
  readonly resultIdentity?: Record<string, unknown>;
  readonly identity?: Record<string, unknown>;
  readonly reasonCode?: string;
  readonly facts: readonly EvidenceFactViewModel[];
  readonly sections: readonly EvidenceSectionViewModel[];
  readonly structuredResults?: StructuredResultsWire;
  readonly resolvedSections?: readonly ResolvedResultSection[];
}

// Mirror of the frozen backend result_sections_declaration(). A declaration
// change must update this digest and its parser tests together; never accept a
// digest supplied by the caller as a new declaration or as an authority receipt.
export const RESULT_SECTIONS_DIGEST = "9ac17e068d3d718e6cb09a938e2d373db3c43d49b11ca6b7ac6df76897732ab6";
const SECTION_FIELDS: Readonly<Record<string, readonly string[]>> = {
  model_identity: ["models", "model_id", "model_type", "model_label", "y_variable", "x_variables", "nobs"],
  regression_table: ["models", "rows", "notes", "significance_levels", "payload_schema", "schema_version"],
  descriptive_statistics: ["rows", "columns", "labels"],
  statistical_tests: ["results", "dataset_ref", "lineage_parent", "warnings", "payload_schema", "schema_version", "correction_scope"],
  survey_design: ["models", "design", "provenance", "warnings"],
  marginal_effects: ["models", "rows", "method", "warnings"],
  model_family_evidence: ["model_family", "models", "results", "diagnostics", "warnings"],
  diagnostics: ["blockers", "warnings", "cautions", "info", "results"],
  interpretation_constraints: ["constraints", "required_mentions", "forbidden_claims"],
  variable_importance: ["rows", "method", "warnings"],
  workflow_status: ["workflow_id", "status", "steps", "artifact_ids", "warnings"],
};
const REQUIRED_FIELDS: Readonly<Record<string, readonly string[]>> = {
  model_identity: ["models"], regression_table: ["models", "rows"], descriptive_statistics: ["rows"],
  statistical_tests: ["results"], survey_design: ["design", "provenance"], marginal_effects: ["rows", "method"],
  model_family_evidence: ["model_family", "results"], diagnostics: ["blockers", "warnings", "cautions", "info"],
  interpretation_constraints: ["constraints", "required_mentions", "forbidden_claims"],
  variable_importance: ["rows", "method"], workflow_status: ["workflow_id", "status", "steps", "artifact_ids"],
};
const FIELD_SHAPES: Readonly<Record<string, readonly string[]>> = {
  ...Object.fromEntries(["rows", "columns", "notes", "warnings", "blockers", "cautions", "info", "x_variables", "required_mentions", "forbidden_claims", "steps", "artifact_ids"].map((key) => [key, ["list"]])),
  ...Object.fromEntries(["labels", "dataset_ref", "design", "provenance", "constraints", "significance_levels"].map((key) => [key, ["object"]])),
  ...Object.fromEntries(["model_id", "model_type", "model_label", "y_variable", "payload_schema", "lineage_parent", "model_family", "workflow_id", "status", "method", "correction_scope"].map((key) => [key, ["text"]])),
  schema_version: ["fact"], nobs: ["fact"], models: ["list", "object"], results: ["list", "object"], diagnostics: ["list", "object"],
};
const NUMERIC_PATHS: Readonly<Record<string, readonly (readonly string[])[]>> = {
  model_identity: [[], ["models", "*"]], regression_table: [["models", "*"], ["rows", "*", "models", "*"]],
  descriptive_statistics: [["rows", "*"]], statistical_tests: [["results", "*"], ["results", "*", "comparisons", "*"]],
  survey_design: [["design"], ["provenance"]], marginal_effects: [["rows", "*"]], model_family_evidence: [["results", "*"]],
  diagnostics: [["results", "*"]], interpretation_constraints: [], variable_importance: [["rows", "*"]], workflow_status: [["steps", "*"]],
};
const COUNT_FIELDS = new Set(["nobs", "n_observations", "sample_size", "n", "count", "missing_count", "replicates_attempted", "replicates_succeeded", "replicates_failed"]);
const NUMERIC_FIELDS = new Set([...COUNT_FIELDS, "estimate", "std_error", "standard_error", "statistic", "p_value", "p_value_corrected", "confidence_level", "lower", "upper", "r_squared", "adjusted_r_squared", "design_effect", "effective_sample_size", "degf", "mean", "median", "variance", "minimum", "maximum"]);
const MAX_SECTION_BYTES = 1048576;
const MAX_SECTION_NODES = 16384;
const MAX_SECTION_DEPTH = 16;
const utf8 = new TextEncoder();

export type ResolvedSectionContent = null | string | number | boolean
  | readonly ResolvedSectionContent[] | { readonly [key: string]: ResolvedSectionContent };
export interface ResolvedResultSection {
  readonly sectionId: string;
  readonly sectionType: string;
  readonly status: "available" | "unavailable" | "not_applicable" | "blocked";
  readonly reasonCodes: readonly string[];
  readonly content: ResolvedSectionContent;
}
type ResultNode =
  | { readonly kind: "text"; readonly value: string }
  | { readonly kind: "boolean"; readonly value: boolean }
  | { readonly kind: "null" }
  | { readonly kind: "missing"; readonly status: "unavailable" | "not_applicable"; readonly reason: string }
  | { readonly kind: "fact"; readonly fact_id: string; readonly representation: "number" | "integer" }
  | { readonly kind: "list"; readonly items: readonly ResultNode[] }
  | { readonly kind: "object"; readonly fields: { readonly [key: string]: ResultNode } };
interface StructuredResultsWire {
  readonly schema_version: 1;
  readonly contract_digest: string;
  readonly sections: readonly {
    readonly section_id: string; readonly section_type: string; readonly schema_version: 1;
    readonly status: ResolvedResultSection["status"]; readonly reason_codes: readonly string[];
    readonly fact_refs: readonly string[]; readonly dependency_refs: readonly string[]; readonly content: ResultNode;
  }[];
}
class InvalidStructuredResults extends Error {}
function requireSection(condition: unknown): asserts condition {
  if (!condition) throw new InvalidStructuredResults();
}
function own(value: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}
function exact(value: unknown, keys: readonly string[]): asserts value is Record<string, unknown> {
  requireSection(record(value) && Object.keys(value).length === keys.length && keys.every((key) => own(value, key)));
}
function sectionText(value: unknown, allowEmpty = false): asserts value is string {
  requireSection(typeof value === "string" && (allowEmpty || value.length > 0) && value.length <= 4096 && !value.includes("\0"));
  // TextEncoder replaces lone surrogates; reject them rather than silently
  // changing a label relative to the server's strict UTF-8 contract.
  requireSection(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value));
  requireSection(utf8.encode(value).length <= 4096);
}
function sectionNumber(value: unknown): asserts value is number {
  // Python floats can be integer-valued (e.g. 1e20). Safe-integer checks
  // belong to the explicitly declared integer/count representation below.
  requireSection(typeof value === "number" && Number.isFinite(value));
}

/** Bounded traversal BEFORE stringify, copying, resolution, or tree rendering. */
function preflightSectionWire(value: unknown) {
  let bytes = 0;
  const spend = (n: number) => { bytes += n; requireSection(bytes <= MAX_SECTION_BYTES); };
  const visit = (item: unknown, depth: number): void => {
    requireSection(depth <= MAX_SECTION_DEPTH * 3 + 8);
    if (Array.isArray(item)) {
      requireSection(item.length <= MAX_SECTION_NODES);
      spend(2 + Math.max(0, item.length - 1));
      for (const child of item) visit(child, depth + 1);
    } else if (record(item)) {
      requireSection(Object.getPrototypeOf(item) === Object.prototype || Object.getPrototypeOf(item) === null);
      spend(2);
      let count = 0;
      const normalized = new Set<string>();
      for (const key in item) {
        if (!own(item, key)) continue;
        requireSection(++count <= MAX_SECTION_NODES);
        sectionText(key);
        const canonicalKey = key.normalize("NFC");
        requireSection(!normalized.has(canonicalKey)); normalized.add(canonicalKey);
        spend(count === 1 ? 1 : 2);
        visit(key, depth + 1); visit(item[key], depth + 1);
      }
    } else {
      if (typeof item === "string") sectionText(item, true);
      else if (typeof item === "number") sectionNumber(item);
      else requireSection(item === null || typeof item === "boolean");
      spend(utf8.encode(JSON.stringify(item)).length);
    }
  };
  visit(value, 0);
}
function sectionRefs(value: unknown, opaque = true): asserts value is string[] {
  requireSection(Array.isArray(value) && value.length <= MAX_SECTION_NODES);
  const seen = new Set<string>();
  for (const ref of value) {
    sectionText(ref);
    requireSection(!seen.has(ref) && (!opaque || /^[A-Za-z0-9](?:[A-Za-z0-9:_-]*[A-Za-z0-9])?$/.test(ref)));
    seen.add(ref);
  }
}

/** Validate both trees together, never trust independently supplied numbers. */
function checkSectionTree(node: unknown, resolved: unknown, facts: ReadonlyMap<string, EvidenceFactViewModel>,
  refs: Set<string>, count: { nodes: number }, type: string, path: readonly string[] = []): void {
  requireSection(path.length <= MAX_SECTION_DEPTH && ++count.nodes <= MAX_SECTION_NODES && record(node));
  switch (node.kind) {
    case "text": exact(node, ["kind", "value"]); sectionText(node.value, true); requireSection(resolved === node.value); return;
    case "boolean": exact(node, ["kind", "value"]); requireSection(typeof node.value === "boolean" && resolved === node.value); return;
    case "null": exact(node, ["kind"]); requireSection(resolved === null); return;
    case "missing":
      exact(node, ["kind", "status", "reason"]); exact(resolved, ["status", "reason"]);
      requireSection(node.status === "unavailable" || node.status === "not_applicable"); sectionText(node.reason);
      requireSection(resolved.status === node.status && resolved.reason === node.reason); return;
    case "fact": {
      exact(node, ["kind", "fact_id", "representation"]); sectionText(node.fact_id);
      const fact = facts.get(node.fact_id); requireSection(fact); sectionNumber(fact.value);
      requireSection(node.representation === "number" || node.representation === "integer");
      requireSection(node.representation !== "integer" || Number.isSafeInteger(fact.value));
      const expected = node.representation === "integer" && fact.value === 0 ? 0 : fact.value;
      requireSection(Object.is(resolved, expected)); refs.add(node.fact_id); return;
    }
    case "list":
      exact(node, ["kind", "items"]);
      requireSection(Array.isArray(node.items) && Array.isArray(resolved) && node.items.length === resolved.length);
      node.items.forEach((child, i) => checkSectionTree(child, resolved[i], facts, refs, count, type, [...path, "*"])); return;
    case "object": {
      exact(node, ["kind", "fields"]); requireSection(record(node.fields)); exact(resolved, Object.keys(node.fields));
      const numericRow = NUMERIC_PATHS[type].some((pattern) => pattern.length === path.length && pattern.every((part, i) => part === "*" || part === path[i]));
      for (const [key, child] of Object.entries(node.fields)) {
        checkSectionTree(child, resolved[key], facts, refs, count, type, [...path, key]);
        if (numericRow && NUMERIC_FIELDS.has(key)) {
          requireSection(record(child));
          if (child.kind === "missing") continue;
          requireSection(child.kind === "fact");
          const value = resolved[key]; sectionNumber(value);
          if (COUNT_FIELDS.has(key)) requireSection(child.representation === "integer" && value >= 0);
          if (key === "p_value" || key === "p_value_corrected") requireSection(value >= 0 && value <= 1);
          if (key === "confidence_level") requireSection(value > 0 && value < 1);
        }
      }
      return;
    }
    default: throw new InvalidStructuredResults();
  }
}

// Mirrors Python ARMA_REPORT_SCHEMA; number roles reuse the fact-only tree
// validator above. Missing is legal at every schema node, not an empty value.
type ReportNodeSchema = "fact" | "text" | "boolean"
  | ["list" | "map", ReportNodeSchema] | { [key: string]: ReportNodeSchema };
const roles = (keys: string, role: ReportNodeSchema): Record<string, ReportNodeSchema> =>
  Object.fromEntries(keys.split(" ").map((key) => [key, role]));
const ARMA_DIAGNOSTIC: ReportNodeSchema = {
  ...roles("statistic p_value used_lag nobs lag f_statistic f_p_value skew kurtosis threshold count rate n", "fact"),
  status: "text", reason: "text",
};
const ARMA_REPORT_SCHEMA: ReportNodeSchema = {
  contract: roles("dataset_ref time_column value_column transform estimation_strategy innovation_distribution", "text"),
  sample: { ...roles("source_n effective_n training_n validation_n", "fact"),
    ...roles("selection_data_role validation_data_role", "text") },
  metrics: { ...roles("validation_n successful_forecast_n mae rmse mean_error interval_coverage average_interval_width coverage_count exception_rate exception_count pinball_loss", "fact"),
    coverage_uncertainty: { method: "text", lower: "fact", upper: "fact" } },
  parameters: roles("mean_candidate selected_variance_candidate final_fit", ["map", "fact"]),
  diagnostics: { adf: ARMA_DIAGNOSTIC, ljung_box: ["list", ARMA_DIAGNOSTIC], arch_lm: ARMA_DIAGNOSTIC,
    normality: { ...ARMA_DIAGNOSTIC, shapiro_wilk: ARMA_DIAGNOSTIC, shapiro_francia: ARMA_DIAGNOSTIC },
    residual_exceedance: ARMA_DIAGNOSTIC, warnings: ["list", "text"] },
  selection: roles("mean variance", roles("final_selected_candidate_id final_selection_basis selected_candidate_id selection_basis validation_data_role", "text")),
  next_forecast: { ...roles("conditional_mean conditional_variance conditional_volatility lower_bound upper_bound lower_quantile", "fact"),
    ...roles("result_role parent_result_id target_label target_time model_scale fit_method predictive_interval warning", "text"),
    forecast_origin: { row_id: "text", time: "text" } },
  forecast_limitations: { horizon: "fact", predictive_interval: "text", parameter_uncertainty_included: "boolean" },
  warnings: ["list", "text"], chart_artifacts: ["list", "text"], artifact_ids: ["list", "text"],
};

/** Shape overlay only: exact node keys, facts, bounds and resolved parity were
 * already checked by checkSectionTree; do not create a second value decoder. */
function checkReportNodeSchema(node: unknown, schema: ReportNodeSchema): void {
  requireSection(record(node));
  if (node.kind === "missing") return;
  if (typeof schema === "string") { requireSection(node.kind === schema); return; }
  if (Array.isArray(schema)) {
    const [role, childSchema] = schema;
    requireSection(node.kind === (role === "map" ? "object" : "list"));
    if (role === "map") {
      requireSection(record(node.fields));
      Object.values(node.fields).forEach((child) => checkReportNodeSchema(child, childSchema));
    } else {
      requireSection(Array.isArray(node.items));
      node.items.forEach((child) => checkReportNodeSchema(child, childSchema));
    }
    return;
  }
  requireSection(node.kind === "object" && record(node.fields));
  for (const [key, child] of Object.entries(node.fields)) {
    requireSection(own(schema, key));
    checkReportNodeSchema(child, schema[key]);
  }
}

function checkArmaReport(fields: Record<string, unknown>, dependencies: readonly string[]): void {
  const family = fields.model_family;
  if (!record(family) || family.kind !== "text" || family.value !== "time_series.arma_garch") return;
  const results = fields.results;
  requireSection(record(results) && results.kind === "object" && record(results.fields));
  for (const model of Object.values(results.fields)) {
    requireSection(record(model) && model.kind === "object" && record(model.fields));
    if (!own(model.fields, "report")) continue;
    const report = model.fields.report;
    requireSection(record(report));
    if (report.kind === "missing") continue;
    checkReportNodeSchema(report, ARMA_REPORT_SCHEMA);
    requireSection(record(report.fields));
    for (const key of ["artifact_ids", "chart_artifacts"]) {
      const refs = report.fields[key];
      if (record(refs) && refs.kind === "list") {
        requireSection(Array.isArray(refs.items));
        for (const ref of refs.items) {
          requireSection(record(ref) && ref.kind === "text" && typeof ref.value === "string" && dependencies.includes(ref.value));
        }
      }
    }
  }
}

function copySectionWire(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(copySectionWire);
  if (record(value)) return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, copySectionWire(child)]));
  return value;
}

function readStructuredSections(candidate: Record<string, unknown>): Pick<EvidenceViewModel, "structuredResults" | "resolvedSections"> | null {
  if (!own(candidate, "structuredResults") && !own(candidate, "resolvedSections")) return {};
  try {
    const wire = candidate.structuredResults, resolved = candidate.resolvedSections;
    preflightSectionWire(wire); preflightSectionWire(resolved);
    exact(wire, ["schema_version", "contract_digest", "sections"]);
    requireSection(wire.schema_version === 1 && wire.contract_digest === RESULT_SECTIONS_DIGEST);
    requireSection(Array.isArray(wire.sections) && wire.sections.length <= 128 && Array.isArray(resolved) && resolved.length === wire.sections.length);
    const facts = new Map<string, EvidenceFactViewModel>();
    for (const fact of candidate.facts as EvidenceFactViewModel[]) {
      if (typeof fact.value === "number") sectionNumber(fact.value);
      requireSection(!facts.has(fact.factId)); facts.set(fact.factId, fact);
    }
    const ids = new Set<string>();
    wire.sections.forEach((section, i) => {
      exact(section, ["section_id", "section_type", "schema_version", "status", "reason_codes", "fact_refs", "dependency_refs", "content"]);
      sectionText(section.section_id); sectionText(section.section_type);
      requireSection(!ids.has(section.section_id) && own(SECTION_FIELDS, section.section_type) && section.schema_version === 1);
      ids.add(section.section_id);
      sectionRefs(section.fact_refs, false);
      // ResultSectionV1._refs accepts bounded IDs, including dotted artifact
      // IDs. Dependency closure and filesystem authority remain server-owned.
      sectionRefs(section.dependency_refs, false); sectionRefs(section.reason_codes, false);
      const row = resolved[i]; exact(row, ["sectionId", "sectionType", "status", "reasonCodes", "content"]);
      requireSection(row.sectionId === section.section_id && row.sectionType === section.section_type && row.status === section.status);
      requireSection(Array.isArray(row.reasonCodes) && row.reasonCodes.length === section.reason_codes.length);
      requireSection(section.reason_codes.every((reason, j) => reason === (row.reasonCodes as unknown[])[j]));
      const actual = new Set<string>();
      checkSectionTree(section.content, row.content, facts, actual, { nodes: 0 }, section.section_type);
      requireSection(actual.size === section.fact_refs.length && section.fact_refs.every((ref) => actual.has(ref)));
      requireSection(record(section.content));
      if (section.status === "available") {
        requireSection(section.reason_codes.length === 0 && section.dependency_refs.length > 0 && section.content.kind === "object");
        const fields = section.content.fields; requireSection(record(fields));
        requireSection(REQUIRED_FIELDS[section.section_type].every((key) => own(fields, key)));
        for (const [key, node] of Object.entries(fields)) {
          requireSection(SECTION_FIELDS[section.section_type].includes(key) && record(node));
          requireSection(node.kind === "missing" || FIELD_SHAPES[key].includes(node.kind as string));
        }
        if (section.section_type === "model_family_evidence") checkArmaReport(fields, section.dependency_refs);
      } else {
        requireSection(["unavailable", "not_applicable", "blocked"].includes(section.status as string));
        requireSection(section.reason_codes.length > 0 && section.fact_refs.length === 0 && section.dependency_refs.length === 0 && section.content.kind === "null");
      }
    });
    // At most 1 MiB each, and all values have passed both preflight and semantic
    // checks. Copy only now, retaining the server's exact display values.
    return {
      structuredResults: copySectionWire(wire) as StructuredResultsWire,
      resolvedSections: copySectionWire(resolved) as ResolvedResultSection[],
    };
  } catch (error) {
    if (error instanceof InvalidStructuredResults) return null;
    throw error;
  }
}

/** The HTTP route, not these value checks or hashes, supplies owner authority. */
export interface ResultDirectoryAnchor {
  readonly identity: Readonly<Record<string, string>>;
  readonly artifact_ref: string;
  readonly commit_id: string;
  readonly envelope_digest: string;
  readonly section_contract_digest: string;
  readonly sections: readonly ResultDirectorySection[];
}
export interface ResultDirectorySection {
  readonly section_id: string;
  readonly section_type: string;
  readonly status: ResolvedResultSection["status"];
  readonly reason_codes: readonly string[];
}
export class ResultReadError extends Error {
  constructor(readonly code: string, message: string) { super(`${code}: ${message}`); this.name = "ResultReadError"; }
}
export const REPORT_LOCAL_POLICY = Object.freeze({ kind: "policy",
  logical_id: "workbench.consumer_projection.local_structured_v1.report", semantic_version: "1.0",
  contract_digest: "0bd2f4b04a959c37aa3deab0580adadb90f8fd1808c0d62674e1a7d38b7d2344" });
export function isResultDirectorySection(value: unknown): value is ResultDirectorySection {
  try {
    exact(value, ["section_id", "section_type", "status", "reason_codes"]);
    sectionText(value.section_id); sectionText(value.section_type); sectionRefs(value.reason_codes, false);
    requireSection(own(SECTION_FIELDS, value.section_type));
    requireSection(value.status === "available" ? value.reason_codes.length === 0
      : ["unavailable", "not_applicable", "blocked"].includes(value.status as string) && value.reason_codes.length > 0);
    return true;
  } catch { return false; }
}

const VALIDATION_LEVELS = ["none", "same_library_regression", "known_answer", "independent_implementation", "reference_software"];
const EVALUATION_DESIGNS = ["in_sample", "holdout", "cross_validation", "nested_cross_validation", "cross_fitting", "bootstrap", "not_applicable"];
function member(value: unknown, choices: readonly string[]): asserts value is string {
  requireSection(typeof value === "string" && choices.includes(value));
}
function sectionDigest(value: unknown): asserts value is string { requireSection(typeof value === "string" && /^[0-9a-f]{64}$/.test(value)); }
function factText(value: unknown): asserts value is string { sectionText(value); requireSection(value === value.trim()); }
function notApplicable(value: unknown): boolean {
  if (!record(value) || value.status !== "not_applicable") return false;
  exact(value, ["status", "reason"]); factText(value.reason); return true;
}
function textOrNA(value: unknown) { if (!notApplicable(value)) factText(value); }
function numberOrNA(value: unknown, check = (_n: number) => true) {
  if (!notApplicable(value)) { sectionNumber(value); requireSection(check(value)); }
}
function contractRef(value: unknown, expected: Readonly<Record<string, string>>) {
  exact(value, ["kind", "logical_id", "semantic_version", "contract_digest"]);
  requireSection(Object.entries(expected).every(([key, item]) => value[key] === item));
}

/** NumericFactV1 wire validation. Retain the entire original fact, not just its
 * display number: NA reasons, correction scope, selectors and oracle evidence. */
function bundleFact(value: unknown): EvidenceFactViewModel {
  exact(value, ["fact_id", "estimand_id", "statistic_id", "value", "denominator", "weight", "unit", "scale",
    "standard_error", "confidence_interval", "confidence_level", "test_direction", "reference_distribution",
    "multiple_comparison", "evaluation_design", "source_selector", "oracle_checks", "validation_level"]);
  factText(value.fact_id); factText(value.statistic_id); sectionNumber(value.value);
  for (const key of ["estimand_id", "unit", "scale"]) textOrNA(value[key]);
  if (!notApplicable(value.denominator)) {
    exact(value.denominator, ["kind", "value", "unit"]);
    factText(value.denominator.kind); factText(value.denominator.unit);
    sectionNumber(value.denominator.value); requireSection(value.denominator.value > 0);
  }
  if (!notApplicable(value.weight)) {
    exact(value.weight, ["kind", "variable_ref"]); factText(value.weight.kind); textOrNA(value.weight.variable_ref);
  }
  numberOrNA(value.standard_error, n => n >= 0); numberOrNA(value.confidence_level, n => n > 0 && n < 1);
  if (!notApplicable(value.confidence_interval)) {
    exact(value.confidence_interval, ["lower", "upper", "method"]);
    sectionNumber(value.confidence_interval.lower); sectionNumber(value.confidence_interval.upper);
    requireSection(value.confidence_interval.lower <= value.confidence_interval.upper); factText(value.confidence_interval.method);
  }
  if (!notApplicable(value.test_direction)) member(value.test_direction, ["two_sided", "greater", "less"]);
  if (!notApplicable(value.reference_distribution)) {
    exact(value.reference_distribution, ["name", "degrees_of_freedom", "parameters"]);
    factText(value.reference_distribution.name); numberOrNA(value.reference_distribution.degrees_of_freedom, n => n > 0);
    requireSection(record(value.reference_distribution.parameters));
  }
  if (!notApplicable(value.multiple_comparison)) {
    exact(value.multiple_comparison, ["family_id", "correction"]);
    textOrNA(value.multiple_comparison.family_id); textOrNA(value.multiple_comparison.correction);
  }
  member(value.evaluation_design, EVALUATION_DESIGNS);
  exact(value.source_selector, ["artifact_ref", "artifact_digest", "selector"]);
  factText(value.source_selector.artifact_ref); factText(value.source_selector.selector); sectionDigest(value.source_selector.artifact_digest);
  member(value.validation_level, VALIDATION_LEVELS);
  requireSection(Array.isArray(value.oracle_checks));
  const ids = new Set<string>(); let level = 0;
  for (const check of value.oracle_checks) {
    exact(check, ["check_id", "status", "basis", "reference", "tolerance", "observed_difference"]);
    factText(check.check_id); requireSection(!ids.has(check.check_id)); ids.add(check.check_id);
    member(check.status, ["pass", "fail", "not_verified", "not_applicable"]); member(check.basis, VALIDATION_LEVELS);
    textOrNA(check.reference); textOrNA(check.tolerance); numberOrNA(check.observed_difference);
    if (check.status === "pass") level = Math.max(level, VALIDATION_LEVELS.indexOf(check.basis));
  }
  requireSection(value.validation_level === VALIDATION_LEVELS[level]);
  return { factId: value.fact_id, statisticId: value.statistic_id, value: value.value,
    validationProvenance: { level: value.validation_level, oracleChecks: value.oracle_checks } };
}

export interface ReadResultSection {
  readonly section: ResolvedResultSection;
  /** Only schema-validated JSON; used for explicit local provenance inspection. */
  readonly facts: readonly ResolvedSectionContent[];
  readonly dependencies: ResolvedSectionContent;
  readonly metadata: ResolvedSectionContent;
  readonly resultIdentity: ResolvedSectionContent;
  readonly structuredSection: ResolvedSectionContent;
}

/** Bridge from complete page bytes' bundle to the EXISTING strict section tree
 * parser. Same 1 MiB / 16,384 node / depth 16 section ceilings. No JSON fallback,
 * no projection issuance, no LLM input, and no new statistical validation claim. */
export function readResultSectionBundle(value: unknown, anchor: ResultDirectoryAnchor, sectionId: string): ReadResultSection {
  try {
    if (ArrayBuffer.isView(value) && Object.prototype.toString.call(value) === "[object Uint8Array]") {
      requireSection(value.byteLength > 0 && value.byteLength <= MAX_SECTION_BYTES);
      const raw = new TextDecoder("utf-8", { fatal: true }).decode(value);
      value = JSON.parse(raw);
      preflightSectionWire(value);
      // Python reparses canonical bytes too. Reject nonportable integer tokens
      // before JS rounding can turn them into a different admitted fact.
      for (const token of raw.matchAll(/"(?:\\.|[^"\\])*"|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g)) {
        if (token[1] && !/[.eE]/.test(token[1])) requireSection(Number.isSafeInteger(Number(token[1])));
      }
      const canonical = (item: unknown): string => {
        if (typeof item === "string") return JSON.stringify(item.normalize("NFC"));
        if (Array.isArray(item)) return `[${item.map(canonical).join(",")}]`;
        if (record(item)) {
          const order = (a: string, b: string): number => {
            const x = Array.from(a, c => c.codePointAt(0)!), y = Array.from(b, c => c.codePointAt(0)!);
            for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
            return x.length - y.length;
          };
          return `{${Object.keys(item).sort(order).map(key => `${canonical(key)}:${canonical(item[key])}`).join(",")}}`;
        }
        return JSON.stringify(item);
      };
      requireSection(canonical(value) === raw);
    }
    // Bundle bytes are canonical NFC; owner/delivery HTTP identities remain
    // verbatim outside this bridge. Normalize only the comparison view here.
    anchor = { ...anchor, artifact_ref: anchor.artifact_ref.normalize("NFC"), commit_id: anchor.commit_id.normalize("NFC"),
      identity: Object.fromEntries(Object.entries(anchor.identity).map(([key, v]) => [key, v.normalize("NFC")])),
      sections: anchor.sections.map(s => ({ ...s, section_id: s.section_id.normalize("NFC"),
        reason_codes: s.reason_codes.map(reason => reason.normalize("NFC")) })) };
    sectionId = sectionId.normalize("NFC");
    preflightSectionWire(value);
    exact(value, ["schema_version", "source_ref", "source_digest", "commit_id", "result_identity", "section_contract_digest",
      "section", "facts", "result_dependencies", "projection_metadata"]);
    requireSection(value.schema_version === 1 && value.source_ref === anchor.artifact_ref && value.source_digest === anchor.envelope_digest
      && value.commit_id === anchor.commit_id && value.section_contract_digest === RESULT_SECTIONS_DIGEST
      && value.section_contract_digest === anchor.section_contract_digest);
    requireSection(record(value.result_identity));
    for (const [key, expected] of Object.entries(anchor.identity)) {
      if (own(value.result_identity, key)) requireSection(value.result_identity[key] === expected);
    }
    const item = anchor.sections.find(s => s.section_id === sectionId); requireSection(item);
    requireSection(record(value.section) && value.section.section_id === item.section_id && value.section.section_type === item.section_type
      && value.section.status === item.status && JSON.stringify(value.section.reason_codes) === JSON.stringify(item.reason_codes));
    const section = value.section;
    sectionRefs(section.fact_refs, false); sectionRefs(section.dependency_refs, false);
    requireSection(Array.isArray(value.facts));
    const facts = value.facts.map(bundleFact);
    const byId = new Map(facts.map(f => [f.factId, f]));
    requireSection(byId.size === facts.length && section.fact_refs.length === facts.length && section.fact_refs.every(id => byId.has(id)));
    const manifest = value.result_dependencies;
    exact(manifest, ["schema_version", "project_ref", "run_id", "records"]);
    requireSection(manifest.schema_version === 1 && manifest.project_ref === anchor.identity.project_ref && manifest.run_id === anchor.identity.run_id
      && Array.isArray(manifest.records));
    const records = new Map<string, Record<string, unknown>>(), paths = new Set<string>();
    for (const dep of manifest.records) {
      // Python str.strip whitespace, not JS trim (which also strips BOM).
      function dependencyText(text: unknown): asserts text is string {
        sectionText(text);
        requireSection(!/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]$/.test(text));
      }
      exact(dep, ["artifact_id", "path", "sha256", "index_record"]); dependencyText(dep.artifact_id); sectionDigest(dep.sha256);
      requireSection(Array.isArray(dep.path) && dep.path.length > 2);
      for (const part of dep.path) { dependencyText(part); requireSection(![".", ".."].includes(part) && !/[\\/]/.test(part)); }
      const row = dep.index_record; requireSection(record(row));
      dependencyText(row.path); dependencyText(row.artifact_type); dependencyText(row.step);
      requireSection(row.artifact_id === dep.artifact_id && row.sha256 === dep.sha256
        && JSON.stringify(dep.path) === JSON.stringify(["runs", anchor.identity.run_id, ...row.path.split("/")])
        && !records.has(dep.artifact_id) && !paths.has(dep.path.join("/")));
      for (const [key, expected] of [["project_ref", anchor.identity.project_ref], ["run_id", anchor.identity.run_id], ["evidence_run_id", anchor.identity.run_id]]) {
        if (own(row, key)) requireSection(row[key] === expected);
      }
      requireSection(!["report", "export"].includes(row.step) && !["report", "report_evidence", "export", "table_export"].includes(row.artifact_type)
        && !["report", "report_evidence", "export"].includes(dep.artifact_id.split(":")[0])
        && !["artifacts_index.json", "report_evidence.json"].includes(dep.path[dep.path.length - 1]));
      records.set(dep.artifact_id, dep); paths.add(dep.path.join("/"));
    }
    const closure = new Set(section.dependency_refs);
    for (const raw of value.facts) {
      const selector = raw.source_selector;
      requireSection(records.get(selector.artifact_ref)?.sha256 === selector.artifact_digest); closure.add(selector.artifact_ref);
    }
    requireSection(closure.size === records.size && [...closure].every(id => records.has(id)));
    const meta = value.projection_metadata;
    exact(meta, ["consumer_id", "consumer_version", "projection_ref", "envelope_ref", "execution_status", "availability", "completeness_status",
      "numerical_method", "inference_basis", "evaluation_design", "validation_summary", "status", "audit", "lineage_refs",
      "data_snapshot_ref", "data_snapshot_digest", "renderer_key"]);
    requireSection(meta.consumer_id === "report" && meta.consumer_version === "1.0" && meta.renderer_key === TYPED_EVIDENCE_RENDERER_KEY
      && meta.envelope_ref === `evidence-envelope:${anchor.envelope_digest}` && meta.availability === "available");
    contractRef(meta.projection_ref, { kind: "projection", logical_id: "workbench.consumer_projection.report", semantic_version: "1.0",
      contract_digest: "a8ef0d53d792009995caa12044aebab7cb94c6aaf8644fa4d358d413956331f8" });
    member(meta.status, ["available", "degraded"]); member(meta.execution_status, ["completed", "partial", "blocked", "failed"]);
    member(meta.completeness_status, ["complete", "degraded", "insufficient", "not_applicable"]);
    member(meta.numerical_method, ["closed_form", "deterministic_numeric", "simulation", "approximate_algorithm"]);
    member(meta.inference_basis, ["exact_distribution", "asymptotic", "bootstrap", "descriptive", "not_applicable"]);
    member(meta.evaluation_design, EVALUATION_DESIGNS); sectionRefs(meta.lineage_refs, false);
    if (meta.data_snapshot_ref === null) requireSection(meta.data_snapshot_digest === null);
    else { sectionText(meta.data_snapshot_ref); sectionDigest(meta.data_snapshot_digest); }
    const summary = meta.validation_summary;
    exact(summary, ["levels_present", "minimum_required", "requirement_status"]);
    member(summary.minimum_required, VALIDATION_LEVELS); sectionRefs(summary.levels_present, false);
    let previous = -1;
    for (const level of summary.levels_present) { member(level, VALIDATION_LEVELS); const rank = VALIDATION_LEVELS.indexOf(level); requireSection(rank > previous); previous = rank; }
    const expectedStatus = summary.minimum_required === "none" ? "not_applicable"
      : summary.levels_present.length > 0 && summary.levels_present.every(level => VALIDATION_LEVELS.indexOf(level) >= VALIDATION_LEVELS.indexOf(summary.minimum_required as string)) ? "met" : "not_met";
    requireSection(summary.requirement_status === expectedStatus);
    const audit = meta.audit;
    exact(audit, ["policy_ref", "destination", "requested_fact_ids", "selected_fact_ids", "omitted_fact_ids", "redacted_fact_ids",
      "requested_section_ids", "selected_section_ids", "omitted_section_ids", "redacted_section_ids", "raw_rows_rejected", "restriction_reason", "row_budget", "token_budget"]);
    contractRef(audit.policy_ref, REPORT_LOCAL_POLICY);
    requireSection(audit.destination === "local" && audit.raw_rows_rejected === false && audit.restriction_reason === null);
    for (const key of ["requested_fact_ids", "selected_fact_ids", "omitted_fact_ids", "redacted_fact_ids", "requested_section_ids", "selected_section_ids", "omitted_section_ids", "redacted_section_ids"]) sectionRefs(audit[key], false);
    requireSection((audit.redacted_fact_ids as string[]).length === 0 && (audit.redacted_section_ids as string[]).length === 0
      && JSON.stringify(audit.requested_section_ids) === JSON.stringify([sectionId]) && JSON.stringify(audit.selected_section_ids) === JSON.stringify([sectionId])
      && JSON.stringify(audit.selected_fact_ids) === JSON.stringify(facts.map(f => f.factId))
      && (audit.requested_fact_ids as string[]).length === facts.length && (audit.requested_fact_ids as string[]).every(id => byId.has(id))
      && !(audit.omitted_section_ids as string[]).includes(sectionId) && !(audit.omitted_fact_ids as string[]).some(id => byId.has(id)));
    for (const key of ["row_budget", "token_budget"]) requireSection(Number.isSafeInteger(audit[key]) && (audit[key] as number) >= 0);
    // Resolution only. The existing paired-tree parser below validates every
    // node kind, exact field set, numeric role and section-specific schema.
    const resolve = (node: unknown, depth = 0): ResolvedSectionContent => {
      requireSection(depth <= MAX_SECTION_DEPTH && record(node));
      switch (node.kind) {
        case "null": return null;
        case "text": requireSection(typeof node.value === "string"); return node.value;
        case "boolean": requireSection(typeof node.value === "boolean"); return node.value;
        case "missing": sectionText(node.status); sectionText(node.reason); return { status: node.status, reason: node.reason };
        case "fact": sectionText(node.fact_id); { const f = byId.get(node.fact_id); requireSection(f); return f.value; }
        case "list": requireSection(Array.isArray(node.items)); return node.items.map(n => resolve(n, depth + 1));
        case "object": requireSection(record(node.fields)); return Object.fromEntries(Object.entries(node.fields).map(([k, n]) => [k, resolve(n, depth + 1)]));
        default: throw new InvalidStructuredResults();
      }
    };
    const parsed = readStructuredSections({ facts, structuredResults: { schema_version: 1, contract_digest: RESULT_SECTIONS_DIGEST, sections: [section] },
      resolvedSections: [{ sectionId, sectionType: section.section_type, status: section.status, reasonCodes: section.reason_codes, content: resolve(section.content) }] });
    requireSection(parsed?.resolvedSections?.length === 1);
    return { section: parsed.resolvedSections[0], facts: copySectionWire(value.facts) as ResolvedSectionContent[],
      dependencies: copySectionWire(manifest) as ResolvedSectionContent, metadata: copySectionWire(meta) as ResolvedSectionContent,
      resultIdentity: copySectionWire(value.result_identity) as ResolvedSectionContent,
      structuredSection: copySectionWire(section) as ResolvedSectionContent };
  } catch {
    throw new ResultReadError("RESULT_SECTION_BUNDLE_INVALID", "Complete bytes do not satisfy the ordinary section/fact contract and directory binding.");
  }
}

const PROJECTION_STATUSES = new Set<EvidenceProjectionStatus>([
  "available",
  "unavailable",
  "degraded",
  "blocked",
]);
const PERSISTED_CONSUMER_IDS = new Set(["results", "agent", "notebook", "report", "ui"]);

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function status(value: unknown): value is EvidenceProjectionStatus {
  return typeof value === "string" && PROJECTION_STATUSES.has(value as EvidenceProjectionStatus);
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function interval(value: unknown): EvidenceIntervalViewModel | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (!finiteNumber(candidate.lower) || !finiteNumber(candidate.upper) || candidate.lower > candidate.upper) return null;
  if (candidate.method !== undefined && !text(candidate.method)) return null;
  if (candidate.confidenceLevel !== undefined && !finiteNumber(candidate.confidenceLevel)) return null;
  return {
    lower: candidate.lower,
    upper: candidate.upper,
    ...(candidate.method === undefined ? {} : { method: candidate.method }),
    ...(candidate.confidenceLevel === undefined ? {} : { confidenceLevel: candidate.confidenceLevel }),
  };
}

function validationProvenance(value: unknown): value is EvidenceValidationProvenance {
  return text(value) || record(value);
}

function textArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every(text);
}

function pairedText(
  candidate: Record<string, unknown>,
  camelKey: string,
  snakeKey: string,
): string | null | undefined {
  const camel = candidate[camelKey];
  const snake = candidate[snakeKey];
  if (camel === undefined && snake === undefined) return undefined;
  if ((camel !== undefined && !text(camel)) || (snake !== undefined && !text(snake))) return null;
  if (camel !== undefined && snake !== undefined && camel !== snake) return null;
  return (camel ?? snake) as string;
}

function provenance(value: unknown): value is EvidenceProvenanceViewModel {
  if (!record(value)) return false;
  const candidate = value as Record<string, unknown>;
  for (const key of [
    "artifactRef",
    "artifactId",
    "artifactType",
    "scopeRef",
    "contentHash",
    "sourceRef",
    "executionRef",
    "contractDigest",
    "commitId",
    "envelopeRef",
    "envelopeDigest",
    "dataSnapshotRef",
    "dataSnapshotDigest",
    "admissionStatus",
  ]) {
    if (candidate[key] !== undefined && !text(candidate[key])) return false;
  }
  if (candidate.validatorRef !== undefined && !validationProvenance(candidate.validatorRef)) return false;
  if (candidate.lineageRefs !== undefined && !textArray(candidate.lineageRefs)) return false;
  if (candidate.envelopeDigests !== undefined && !textArray(candidate.envelopeDigests)) return false;
  if (candidate.projectionRef !== undefined && !record(candidate.projectionRef)) return false;
  if (candidate.resultIdentity !== undefined && !record(candidate.resultIdentity)) return false;
  if (candidate.projections !== undefined
    && (!Array.isArray(candidate.projections) || !candidate.projections.every(record))) return false;
  return candidate.indexed === undefined || typeof candidate.indexed === "boolean";
}

function fact(value: unknown): value is EvidenceFactViewModel {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  if (!text(candidate.factId)
    || !text(candidate.statisticId)
    || !((typeof candidate.value === "number" && Number.isFinite(candidate.value)) || typeof candidate.value === "string")) {
    return false;
  }
  if (candidate.unit !== undefined && candidate.unit !== null && !text(candidate.unit)) return false;
  if (candidate.standardError !== undefined && !finiteNumber(candidate.standardError)) return false;
  if (candidate.interval !== undefined && interval(candidate.interval) === null) return false;
  if (candidate.confidenceInterval !== undefined && interval(candidate.confidenceInterval) === null) return false;
  if (candidate.interval !== undefined && candidate.confidenceInterval !== undefined) {
    const left = interval(candidate.interval)!;
    const right = interval(candidate.confidenceInterval)!;
    if (left.lower !== right.lower || left.upper !== right.upper) return false;
  }
  if (candidate.caveat !== undefined && !text(candidate.caveat)) return false;
  if (candidate.availability !== undefined && !text(candidate.availability)) return false;
  if (candidate.validationProvenance !== undefined && !validationProvenance(candidate.validationProvenance)) return false;
  return true;
}

function readFact(value: unknown): EvidenceFactViewModel | null {
  if (!fact(value)) return null;
  const candidate = value as unknown as Record<string, unknown>;
  const parsedInterval = candidate.interval === undefined ? undefined : interval(candidate.interval)!;
  const parsedConfidenceInterval = candidate.confidenceInterval === undefined
    ? undefined
    : interval(candidate.confidenceInterval)!;
  const parsedCanonicalInterval = parsedInterval ?? parsedConfidenceInterval;
  return {
    factId: candidate.factId as string,
    statisticId: candidate.statisticId as string,
    value: candidate.value as number | string,
    ...(candidate.unit === undefined ? {} : { unit: candidate.unit as string | null }),
    ...(parsedCanonicalInterval === undefined ? {} : { interval: parsedCanonicalInterval }),
    ...(candidate.caveat === undefined ? {} : { caveat: candidate.caveat as string }),
    ...(candidate.availability === undefined ? {} : { availability: candidate.availability as string }),
    ...(candidate.validationProvenance === undefined ? {} : { validationProvenance: candidate.validationProvenance as EvidenceValidationProvenance }),
    ...(candidate.standardError === undefined ? {} : { standardError: candidate.standardError as number }),
    ...(parsedConfidenceInterval === undefined ? {} : { confidenceInterval: parsedConfidenceInterval }),
  };
}

function section(value: unknown): value is EvidenceSectionViewModel {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return text(candidate.key) && text(candidate.label) && status(candidate.status);
}

function hasSupportedRenderer(candidate: Record<string, unknown>, expectedConsumerId?: string): boolean {
  const consumerId = expectedConsumerId ?? (typeof candidate.consumerId === "string" ? candidate.consumerId : undefined);
  const values = ["rendererKey", "renderer_key", "renderer"]
    .map((key) => candidate[key])
    .filter((value): value is string => value !== undefined);
  if (values.length === 0 || values.some((value) => !text(value)) || new Set(values).size !== 1) return false;
  const renderer = values[0];
  return renderer === TYPED_EVIDENCE_RENDERER_KEY
    || renderer === LEGACY_TYPED_EVIDENCE_RENDERER_KEY
    || (consumerId !== undefined && renderer === `workbench.consumer_projection.${consumerId}`);
}

function hasNoRawPayload(candidate: Record<string, unknown>): boolean {
  return ["payload", "rawPayload", "raw_payload", "modelResults", "model_results"].every(
    (key) => candidate[key] === undefined,
  );
}

/** Parse a server-owned typed contribution without inventing absent fields. */
function readPersistedEvidence(value: unknown, expectedConsumerId?: string): EvidenceViewModel | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (!hasSupportedRenderer(candidate, expectedConsumerId) || !hasNoRawPayload(candidate)) return null;
  if (candidate.schemaVersion !== undefined && candidate.schemaVersion !== 1) return null;
  if (candidate.contract !== undefined
    && candidate.contract !== "workbench.report.evidence.v1"
    && candidate.contract !== "workbench.notebook.evidence.v1") return null;
  if (!text(candidate.consumerId)
    || !PERSISTED_CONSUMER_IDS.has(candidate.consumerId)
    || (expectedConsumerId !== undefined && candidate.consumerId !== expectedConsumerId)
    || !text(candidate.projectionId)
    || !text(candidate.consumerVersion)
    || !text(candidate.artifactRef)
    || !text(candidate.envelopeRef)
    || !text(candidate.envelopeDigest)
    || !status(candidate.status)
    || !text(candidate.executionStatus)
    || !text(candidate.availability)
    || !text(candidate.completenessStatus)
    || !text(candidate.validationStatus)
    || !record(candidate.validationSummary)
    || !Array.isArray(candidate.facts)
    || !candidate.facts.every(fact)
    || !Array.isArray(candidate.sections)
    || !candidate.sections.every(section)) {
    return null;
  }
  if (candidate.commitId !== undefined && !text(candidate.commitId)) return null;
  if (candidate.reasonCode !== undefined && !text(candidate.reasonCode)) return null;
  if (candidate.projectionDigest !== undefined
    && (typeof candidate.projectionDigest !== "string"
      || (candidate.projectionDigest !== "UNAVAILABLE" && !/^[0-9a-f]{64}$/.test(candidate.projectionDigest)))) return null;
  for (const key of ["actorRef", "projectRef", "sessionRef", "scopeRef", "runId", "modelRunId", "confirmationRef"]) {
    if (candidate[key] !== undefined && !text(candidate[key])) return null;
  }
  if (candidate.validationProvenance !== undefined && !validationProvenance(candidate.validationProvenance)) return null;
  if (candidate.provenance !== undefined && !provenance(candidate.provenance)) return null;
  if (candidate.lineageRefs !== undefined && !textArray(candidate.lineageRefs)) return null;
  if (candidate.resultIdentity !== undefined && !record(candidate.resultIdentity)) return null;
  if (candidate.identity !== undefined && !record(candidate.identity)) return null;
  const dataSnapshotRef = pairedText(candidate, "dataSnapshotRef", "data_snapshot_ref");
  const dataSnapshotDigest = pairedText(candidate, "dataSnapshotDigest", "data_snapshot_digest");
  if (dataSnapshotRef === null
    || dataSnapshotDigest === null
    || (dataSnapshotRef === undefined) !== (dataSnapshotDigest === undefined)) return null;
  if (dataSnapshotDigest !== undefined && !/^[0-9a-f]{64}$/.test(dataSnapshotDigest)) return null;
  if (candidate.contract !== undefined) {
    const expectedContract = candidate.consumerId === "report"
      ? "workbench.report.evidence.v1"
      : candidate.consumerId === "notebook"
        ? "workbench.notebook.evidence.v1"
        : undefined;
    if (expectedContract !== undefined && candidate.contract !== expectedContract) return null;
  }
  const facts = candidate.facts.map(readFact);
  if (facts.some((item): item is null => item === null)) return null;
  const structured = readStructuredSections(candidate);
  if (structured === null) return null;
  return {
    ...structured,
    ...(candidate.schemaVersion === undefined ? {} : { schemaVersion: candidate.schemaVersion as 1 }),
    projectionId: candidate.projectionId,
    consumerId: candidate.consumerId,
    consumerVersion: candidate.consumerVersion,
    artifactRef: candidate.artifactRef,
    envelopeRef: candidate.envelopeRef,
    envelopeDigest: candidate.envelopeDigest,
    ...(dataSnapshotRef === undefined ? {} : { dataSnapshotRef }),
    ...(dataSnapshotDigest === undefined ? {} : { dataSnapshotDigest }),
    ...(candidate.projectionDigest === undefined ? {} : { projectionDigest: candidate.projectionDigest as string }),
    ...(candidate.actorRef === undefined ? {} : { actorRef: candidate.actorRef as string }),
    ...(candidate.projectRef === undefined ? {} : { projectRef: candidate.projectRef as string }),
    ...(candidate.sessionRef === undefined ? {} : { sessionRef: candidate.sessionRef as string }),
    ...(candidate.scopeRef === undefined ? {} : { scopeRef: candidate.scopeRef as string }),
    ...(candidate.runId === undefined ? {} : { runId: candidate.runId as string }),
    ...(candidate.modelRunId === undefined ? {} : { modelRunId: candidate.modelRunId as string }),
    ...(candidate.confirmationRef === undefined ? {} : { confirmationRef: candidate.confirmationRef as string }),
    ...(candidate.rendererKey === undefined ? {} : { rendererKey: candidate.rendererKey as string }),
    ...(candidate.contract === undefined ? {} : { contract: candidate.contract as string }),
    ...(candidate.commitId === undefined ? {} : { commitId: candidate.commitId as string }),
    status: candidate.status,
    executionStatus: candidate.executionStatus,
    availability: candidate.availability,
    completenessStatus: candidate.completenessStatus,
    validationStatus: candidate.validationStatus,
    validationSummary: candidate.validationSummary,
    ...(candidate.validationProvenance === undefined ? {} : { validationProvenance: candidate.validationProvenance as EvidenceValidationProvenance }),
    ...(candidate.provenance === undefined ? {} : { provenance: candidate.provenance as EvidenceProvenanceViewModel }),
    ...(candidate.lineageRefs === undefined ? {} : { lineageRefs: candidate.lineageRefs as readonly string[] }),
    ...(candidate.resultIdentity === undefined ? {} : { resultIdentity: candidate.resultIdentity as Record<string, unknown> }),
    ...(candidate.identity === undefined ? {} : { identity: candidate.identity as Record<string, unknown> }),
    ...(candidate.reasonCode === undefined ? {} : { reasonCode: candidate.reasonCode as string }),
    facts: facts as EvidenceFactViewModel[],
    sections: candidate.sections,
  };
}

/** Runtime gate for UI consumers receiving data across the server boundary. */
export function isPersistedReportEvidenceProjection(value: unknown): value is EvidenceViewModel {
  return readReportEvidence(value) !== null;
}

export function readPersistedEvidenceProjection(value: unknown): EvidenceViewModel | null {
  return readPersistedEvidence(value);
}

export function readReportEvidence(value: unknown): EvidenceViewModel | null {
  return readPersistedEvidence(value, "report");
}

/** Runtime gate for non-Report consumers that still use the same projection. */
export function isPersistedEvidenceProjection(value: unknown): value is EvidenceViewModel {
  return readPersistedEvidenceProjection(value) !== null;
}
