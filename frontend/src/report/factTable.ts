// v1.6.11 slice C — deterministic citable-fact extraction.
//
// The fact table is the anti-hallucination contract: it is built HERE, from
// the same pure context resolver the drawer uses, and sent to the model as the
// only permitted source of numbers. Chips later render from this local table
// (never from model output), so an invented number can never become a chip.
import type { ForestViewModel } from "../lineage/api/graphViewTypes";
import { resolveNodeOperationContext } from "../lineage/api/nodeOperationContext";
import {
  readReportEvidence,
  type EvidenceViewModel,
} from "./reportEvidence";

export interface CitableFact {
  id: string;
  node_key: string;
  node_label: string;
  /** e.g. "param:covariance", "metric:r_squared", "decision:standard_errors" */
  field: string;
  label: string;
  value: unknown;
  /** Optional provider metadata; old facts remain valid without it. */
  provider_id?: string;
  kind?: "estimate" | "diagnostic" | "sample" | "decision" | "metadata" | string;
  unit?: string | null;
  artifact_ids?: string[];
  claim_types?: string[];
  validation_level?: "external_oracle" | "internal_only" | "unverified" | string;
  qualifiers?: Record<string, unknown>;
}

export interface ReportEvidenceProvenance {
  readonly artifactRef?: string;
  readonly artifactId?: string;
  readonly artifactType?: string;
  readonly commitId?: string;
  readonly envelopeRef?: string;
  readonly lineageRefs?: readonly string[];
  readonly projectionRef?: Record<string, unknown>;
  readonly resultIdentity?: Record<string, unknown>;
  readonly indexed?: boolean;
  readonly admissionStatus?: string;
  readonly projections?: readonly Record<string, unknown>[];
  readonly envelopeDigests?: readonly string[];
}

export interface ReportEvidenceIdentity {
  readonly actorRef: string;
  readonly projectRef: string;
  readonly sessionRef: string;
  readonly scopeRef: string;
  readonly runId: string;
  readonly modelRunId: string;
  readonly artifactRef: string;
  readonly commitId: string;
  readonly confirmationRef: string;
}

export type ReportEvidenceProjection = EvidenceViewModel & {
  readonly schemaVersion: 1;
  readonly actorRef: string;
  readonly projectRef: string;
  readonly sessionRef: string;
  readonly scopeRef: string;
  readonly runId: string;
  readonly modelRunId: string;
  readonly validationStatus: string;
  readonly validationSummary: Readonly<Record<string, unknown>>;
  readonly commitId: string;
  readonly confirmationRef: string;
  readonly reasonCode?: string;
  readonly provenance: ReportEvidenceProvenance;
};

function asEvidenceRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function readEvidenceProvenance(value: unknown): ReportEvidenceProvenance | null {
  const record = asEvidenceRecord(value);
  if (!record) return null;
  const provenance: ReportEvidenceProvenance = {};
  for (const key of [
    "artifactRef",
    "artifactId",
    "artifactType",
    "commitId",
    "envelopeRef",
    "admissionStatus",
  ] as const) {
    if (record[key] !== undefined && typeof record[key] !== "string") return null;
    if (typeof record[key] === "string") {
      (provenance as Record<string, unknown>)[key] = record[key];
    }
  }
  if (record.indexed !== undefined && typeof record.indexed !== "boolean") return null;
  if (record.indexed === true) {
    (provenance as Record<string, unknown>).indexed = true;
  }
  if (record.lineageRefs !== undefined) {
    if (!Array.isArray(record.lineageRefs) || !record.lineageRefs.every((item) => typeof item === "string")) return null;
    (provenance as Record<string, unknown>).lineageRefs = record.lineageRefs;
  }
  if (record.envelopeDigests !== undefined) {
    if (!Array.isArray(record.envelopeDigests) || !record.envelopeDigests.every((item) => typeof item === "string")) return null;
    (provenance as Record<string, unknown>).envelopeDigests = record.envelopeDigests;
  }
  if (record.projectionRef !== undefined) {
    const projectionRef = asEvidenceRecord(record.projectionRef);
    if (!projectionRef) return null;
    (provenance as Record<string, unknown>).projectionRef = projectionRef;
  }
  if (record.resultIdentity !== undefined) {
    const resultIdentity = asEvidenceRecord(record.resultIdentity);
    if (!resultIdentity) return null;
    (provenance as Record<string, unknown>).resultIdentity = resultIdentity;
  }
  if (record.projections !== undefined) {
    if (!Array.isArray(record.projections)) return null;
    const projections = record.projections
      .map(asEvidenceRecord)
      .filter((item): item is Record<string, unknown> => item !== null);
    if (projections.length !== record.projections.length) return null;
    (provenance as Record<string, unknown>).projections = projections;
  }
  return provenance;
}

