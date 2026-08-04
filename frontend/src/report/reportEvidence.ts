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

export interface ReportCapabilityManifestEntry {
  capability_id: string;
  provider_id: string;
  availability: "available" | "unavailable" | "not_applicable";
  validation_level: "external_oracle" | "internal_only" | "unverified";
  report_modules: string[];
  limitations: string[];
}

/**
 * Reader-facing provider registry. New evidence providers should add a
 * prefix/module entry here instead of adding model-specific branches to the
 * Report view. Unknown fields intentionally remain visible in `other`.
 */
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
    if (current) {
      current.facts.push(fact);
    } else {
      groups.set(definition.id, {
        id: definition.id,
        label: definition.label,
        facts: [fact],
      });
    }
  }
  return EVIDENCE_GROUPS
    .filter((definition) => groups.has(definition.id))
    .map((definition) => groups.get(definition.id)!);
}

export function groupFactIds(group: EvidenceGroup): string[] {
  return group.facts.map((fact) => fact.id);
}

/** Capability modules are derived from the provider registry, not model names. */
export function reportCapabilitiesForFacts(facts: CitableFact[]): string[] {
  const fields = facts.map((fact) => fact.field);
  const capabilities: string[] = [];
  for (const definition of EVIDENCE_GROUPS) {
    if (!definition.capability) continue;
    if (fields.some((field) => definition.prefixes.some((prefix) => field.startsWith(prefix)))) {
      capabilities.push(definition.capability);
    }
  }
  return capabilities;
}

/**
 * Send provider identity alongside the compact capability list.  The report
 * writer can then explain which module was unavailable or internally
 * validated, while future providers can register without adding model-name
 * branches to ReportView.
 */
export function reportCapabilityManifestForFacts(
  facts: CitableFact[],
): ReportCapabilityManifestEntry[] {
  const groups = groupFacts(facts);
  return EVIDENCE_GROUPS.flatMap((definition) => {
    if (!definition.capability) return [];
    const group = groups.find((candidate) => candidate.id === definition.id);
    if (!group) return [];
    const providerId = group.facts.find((fact) => fact.provider_id)?.provider_id
      ?? definition.provider_id
      ?? `evidence.${definition.id}.v1`;
    return [{
      capability_id: definition.capability,
      provider_id: providerId,
      availability: "available" as const,
      validation_level: "internal_only" as const,
      report_modules: [definition.id],
      limitations: [],
    }];
  });
}

/**
 * Keep the evidence table readable without hiding the canonical field key.
 * The raw key stays in the disclosure so future providers can use arbitrary
 * names while the default view remains a reader-facing table.
 */
export function displayEvidenceLabel(fact: CitableFact): string {
  const label = fact.label || fact.field;
  if (label.length === 0) return label;
  const readable = label.replace(/_/g, " ");
  const withInitial = `${readable.slice(0, 1).toLocaleUpperCase()}${readable.slice(1)}`;
  return withInitial.replace(/\b(rmse|mae|aicc|aic|bic|arma|garch|arch)\b/gi, (token) => token.toUpperCase());
}
