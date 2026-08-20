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
  readonly artifactRef: string;
  readonly artifactId?: string;
  readonly artifactType: string;
  readonly scopeRef: string;
  readonly contentHash: string;
  readonly sourceRef: string;
  readonly validatorRef: string | Record<string, unknown>;
  readonly executionRef: string;
  readonly contractDigest: string;
  readonly commitId: string;
  readonly envelopeRef: string;
  readonly envelopeDigest: string;
  readonly lineageRefs: readonly string[];
  readonly projectionRef: Record<string, unknown>;
  readonly resultIdentity: Record<string, unknown>;
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
  /** Server-owned canonical digest; unavailable projections use a typed sentinel. */
  readonly projectionDigest: string;
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
  const parsedProvenance: Record<string, unknown> = {};
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
      parsedProvenance[key] = record[key];
    }
  }
  if (record.indexed !== undefined && typeof record.indexed !== "boolean") return null;
  if (record.indexed === true) {
    parsedProvenance.indexed = true;
  }
  if (record.lineageRefs !== undefined) {
    if (!Array.isArray(record.lineageRefs) || !record.lineageRefs.every((item) => typeof item === "string")) return null;
    parsedProvenance.lineageRefs = record.lineageRefs;
  }
  if (record.envelopeDigests !== undefined) {
    if (!Array.isArray(record.envelopeDigests) || !record.envelopeDigests.every((item) => typeof item === "string")) return null;
    parsedProvenance.envelopeDigests = record.envelopeDigests;
  }
  if (record.projectionRef !== undefined) {
    const projectionRef = asEvidenceRecord(record.projectionRef);
    if (!projectionRef) return null;
    parsedProvenance.projectionRef = projectionRef;
  }
  if (record.resultIdentity !== undefined) {
    const resultIdentity = asEvidenceRecord(record.resultIdentity);
    if (!resultIdentity) return null;
    parsedProvenance.resultIdentity = resultIdentity;
  }
  if (record.projections !== undefined) {
    if (!Array.isArray(record.projections)) return null;
    const projections = record.projections
      .map(asEvidenceRecord)
      .filter((item): item is Record<string, unknown> => item !== null);
    if (projections.length !== record.projections.length) return null;
    parsedProvenance.projections = projections;
  }
  const requiredTextKeys = [
    "artifactRef",
    "artifactType",
    "scopeRef",
    "sourceRef",
    "executionRef",
    "commitId",
    "envelopeRef",
    "envelopeDigest",
    "contractDigest",
  ] as const;
  if (requiredTextKeys.some((key) => typeof record[key] !== "string" || record[key] === "" || record[key] === "UNAVAILABLE")) {
    return null;
  }
  const digestKeys = ["contentHash", "contractDigest", "envelopeDigest"] as const;
  if (digestKeys.some((key) => typeof record[key] !== "string" || !/^[0-9a-f]{64}$/.test(record[key] as string))) {
    return null;
  }
  const validatorRef = record.validatorRef;
  if (typeof validatorRef === "string") {
    if (!validatorRef.trim() || validatorRef === "UNAVAILABLE") return null;
  } else {
    const validatorRecord = asEvidenceRecord(validatorRef);
    if (!validatorRecord) return null;
    for (const key of ["kind", "logical_id", "semantic_version", "contract_digest"] as const) {
      if (typeof validatorRecord[key] !== "string" || validatorRecord[key] === "") return null;
    }
    if (!/^[0-9a-f]{64}$/.test(validatorRecord.contract_digest as string)) return null;
  }
  const projectionRef = asEvidenceRecord(record.projectionRef);
  if (!projectionRef) return null;
  for (const key of ["kind", "logical_id", "semantic_version", "contract_digest"] as const) {
    if (typeof projectionRef[key] !== "string" || projectionRef[key] === "") return null;
  }
  if (!/^[0-9a-f]{64}$/.test(projectionRef.contract_digest as string)) return null;
  if (!Array.isArray(record.lineageRefs) || !record.lineageRefs.every((item) => typeof item === "string" && item.trim() !== "")) {
    return null;
  }
  const resultIdentity = asEvidenceRecord(record.resultIdentity);
  if (!resultIdentity) return null;
  for (const key of ["contract", "result_id", "schema_version"] as const) {
    if (typeof resultIdentity[key] !== "string" || resultIdentity[key] === "") return null;
  }
  for (const key of requiredTextKeys) {
    parsedProvenance[key] = record[key];
  }
  parsedProvenance.contentHash = record.contentHash;
  parsedProvenance.validatorRef = validatorRef;
  return parsedProvenance as unknown as ReportEvidenceProvenance;
}

