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
  return {
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