/** Parse the server-owned report projection, including its provenance gate. */
export function readReportEvidenceProjection(
  value: unknown,
  expectedIdentity?: Partial<ReportEvidenceIdentity>,
): ReportEvidenceProjection | null {
  const base = readReportEvidence(value);
  if (!base || !asEvidenceRecord(value)) return null;
  const candidate = asEvidenceRecord(value)!;
  if (candidate.schemaVersion !== 1) return null;
  const identityKeys = [
    "actorRef",
    "projectRef",
    "sessionRef",
    "scopeRef",
    "runId",
    "modelRunId",
    "artifactRef",
    "commitId",
    "confirmationRef",
  ] as const;
  if (identityKeys.some((key) => typeof candidate[key] !== "string" || String(candidate[key]).trim().length === 0)) {
    return null;
  }
  for (const key of identityKeys) {
    const expected = expectedIdentity?.[key];
    if (expected !== undefined && candidate[key] !== expected) return null;
  }
  const provenance = readEvidenceProvenance(candidate.provenance);
  if (!provenance) return null;
  const parsedStatus = base.status;
  if (candidate.consumerId !== "report" || candidate.consumerVersion !== "1.0") return null;
  const validationStatus = candidate.validationStatus;
  const validationSummary = asEvidenceRecord(candidate.validationSummary);
  if (typeof validationStatus !== "string" || validationStatus.trim().length === 0 || !validationSummary) return null;
  const parsedValidationStatus: string = validationStatus;
  const commitId = candidate.commitId;
  const reasonCode = candidate.reasonCode;
  if (typeof commitId !== "string") return null;
  if (reasonCode !== undefined && typeof reasonCode !== "string") return null;
  if (typeof provenance.commitId === "string" && provenance.commitId !== commitId) return null;
  if (typeof provenance.artifactRef === "string" && provenance.artifactRef !== candidate.artifactRef) return null;
  if (typeof provenance.envelopeRef === "string" && provenance.envelopeRef !== candidate.envelopeRef) return null;
  if (
    Array.isArray(provenance.envelopeDigests)
    && !provenance.envelopeDigests.includes(candidate.envelopeDigest)
  ) return null;
  const resultIdentity = provenance.resultIdentity;
  if (resultIdentity) {
    for (const key of ["projectRef", "sessionRef", "scopeRef", "runId", "modelRunId"] as const) {
      if (resultIdentity[key] !== undefined && resultIdentity[key] !== candidate[key]) return null;
    }
  }
  if (parsedStatus === "available") {
    if (
      candidate.availability !== "available"
      || candidate.executionStatus !== "completed"
      || candidate.completenessStatus !== "complete"
      || candidate.validationStatus === "unavailable"
      || commitId === "UNAVAILABLE"
      || candidate.envelopeDigest === "UNAVAILABLE"
      || candidate.projectionId !== `${candidate.consumerId}:${commitId}`
      || identityKeys.some((key) => candidate[key] === "UNAVAILABLE")
    ) return null;
  } else {
    if (base.facts.length !== 0) return null;
    if (["degraded", "blocked"].includes(parsedStatus) && ["met", "validated", "complete"].includes(parsedValidationStatus)) return null;
    if (parsedStatus === "unavailable" && candidate.availability === "available") return null;
  }
  return {
    ...base,
    schemaVersion: 1,
    actorRef: candidate.actorRef as string,
    projectRef: candidate.projectRef as string,
    sessionRef: candidate.sessionRef as string,
    scopeRef: candidate.scopeRef as string,
    runId: candidate.runId as string,
    modelRunId: candidate.modelRunId as string,
    confirmationRef: candidate.confirmationRef as string,
    validationStatus,
    validationSummary,
    commitId,
    ...(reasonCode !== undefined ? { reasonCode } : {}),
    provenance,
  };
}

/** Construct a typed empty contribution when the server cannot admit facts. */
export function unavailableReportEvidence(
  reasonCode: string,
  artifactRef = "UNAVAILABLE",
): ReportEvidenceProjection {
  return {
    schemaVersion: 1,
    projectionId: `report:unavailable:${artifactRef}`,
    consumerId: "report",
    consumerVersion: "1.0",
    actorRef: "UNAVAILABLE",
    projectRef: "UNAVAILABLE",
    sessionRef: "UNAVAILABLE",
    scopeRef: "UNAVAILABLE",
    runId: artifactRef.startsWith("run:") ? artifactRef.slice(4) : "UNAVAILABLE",
    modelRunId: "UNAVAILABLE",
    artifactRef,
    envelopeRef: "UNAVAILABLE",
    commitId: "UNAVAILABLE",
    envelopeDigest: "UNAVAILABLE",
    status: "unavailable",
    executionStatus: "unavailable",
    availability: "unavailable",
    completenessStatus: "unavailable",
    validationStatus: "unavailable",
    confirmationRef: "UNAVAILABLE",
    validationSummary: {
      status: "unavailable",
      reasonCode,
    },
    facts: [],
    sections: [{ key: "persisted-evidence", label: "Persisted evidence", status: "unavailable" }],
    reasonCode,
    provenance: {
      artifactId: artifactRef,
      indexed: true,
      admissionStatus: "unavailable",
    },
  };
}

const MAX_TYPED_EVIDENCE_FACTS = 80;