/** Canonical JSON v1 parity for the server-owned projection digest. */
function canonicalJsonV1(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value.normalize("NFC"));
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("canonical JSON does not allow non-finite numbers");
    if (Object.is(value, -0) || value === 0) return "0";
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new TypeError("canonical JSON number encoding failed");
    return encoded;
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJsonV1).join(",")}]`;
  const record = asEvidenceRecord(value);
  if (!record) throw new TypeError("canonical JSON value is unsupported");
  const entries = Object.keys(record)
    .map((key) => [key.normalize("NFC"), record[key]] as const)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0);
  if (new Set(entries.map(([key]) => key)).size !== entries.length) {
    throw new TypeError("canonical JSON has duplicate keys");
  }
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJsonV1(item)}`).join(",")}}`;
}

const SHA256_ROUND_CONSTANTS = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

function sha256Hex(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const bitLength = bytes.length * 8;
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const lengthOffset = paddedLength - 8;
  const highLength = Math.floor(bitLength / 0x100000000);
  const lowLength = bitLength >>> 0;
  padded[lengthOffset] = (highLength >>> 24) & 0xff;
  padded[lengthOffset + 1] = (highLength >>> 16) & 0xff;
  padded[lengthOffset + 2] = (highLength >>> 8) & 0xff;
  padded[lengthOffset + 3] = highLength & 0xff;
  padded[lengthOffset + 4] = (lowLength >>> 24) & 0xff;
  padded[lengthOffset + 5] = (lowLength >>> 16) & 0xff;
  padded[lengthOffset + 6] = (lowLength >>> 8) & 0xff;
  padded[lengthOffset + 7] = lowLength & 0xff;

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  for (let offset = 0; offset < padded.length; offset += 64) {
    const words = new Uint32Array(64);
    for (let index = 0; index < 16; index += 1) {
      const at = offset + index * 4;
      words[index] = ((padded[at] << 24) | (padded[at + 1] << 16) | (padded[at + 2] << 8) | padded[at + 3]) >>> 0;
    }
    for (let index = 16; index < 64; index += 1) {
      const x = words[index - 15];
      const y = words[index - 2];
      const smallSigma0 = rotateRight(x, 7) ^ rotateRight(x, 18) ^ (x >>> 3);
      const smallSigma1 = rotateRight(y, 17) ^ rotateRight(y, 19) ^ (y >>> 10);
      words[index] = (words[index - 16] + smallSigma0 + words[index - 7] + smallSigma1) >>> 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let index = 0; index < 64; index += 1) {
      const bigSigma1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temporary1 = (h + bigSigma1 + choose + SHA256_ROUND_CONSTANTS[index] + words[index]) >>> 0;
      const bigSigma0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temporary2 = (bigSigma0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temporary1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temporary1 + temporary2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((word) => word.toString(16).padStart(8, "0"))
    .join("");
}

export function reportProjectionDigest(candidate: Record<string, unknown>): string {
  const withoutDigest = Object.fromEntries(
    Object.entries(candidate).filter(([key]) => key !== "projectionDigest"),
  );
  return sha256Hex(canonicalJsonV1(withoutDigest));
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
  if (
    typeof candidate.projectionDigest !== "string"
    || !/^[0-9a-f]{64}$/.test(candidate.projectionDigest)
  ) return null;
  try {
    if (candidate.projectionDigest !== reportProjectionDigest(candidate)) return null;
  } catch {
    return null;
  }
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
  if (provenance.scopeRef !== candidate.scopeRef) return null;
  if (typeof provenance.envelopeRef === "string" && provenance.envelopeRef !== candidate.envelopeRef) return null;
  if (provenance.envelopeDigest !== candidate.envelopeDigest) return null;
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
    projectionDigest: candidate.projectionDigest as string,
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
    projectionDigest: "UNAVAILABLE",
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
      artifactRef,
      artifactType: "UNAVAILABLE",
      artifactId: artifactRef,
      scopeRef: "UNAVAILABLE",
      contentHash: "UNAVAILABLE",
      sourceRef: "UNAVAILABLE",
      validatorRef: "UNAVAILABLE",
      executionRef: "UNAVAILABLE",
      contractDigest: "UNAVAILABLE",
      commitId: "UNAVAILABLE",
      envelopeRef: "UNAVAILABLE",
      envelopeDigest: "UNAVAILABLE",
      lineageRefs: [],
      projectionRef: {},
      resultIdentity: {},
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
