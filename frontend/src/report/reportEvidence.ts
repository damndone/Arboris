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

export interface EvidenceFactViewModel {
  readonly factId: string;
  readonly statisticId: string;
  readonly value: number | string;
  readonly unit?: string;
  readonly standardError?: number;
  readonly confidenceInterval?: Readonly<{
    lower: number;
    upper: number;
  }>;
}

export interface EvidenceSectionViewModel {
  readonly key: string;
  readonly label: string;
  readonly status: EvidenceSectionStatus;
}

export interface EvidenceViewModel {
  readonly projectionId: string;
  readonly consumerId: string;
  readonly consumerVersion: string;
  readonly artifactRef: string;
  readonly envelopeRef: string;
  readonly envelopeDigest: string;
  readonly status: EvidenceProjectionStatus;
  readonly executionStatus: string;
  readonly availability: string;
  readonly completenessStatus: string;
  readonly facts: readonly EvidenceFactViewModel[];
  readonly sections: readonly EvidenceSectionViewModel[];
}

const PROJECTION_STATUSES = new Set<EvidenceProjectionStatus>([
  "available",
  "unavailable",
  "degraded",
  "blocked",
]);

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function status(value: unknown): value is EvidenceProjectionStatus {
  return typeof value === "string" && PROJECTION_STATUSES.has(value as EvidenceProjectionStatus);
}

function fact(value: unknown): value is EvidenceFactViewModel {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return text(candidate.factId)
    && text(candidate.statisticId)
    && (typeof candidate.value === "number" || typeof candidate.value === "string");
}

function section(value: unknown): value is EvidenceSectionViewModel {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return text(candidate.key) && text(candidate.label) && status(candidate.status);
}

/** Parse a server-owned typed contribution without inventing absent fields. */
export function readReportEvidence(value: unknown): EvidenceViewModel | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (!text(candidate.projectionId)
    || !text(candidate.consumerId)
    || !text(candidate.consumerVersion)
    || !text(candidate.artifactRef)
    || !text(candidate.envelopeRef)
    || !text(candidate.envelopeDigest)
    || !status(candidate.status)
    || !text(candidate.executionStatus)
    || !text(candidate.availability)
    || !text(candidate.completenessStatus)
    || !Array.isArray(candidate.facts)
    || !candidate.facts.every(fact)
    || !Array.isArray(candidate.sections)
    || !candidate.sections.every(section)) {
    return null;
  }
  return {
    projectionId: candidate.projectionId,
    consumerId: candidate.consumerId,
    consumerVersion: candidate.consumerVersion,
    artifactRef: candidate.artifactRef,
    envelopeRef: candidate.envelopeRef,
    envelopeDigest: candidate.envelopeDigest,
    status: candidate.status,
    executionStatus: candidate.executionStatus,
    availability: candidate.availability,
    completenessStatus: candidate.completenessStatus,
    facts: candidate.facts,
    sections: candidate.sections,
  };
}