function typedFactLabel(statisticId: string): string {
  const labels: Record<string, string> = {
    "ts:arma:selected_candidate": "Selected ARMA specification",
    "ts:validation:rmse": "Validation RMSE",
    "ts:contract:transform": "Analysis transform",
    "ts:data:analysis_observations": "Analysis-view observations",
  };
  const parts = statisticId.split(":");
  return labels[statisticId] ?? parts[parts.length - 1]?.replace(/_/g, " ") ?? statisticId;
}

/** Convert only the bounded server projection into citable report facts. */
export function buildReportEvidenceFacts(
  evidence: ReportEvidenceProjection | null | undefined,
  startAt = 0,
): CitableFact[] {
  if (!evidence || evidence.status !== "available") return [];
  const commitId = evidence.commitId ?? evidence.provenance.commitId;
  return evidence.facts.slice(0, MAX_TYPED_EVIDENCE_FACTS).map((fact, index) => ({
    id: `c${startAt + index + 1}`,
    node_key: `evidence:${evidence.projectionId}`,
    node_label: "Persisted report evidence",
    field: fact.statisticId,
    label: `${typedFactLabel(fact.statisticId)}${fact.unit ? ` (${fact.unit})` : ""}`,
    value: fact.value,
    provider_id: "evidence.report.typed.v1",
    kind: "estimate",
    artifact_ids: [evidence.artifactRef],
    qualifiers: {
      projection_id: evidence.projectionId,
      commit_id: commitId ?? "UNAVAILABLE",
      envelope_digest: evidence.envelopeDigest,
      fact_id: fact.factId,
      provenance: evidence.provenance,
    },
  }));
}

export interface ReportScope {
  run_id: string;
  node_count: number;
  node_keys: string[];
}

/** Only stable figure identity may enter a Report generation packet. */
export interface FigureFactInput {
  artifact_id: string;
  chart_type: string;
}

/** Legacy raw figure inputs are permanently outside the Report boundary. */
export function buildFigureFacts(
  figures: readonly unknown[],
  startAt = 0,
): CitableFact[] {
  void figures;
  void startAt;
  return [];
}

function isAtomicFact(value: unknown): value is string | number | boolean {
  return (
    (typeof value === "string" && value !== "")
    || (typeof value === "number" && Number.isFinite(value))
    || typeof value === "boolean"
  );
}

/** Legacy raw post-estimation payloads are permanently outside the Report boundary. */
export function buildPostEstimationFacts(
  results: readonly unknown[],
  startAt = 0,
): CitableFact[] {
  void results;
  void startAt;
  return [];
}

/** Raw time-series JSON is permanently outside the Report boundary. */
export function buildTimeSeriesFacts(
  artifacts: unknown,
  startAt = 0,
  provenance?: { nodeKey: string; nodeLabel: string },
): CitableFact[] {
  void artifacts;
  void startAt;
  void provenance;
  return [];
}

export function buildFactTable(
  forest: ForestViewModel,
  activeRunId: string,
): { facts: CitableFact[]; scope: ReportScope; fingerprints: string[] } {
  const pathNodes = forest.nodes.filter((node) => (node.runs ?? []).includes(activeRunId));
  const facts: CitableFact[] = [];
  const fingerprints: string[] = [];
  let counter = 0;
  const nextId = () => `c${++counter}`;

  for (const node of pathNodes) {
    const resolved = resolveNodeOperationContext({
      forest,
      selected_forest_node_key: node.nodeKey,
      active_head_run_id: activeRunId,
    });
    if (!resolved.ok) continue;
    const context = resolved.context;
    fingerprints.push(context.context_fingerprint);
    const nodeLabel = context.selection.display_label;

    for (const [key, value] of Object.entries(context.node_payload.params)) {
      if (!isAtomicFact(value)) continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `param:${key}`,
        label: key,
        value,
      });
    }
    const metrics = context.node_payload.metrics ?? {};
    for (const [key, value] of Object.entries(metrics)) {
      if (value === null || value === undefined) continue;
      if (typeof value === "object") continue; // scalars only — keep facts atomic
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `metric:${key}`,
        label: key,
        value,
      });
    }
    // v1.6.11 C-2 — model coefficient rows (serve-time decoration) expand into
    // atomic per-term facts so the report can cite estimates and p-values.
    const coefficientRows = Array.isArray(metrics.coefficients)
      ? metrics.coefficients
      : [];
    for (const row of coefficientRows) {
      if (!row || typeof row !== "object") continue;
      const { variable, estimate, std_error, p_value } = row as Record<string, unknown>;
      if (typeof variable !== "string" || typeof estimate !== "number") continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `coef:${variable}`,
        label: `coefficient (${variable})`,
        value: estimate,
      });
      if (typeof std_error === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_se:${variable}`,
          label: `std. error (${variable})`,
          value: std_error,
        });
      }
      if (typeof p_value === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_p:${variable}`,
          label: `p-value (${variable})`,
          value: p_value,
        });
      }
    }
    for (const decision of context.node_payload.decisions) {
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `decision:${decision.id}`,
        label: decision.question,
        value: decision.picked,
      });
    }
  }

  return {
    facts,
    scope: {
      run_id: activeRunId,
      node_count: pathNodes.length,
      node_keys: pathNodes.map((n) => n.nodeKey),
    },
    fingerprints,
  };
}
