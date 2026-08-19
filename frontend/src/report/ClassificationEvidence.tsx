import type { ReactNode } from "react";

type EvidenceRecord = Record<string, unknown>;

export type ClassificationEvidenceStatus = "validated" | "degraded" | "unavailable";

export interface ClassificationEvidenceTaskIdentity {
  readonly task_type: string;
  readonly positive_class: unknown;
  readonly class_support: Readonly<Record<string, number>>;
  readonly task_hash: string;
}

export interface ClassificationEvidenceSplitIdentity {
  readonly profile: string;
  readonly split_hash: string;
  readonly [key: string]: unknown;
}

export interface ClassificationEvidenceReleasePlan {
  readonly plan_hash: string;
  readonly task_hash: string;
  readonly split_hash: string;
  readonly model_id: string;
  readonly model_hash: string;
  readonly calibration_hash: string;
  readonly policy_hash: string;
  readonly [key: string]: unknown;
}

export interface ClassificationEvidenceHoldoutIdentity {
  readonly status: string;
  readonly release_plan_hash: string;
  readonly release_count: number;
  readonly release_plan: ClassificationEvidenceReleasePlan;
  readonly [key: string]: unknown;
}

export interface ClassificationEvidencePacket {
  readonly payload_schema: "workbench.prediction.classification-evidence";
  readonly schema_version: 1;
  readonly status: ClassificationEvidenceStatus;
  readonly task: ClassificationEvidenceTaskIdentity;
  readonly split: ClassificationEvidenceSplitIdentity;
  readonly metrics: Readonly<Record<string, unknown>>;
  readonly calibration: Readonly<Record<string, unknown>>;
  readonly baselines: readonly unknown[];
  readonly controls: readonly unknown[];
  readonly comparison: Readonly<Record<string, unknown>>;
  readonly explanations: Readonly<Record<string, unknown>>;
  readonly stability: Readonly<Record<string, unknown>>;
  readonly shift: Readonly<Record<string, unknown>>;
  readonly decision_policy: Readonly<Record<string, unknown>>;
  readonly blocked_reasons: readonly string[];
  readonly evidence_refs: Readonly<{
    readonly task: string;
    readonly split: string;
    readonly model: string;
    readonly holdout: string;
    readonly release_plan: string;
    readonly [key: string]: string;
  }>;
  readonly holdout: ClassificationEvidenceHoldoutIdentity;
  readonly c0_evidence_envelope: Readonly<Record<string, unknown>>;
  readonly c0_consumer_projection: Readonly<Record<string, unknown>>;
  readonly foundation_status: Readonly<{
    readonly execution_status: "completed" | "partial" | "blocked" | "failed";
    readonly availability: "available" | "not_available" | "not_applicable";
    readonly completeness_status: "complete" | "degraded" | "insufficient" | "not_applicable";
    readonly producer_status: ClassificationEvidenceStatus;
  }>;
}

export interface ClassificationArtifactsWrapper {
  readonly payload_schema: "workbench.prediction.classification-artifacts-wrapper";
  readonly schema_version: 1;
  readonly artifact_id: string;
  readonly artifact_path: string;
  readonly artifact_sha256: string;
  readonly index: EvidenceRecord;
  readonly artifact: EvidenceRecord & { readonly evidence: ClassificationEvidencePacket };
  readonly receipt_path: "classification_receipt.json";
  readonly receipt_sha256: string;
  readonly receipt: EvidenceRecord;
  readonly receipt_digest: string;
  readonly content_digests: Readonly<Record<string, string>>;
  readonly server_identity: EvidenceRecord;
}

export interface ClassificationActiveScope {
  readonly projectRoot: string;
  readonly runId: string;
}

const tableStyle = { fontSize: 12, borderCollapse: "collapse" as const };
const cellStyle = { padding: "2px 10px 2px 0", textAlign: "left" as const };
const SAFE_DISPLAY_KEYS = new Set([
  "positive_class", "class_support", "split_profile", "split_hash", "profile",
  "status", "reason", "brier", "ece", "calibration_method", "sample_scope", "n_bins",
  "selected_model", "same_split", "baseline_model", "metric", "direction",
  "method", "feature_count", "folds", "n_folds", "summary", "compared_to",
  "selection_status", "holdout", "threshold", "time_horizon", "cost_policy",
  "split", "holdout_ref", "calibration", "explanations", "stability", "shift",
]);

function asRecord(value: unknown): EvidenceRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as EvidenceRecord
    : null;
}

const CLASSIFICATION_EVIDENCE_SCHEMA = "workbench.prediction.classification-evidence";
const CLASSIFICATION_C0_CONSUMERS = new Set(["agent", "notebook", "report"]);
const CLASSIFICATION_C0_BASE_FACETS = new Set(["classification", "task", "split", "holdout", "release_plan"]);
const CLASSIFICATION_C0_STATUS = {
  validated: { execution_status: "completed", availability: "available", completeness_status: "complete", projection_status: "available", source_eligible: true },
  degraded: { execution_status: "completed", availability: "available", completeness_status: "degraded", projection_status: "available", source_eligible: false },
  unavailable: { execution_status: "blocked", availability: "not_available", completeness_status: "insufficient", projection_status: "blocked", source_eligible: false },
} as const;
const CLASSIFICATION_REQUIRED_FIELDS = [
  "status", "task", "split", "metrics", "calibration", "baselines", "controls", "comparison",
  "explanations", "stability", "shift", "decision_policy", "blocked_reasons", "evidence_refs",
  "holdout", "c0_evidence_envelope", "c0_consumer_projection", "foundation_status",
] as const;

const PERSISTED_CLASSIFICATION_SCHEMA = "workbench.prediction.classification-artifacts";
const CLASSIFICATION_ARTIFACTS_WRAPPER_SCHEMA = "workbench.prediction.classification-artifacts-wrapper";
const CLASSIFICATION_RECEIPT_SCHEMA = "workbench.prediction.classification-receipt";
const CLASSIFICATION_CONTENT_DIGEST_KEYS = [
  "artifact", "evidence", "evidence.metrics", "evaluation", "evaluation.metrics",
  "models", "models.metadata", "models.warnings", "fit", "fold_receipts",
] as const;

function isFiniteNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= 0;
}

function isDigest(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

function isHexDigest(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isServerIdentity(value: unknown): value is EvidenceRecord {
  const identity = asRecord(value);
  const base = identity === null
    ? null
    : {
      schema_version: identity.schema_version,
      project_id: identity.project_id,
      run_id: identity.run_id,
      namespace: identity.namespace,
    };
  return (
    identity !== null
    && Object.keys(identity).sort().join("|") === "digest|namespace|project_id|run_id|schema_version"
    && identity.schema_version === 1
    && typeof identity.project_id === "string"
    && /^project:sha256:[0-9a-f]{64}$/.test(identity.project_id)
    && typeof identity.run_id === "string"
    && /^[^/\\]+$/.test(identity.run_id)
    && identity.namespace === "workbench.prediction.classification-artifacts.v1"
    && isDigest(identity.digest)
    && base !== null
    && identity.digest === `sha256:${canonicalDigest(base)}`
  );
}

function sameJson(left: unknown, right: unknown): boolean {
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

function normalizeCanonicalString(value: string): string {
  const normalized = value.normalize("NFC");
  for (const character of normalized) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint >= 0xd800 && codePoint <= 0xdfff) {
      throw new Error("canonical JSON does not allow surrogate code points");
    }
  }
  return normalized;
}

function compareCodePointStrings(left: string, right: string): number {
  const leftCodePoints = Array.from(left, (character) => character.codePointAt(0) ?? 0);
  const rightCodePoints = Array.from(right, (character) => character.codePointAt(0) ?? 0);
  const length = Math.min(leftCodePoints.length, rightCodePoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftCodePoints[index] !== rightCodePoints[index]) {
      return leftCodePoints[index] - rightCodePoints[index];
    }
  }
  return leftCodePoints.length - rightCodePoints.length;
}

function canonicalJson(value: unknown): string {
  if (value === undefined) throw new Error("canonical JSON does not allow undefined");
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("canonical JSON does not allow NaN or Infinity");
    return Object.is(value, -0) ? "0" : JSON.stringify(value);
  }
  if (typeof value === "string") return JSON.stringify(normalizeCanonicalString(value));
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const record = asRecord(value);
  if (!record) throw new Error("unsupported canonical value");
  const normalizedEntries = Object.entries(record).map(([key, item]) => [normalizeCanonicalString(key), item] as const);
  const uniqueKeys = new Set(normalizedEntries.map(([key]) => key));
  if (uniqueKeys.size !== normalizedEntries.length) {
    throw new Error("Unicode normalization produced duplicate object keys");
  }
  normalizedEntries.sort(([left], [right]) => compareCodePointStrings(left, right));
  return `{${normalizedEntries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
}

function sha256(value: string): string {
  const bytes = new TextEncoder().encode(value);
  const words = new Uint32Array(64);
  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const constants = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
    0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
    0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const bitLength = bytes.length * 8;
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const lengthOffset = paddedLength - 8;
  for (let index = 0; index < 8; index += 1) padded[lengthOffset + index] = (bitLength / 2 ** (56 - index * 8)) & 0xff;
  const rotateRight = (value: number, amount: number) => (value >>> amount) | (value << (32 - amount));
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      const position = offset + index * 4;
      words[index] = ((padded[position] << 24) | (padded[position + 1] << 16) | (padded[position + 2] << 8) | padded[position + 3]) >>> 0;
    }
    for (let index = 16; index < 64; index += 1) {
      const s0 = rotateRight(words[index - 15], 7) ^ rotateRight(words[index - 15], 18) ^ (words[index - 15] >>> 3);
      const s1 = rotateRight(words[index - 2], 17) ^ rotateRight(words[index - 2], 19) ^ (words[index - 2] >>> 10);
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let index = 0; index < 64; index += 1) {
      const s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + choose + constants[index] + words[index]) >>> 0;
      const s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + majority) >>> 0;
      [h, g, f, e, d, c, b, a] = [g, f, e, (d + temp1) >>> 0, c, b, a, (temp1 + temp2) >>> 0];
    }
    state[0] = (state[0] + a) >>> 0;
    state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0;
    state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0;
    state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0;
    state[7] = (state[7] + h) >>> 0;
  }
  return [...state].map((word) => word.toString(16).padStart(8, "0")).join("");
}

export function classificationCanonicalJson(value: unknown): string {
  return canonicalJson(value);
}

export function classificationCanonicalDigest(value: unknown): string {
  return sha256(canonicalJson(value));
}

export function classificationProjectId(projectRoot: string): string {
  return `project:sha256:${sha256(projectRoot)}`;
}

function canonicalDigest(value: unknown): string {
  try {
    return classificationCanonicalDigest(value);
  } catch {
    return "";
  }
}

function matchesActiveClassificationScope(
  serverIdentity: EvidenceRecord,
  activeScope?: ClassificationActiveScope,
): boolean {
  if (activeScope === undefined) return true;
  return (
    typeof activeScope.projectRoot === "string"
    && activeScope.projectRoot.length > 0
    && typeof activeScope.runId === "string"
    && activeScope.runId.length > 0
    && serverIdentity.project_id === classificationProjectId(activeScope.projectRoot)
    && serverIdentity.run_id === activeScope.runId
    && serverIdentity.namespace === "workbench.prediction.classification-artifacts.v1"
  );
}

export function isPersistedClassificationArtifact(
  value: unknown,
  activeScope?: ClassificationActiveScope,
): value is ClassificationArtifactsWrapper {
  const persistedInvalid = (): false => false;
  const wrapper = asRecord(value);
  const artifact = asRecord(wrapper?.artifact);
  const receipt = asRecord(wrapper?.receipt);
  const index = asRecord(wrapper?.index);
  const contentDigests = asRecord(wrapper?.content_digests);
  const serverIdentity = asRecord(wrapper?.server_identity);
  const receiptServerIdentity = asRecord(receipt?.server_identity);
  const indexServerIdentity = asRecord(index?.server_identity);
  if (
    wrapper === null
    || wrapper.payload_schema !== CLASSIFICATION_ARTIFACTS_WRAPPER_SCHEMA
    || wrapper.schema_version !== 1
    || artifact === null
    || artifact.payload_schema !== PERSISTED_CLASSIFICATION_SCHEMA
    || artifact.schema_version !== 1
    || receipt === null
    || index === null
    || contentDigests === null
    || serverIdentity === null
    || !isServerIdentity(serverIdentity)
    || !isServerIdentity(receiptServerIdentity)
    || !isServerIdentity(indexServerIdentity)
    || !sameJson(serverIdentity, receiptServerIdentity)
    || !sameJson(serverIdentity, indexServerIdentity)
    || typeof wrapper.artifact_id !== "string"
    || wrapper.artifact_id !== artifact.artifact_id
    || wrapper.artifact_id !== index.artifact_id
    || wrapper.artifact_path !== index.path
    || wrapper.artifact_path !== receipt.artifact_path
    || wrapper.artifact_path !== "classification_artifacts.json"
    || !isHexDigest(wrapper.artifact_sha256)
    || wrapper.artifact_sha256 !== index.sha256
    || wrapper.artifact_sha256 !== receipt.artifact_sha256
    || wrapper.receipt_path !== "classification_receipt.json"
    || wrapper.receipt_path !== index.receipt_path
    || !isHexDigest(wrapper.receipt_sha256)
    || wrapper.receipt_sha256 !== index.receipt_sha256
    || receipt.payload_schema !== CLASSIFICATION_RECEIPT_SCHEMA
    || receipt.schema_version !== 1
    || typeof receipt.receipt_id !== "string"
    || receipt.receipt_id.length === 0
    || receipt.artifact_id !== wrapper.artifact_id
    || asRecord(receipt.payload_contract)?.payload_schema !== PERSISTED_CLASSIFICATION_SCHEMA
    || asRecord(receipt.payload_contract)?.schema_version !== 1
    || receipt.issuer !== "workbench.server.classification-persistence"
    || !isHexDigest(receipt.receipt_digest)
    || wrapper.receipt_digest !== receipt.receipt_digest
    || !sameJson(contentDigests, receipt.content_digests)
    || Object.keys(receipt).sort().join("|") !== [
      "artifact_id", "artifact_path", "artifact_sha256", "content_digests", "issuer",
      "payload_contract", "payload_schema", "receipt_digest", "receipt_id", "schema_version", "server_identity",
    ].sort().join("|")
    || Object.keys(contentDigests).length !== CLASSIFICATION_CONTENT_DIGEST_KEYS.length
    || CLASSIFICATION_CONTENT_DIGEST_KEYS.some((key) => !isHexDigest(contentDigests[key]))
    || !matchesActiveClassificationScope(serverIdentity, activeScope)
  ) return persistedInvalid();
  const receiptBase = { ...receipt };
  delete receiptBase.receipt_digest;
  if (canonicalDigest(receiptBase) !== receipt.receipt_digest) return persistedInvalid();
  const expectedContentDigests = {
    artifact: wrapper.artifact_sha256,
    evidence: canonicalDigest(artifact.evidence),
    "evidence.metrics": canonicalDigest(asRecord(artifact.evidence)?.metrics),
    evaluation: canonicalDigest(artifact.evaluation),
    "evaluation.metrics": canonicalDigest(asRecord(artifact.evaluation)?.metrics),
    models: canonicalDigest(artifact.models),
    "models.metadata": canonicalDigest(Object.fromEntries(Object.entries(asRecord(artifact.models) ?? {}).map(([modelId, model]) => [modelId, asRecord(model)?.metadata ?? null]))),
    "models.warnings": canonicalDigest(Object.fromEntries(Object.entries(asRecord(artifact.models) ?? {}).map(([modelId, model]) => [modelId, asRecord(asRecord(model)?.metadata)?.warnings ?? null]))),
    fit: canonicalDigest(artifact.fit),
    fold_receipts: canonicalDigest(Object.fromEntries(Object.entries(asRecord(artifact.fit)?.models ?? {}).map(([modelId, model]) => [modelId, asRecord(model)?.fold_receipts]))),
  };
  if (!sameJson(contentDigests, expectedContentDigests)) return persistedInvalid();
  const evidence = asRecord(artifact.evidence);
  const identity = asRecord(artifact.identity);
  const fit = asRecord(artifact.fit);
  const evaluation = asRecord(artifact.evaluation);
  const models = asRecord(artifact.models);
  const artifactServerIdentity = asRecord(artifact.server_identity);
  const identityServerIdentity = asRecord(identity?.server_identity);
  if (
    evidence === null
    || identity === null
    || fit === null
    || evaluation === null
    || models === null
    || !isRawTypedClassificationEvidencePacket(evidence)
    || typeof artifact.artifact_id !== "string"
    || identity.artifact_id !== artifact.artifact_id
    || identity.schema_version !== 1
    || artifactServerIdentity === null
    || identityServerIdentity === null
    || !isServerIdentity(artifactServerIdentity)
    || !isServerIdentity(identityServerIdentity)
    || !sameJson(artifactServerIdentity, serverIdentity)
    || asRecord(identity.parts) === null
    || !Object.values(asRecord(identity.parts) as EvidenceRecord).every((item) => typeof item === "string" && item.length > 0)
    || typeof identity.task_hash !== "string"
    || typeof identity.split_hash !== "string"
    || typeof identity.model_id !== "string"
    || typeof identity.model_hash !== "string"
    || typeof identity.holdout_hash !== "string"
    || typeof identity.release_plan_hash !== "string"
    || !isDigest(identity.fit_digest)
    || !isDigest(identity.evaluation_digest)
    || asRecord(identity.parts)?.server_identity_digest !== serverIdentity.digest
    || fit.schema_version !== 1
    || evaluation.schema_version !== 1
    || fit.digest !== identity.fit_digest
    || evaluation.digest !== identity.evaluation_digest
  ) return persistedInvalid();

  const task = asRecord(evidence.task);
  const split = asRecord(evidence.split);
  const holdout = asRecord(evidence.holdout);
  const releasePlan = asRecord(holdout?.release_plan);
  const comparison = asRecord(evidence.comparison);
  const expectedIdentity = {
    task_hash: task?.task_hash,
    split_hash: split?.split_hash,
    model_id: comparison?.selected_model,
    model_hash: releasePlan?.model_hash,
    holdout_hash: releasePlan?.plan_hash,
    release_plan_hash: releasePlan?.plan_hash,
  };
  if (
    Object.entries(expectedIdentity).some(([key, expected]) => identity[key] !== expected)
    || !sameJson(fit.identity, { ...expectedIdentity, server_identity: serverIdentity })
    || !sameJson(evaluation.identity, { ...expectedIdentity, server_identity: serverIdentity })
  ) return persistedInvalid();

  const fitModels = asRecord(fit.models);
  const evaluationComparison = evaluation.comparison;
  const selectedModel = comparison?.selected_model;
  const selected = typeof selectedModel === "string" ? asRecord(models[selectedModel]) : null;
  const selectedFit = typeof selectedModel === "string" ? asRecord(fitModels?.[selectedModel]) : null;
  if (
    fitModels === null
    || selected === null
    || selectedFit === null
    || !sameJson(evaluationComparison, evidence.comparison)
    || !sameJson(evaluation.metrics, { oof: selected.oof_metrics, holdout: selected.holdout })
    || new Set(Object.keys(fitModels)).size !== Object.keys(models).length
    || Object.keys(fitModels).some((modelId) => !Object.prototype.hasOwnProperty.call(models, modelId))
  ) return persistedInvalid();

  const overallSupport = asRecord(task?.class_support);
  if (overallSupport === null || Object.keys(overallSupport).length < 2) return persistedInvalid();
  const labels = Object.keys(overallSupport);
  for (const modelId of Object.keys(models)) {
    const model = asRecord(models[modelId]);
    const fitModel = asRecord(fitModels[modelId]);
    const preprocessing = asRecord(model?.preprocessing);
    const folds = preprocessing?.folds;
    const foldReceipts = fitModel?.fold_receipts;
    if (!Array.isArray(folds) || folds.length === 0 || !Array.isArray(foldReceipts) || !sameJson(folds, foldReceipts)) return persistedInvalid();
    const seenFolds = new Set<number>();
    for (const rawFold of foldReceipts) {
      const fold = asRecord(rawFold);
      const receipt = asRecord(fold?.receipt);
      const support = asRecord(receipt?.class_support);
      const trainingRefs = fold?.training_row_refs;
      const validationRefs = fold?.validation_row_refs;
      if (
        fold === null
        || receipt === null
        || support === null
        || !isFiniteNonNegativeInteger(fold.fold)
        || seenFolds.has(fold.fold)
        || !Array.isArray(trainingRefs)
        || !Array.isArray(validationRefs)
        || trainingRefs.length === 0
        || validationRefs.length === 0
        || receipt.schema_version !== 1
        || receipt.split_hash !== split?.split_hash
        || !sameJson(receipt.fit_row_refs, trainingRefs)
        || !sameJson(support.class_labels, labels)
      ) return persistedInvalid();
      seenFolds.add(fold.fold);
      for (const [scope, refs] of [["training", trainingRefs], ["validation", validationRefs]] as const) {
        const counts = asRecord(support[scope]);
        if (counts === null || Object.keys(counts).sort().join("|") !== labels.slice().sort().join("|") || !Object.values(counts).every(isFiniteNonNegativeInteger)) return persistedInvalid();
        if (Object.entries(counts).some(([label, count]) => typeof count !== "number" || count > Number(overallSupport[label]))) return persistedInvalid();
        if (Object.values(counts).reduce<number>((sum, count) => sum + (count as number), 0) !== refs.length || new Set(refs).size !== refs.length) return persistedInvalid();
      }
    }
  }
  return true;
}

function isStringRecord(value: unknown): value is EvidenceRecord {
  const record = asRecord(value);
  return record !== null && Object.values(record).every((item) => typeof item === "string");
}

/** Validate the complete server-owned packet before any report rendering. */
function isRawTypedClassificationEvidencePacket(value: unknown): value is ClassificationEvidencePacket {
  const packet = asRecord(value);
  if (
    packet === null
    || packet.payload_schema !== CLASSIFICATION_EVIDENCE_SCHEMA
    || packet.schema_version !== 1
    || (packet.status !== "validated" && packet.status !== "degraded" && packet.status !== "unavailable")
    || CLASSIFICATION_REQUIRED_FIELDS.some((field) => !(field in packet))
  ) return false;

  const status = packet.status;
  const expected = CLASSIFICATION_C0_STATUS[status];
  const task = asRecord(packet.task);
  const split = asRecord(packet.split);
  const comparison = asRecord(packet.comparison);
  const holdout = asRecord(packet.holdout);
  const releasePlan = asRecord(holdout?.release_plan);
  const evidenceRefs = asRecord(packet.evidence_refs);
  const foundation = asRecord(packet.foundation_status);
  if (
    task === null
    || typeof task.task_type !== "string"
    || typeof task.task_hash !== "string"
    || asRecord(task.class_support) === null
    || !Object.values(asRecord(task.class_support) as EvidenceRecord).every((item) => typeof item === "number" && Number.isFinite(item))
    || split === null
    || typeof split.profile !== "string"
    || typeof split.split_hash !== "string"
    || asRecord(packet.metrics) === null
    || asRecord(packet.calibration) === null
    || !Array.isArray(packet.baselines)
    || !Array.isArray(packet.controls)
    || comparison === null
    || typeof comparison.selected_model !== "string"
    || asRecord(packet.explanations) === null
    || asRecord(packet.stability) === null
    || asRecord(packet.shift) === null
    || asRecord(packet.decision_policy) === null
    || !Array.isArray(packet.blocked_reasons)
    || packet.blocked_reasons.some((item) => typeof item !== "string")
    || holdout === null
    || typeof holdout.status !== "string"
    || typeof holdout.release_plan_hash !== "string"
    || !isFiniteNonNegativeInteger(holdout.release_count)
    || releasePlan === null
    || typeof releasePlan.plan_hash !== "string"
    || typeof releasePlan.task_hash !== "string"
    || typeof releasePlan.split_hash !== "string"
    || typeof releasePlan.model_id !== "string"
    || typeof releasePlan.model_hash !== "string"
    || typeof releasePlan.calibration_hash !== "string"
    || typeof releasePlan.policy_hash !== "string"
    || releasePlan.plan_hash !== holdout.release_plan_hash
    || releasePlan.task_hash !== task.task_hash
    || releasePlan.split_hash !== split.split_hash
    || releasePlan.model_id !== comparison.selected_model
    || holdout.model_id !== comparison.selected_model
    || evidenceRefs === null
    || Object.keys(evidenceRefs).length !== 5
    || !isStringRecord(evidenceRefs)
  ) return false;

  const expectedRefs = {
    task: `classification-task:${task.task_hash}`,
    split: `classification-split:${split.split_hash}`,
    model: `classification-model:${comparison.selected_model}:${releasePlan.model_hash}`,
    holdout: `classification-holdout:${releasePlan.plan_hash}`,
    release_plan: `classification-release-plan:${releasePlan.plan_hash}`,
  };
  if (Object.entries(expectedRefs).some(([key, expectedRef]) => evidenceRefs[key] !== expectedRef)) return false;
  const envelope = asRecord(packet.c0_evidence_envelope);
  const envelopeIdentity = asRecord(envelope?.result_identity);
  const inputProvenance = asRecord(envelope?.input_provenance);
  const familyEvidence = asRecord(asRecord(envelope?.family_evidence)?.classification);
  const familyMethod = asRecord(familyEvidence?.method);
  const familyIdentity = asRecord(familyEvidence?.identity);
  const projection = asRecord(packet.c0_consumer_projection);
  const projectionPayload = asRecord(projection?.payload);
  const resultRef = `classification-evidence:${task.task_hash}:${split.split_hash}:${releasePlan.plan_hash}`;
  if (
    envelope === null
    || envelopeIdentity === null
    || inputProvenance === null
    || envelope.execution_status !== expected.execution_status
    || envelope.availability !== expected.availability
    || envelope.completeness_status !== expected.completeness_status
    || envelopeIdentity.result_ref !== resultRef
    || envelopeIdentity.task_hash !== task.task_hash
    || envelopeIdentity.split_hash !== split.split_hash
    || envelopeIdentity.holdout_hash !== releasePlan.plan_hash
    || envelopeIdentity.release_plan_hash !== releasePlan.plan_hash
    || inputProvenance.task_hash !== task.task_hash
    || inputProvenance.split_hash !== split.split_hash
    || inputProvenance.holdout_hash !== releasePlan.plan_hash
    || inputProvenance.release_plan_hash !== releasePlan.plan_hash
    || familyEvidence === null
    || Object.keys(familyEvidence).length !== 5
    || familyEvidence.status !== status
    || familyEvidence.issuer !== "workbench.server"
    || familyEvidence.producer !== "workbench.prediction.run_classification_model_v189"
    || familyMethod === null
    || Object.keys(familyMethod).length !== 2
    || familyMethod.id !== "classification-production-v1"
    || familyMethod.version !== "1.0"
    || familyIdentity === null
    || Object.keys(familyIdentity).length !== 7
    || familyIdentity.result_ref !== resultRef
    || familyIdentity.task_hash !== task.task_hash
    || familyIdentity.split_hash !== split.split_hash
    || familyIdentity.model_id !== comparison.selected_model
    || familyIdentity.model_hash !== releasePlan.model_hash
    || familyIdentity.holdout_hash !== releasePlan.plan_hash
    || familyIdentity.release_plan_hash !== releasePlan.plan_hash
    || projection === null
    || projection.contract !== "consumer-projection"
    || projection.contract_version !== "1.0"
    || projection.producer_version !== "1.8.9"
    || projectionPayload === null
    || projectionPayload.projection_id !== resultRef
    || typeof projectionPayload.projection_ref !== "string"
    || projectionPayload.projection_ref.length === 0
    || projectionPayload.projection_status !== expected.projection_status
    || !Array.isArray(projectionPayload.slots)
    || projectionPayload.slots.length !== 3
  ) return false;

  const slots = projectionPayload.slots.map(asRecord);
  if (slots.some((slot) => slot === null)) return false;
  const consumers = new Set(slots.map((slot) => slot?.consumer));
  const expectedFacets = new Set(CLASSIFICATION_C0_BASE_FACETS);
  if (!expected.source_eligible) expectedFacets.add("degraded");
  if (
    consumers.size !== CLASSIFICATION_C0_CONSUMERS.size
    || [...consumers].some((consumer) => !CLASSIFICATION_C0_CONSUMERS.has(String(consumer)))
    || slots.some((slot) => {
      const facets = slot?.artifact_facets;
      return (
        typeof slot?.consumer !== "string"
        || !Array.isArray(facets)
        || facets.length !== expectedFacets.size
        || new Set(facets).size !== expectedFacets.size
        || facets.some((facet) => typeof facet !== "string" || !expectedFacets.has(facet))
        || slot?.payload_schema_ref !== CLASSIFICATION_EVIDENCE_SCHEMA
        || slot?.source_eligible !== expected.source_eligible
      );
    })
  ) return false;

  const notApplicable = asRecord(projectionPayload.not_applicable_projection);
  if (
    notApplicable === null
    || notApplicable.status !== "not_applicable"
    || typeof notApplicable.reason !== "string"
    || notApplicable.reason.length === 0
    || foundation === null
    || Object.keys(foundation).length !== 4
    || foundation.execution_status !== expected.execution_status
    || foundation.availability !== expected.availability
    || foundation.completeness_status !== expected.completeness_status
    || foundation.producer_status !== status
  ) return false;
  return true;
}

/** Only the shared server-owned artifact wrapper is a renderable input. */
export function isTypedClassificationEvidencePacket(value: unknown): value is ClassificationArtifactsWrapper {
  return isPersistedClassificationArtifact(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  // Typed evidence is rendered through allowlisted scalar fields. Never dump
  // an unvalidated nested object/array into the report surface.
  return "structured value unavailable";
}

function displayLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} style={{ marginTop: 10 }}>
      <h3 style={{ fontSize: 12, margin: "0 0 5px" }}>{title}</h3>
      {children}
    </section>
  );
}

function Unavailable({ label }: { label: string }) {
  return (
    <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
      {label} unavailable; no serialized value was supplied by the typed packet.
    </p>
  );
}

function KeyValueList({ value }: { value: unknown }) {
  const record = asRecord(value);
  const entries = record
    ? Object.entries(record).filter(([key]) => SAFE_DISPLAY_KEYS.has(key))
    : [];
  if (entries.length === 0) return <Unavailable label="Details" />;
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 }}>
      {entries.map(([key, item]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd style={{ margin: 0 }}>{displayValue(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

function MetricTable({ metrics }: { metrics: unknown }) {
  const record = asRecord(metrics);
  const entries = record ? Object.entries(record).map(([name, item]) => [name, asRecord(item)] as const) : [];
  const rows = entries.filter((entry): entry is readonly [string, EvidenceRecord] => entry[1] !== null);
  if (rows.length === 0) return <Unavailable label="Metrics" />;
  return (
    <table style={tableStyle}>
      <thead>
        <tr><th style={cellStyle}>Metric</th><th style={cellStyle}>Estimate</th><th style={cellStyle}>Status</th><th style={cellStyle}>Scope</th></tr>
      </thead>
      <tbody>
        {rows.map(([name, item]) => (
          <tr key={name}>
            <td style={cellStyle}>{displayLabel(name)}</td>
            <td style={cellStyle}>{displayValue(item.point_estimate)}</td>
            <td style={cellStyle}>{displayValue(item.status)}</td>
            <td style={cellStyle}>{displayValue(item.sample_scope)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RecordArray({ value, label }: { value: unknown; label: string }) {
  const items = asArray(value);
  if (items.length === 0) return <Unavailable label={label} />;
  return (
    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
      {items.map((item, index) => <li key={index}>{displayValue(item)}</li>)}
    </ul>
  );
}

function classificationTitle(task: unknown): string {
  const taskRecord = asRecord(task);
  const taskType = typeof taskRecord?.task_type === "string" ? taskRecord.task_type : "classification";
  return `${taskType.charAt(0).toUpperCase()}${taskType.slice(1)} classification`;
}

export function ClassificationEvidence({ evidence }: { evidence: ClassificationArtifactsWrapper }) {
  if (!isPersistedClassificationArtifact(evidence)) {
    return (
      <div data-testid="classification-evidence" style={{ fontSize: 13 }}>
        <strong>UNAVAILABLE</strong>
        <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "4px 0 0" }}>
          Classification evidence is unavailable because its typed C0 envelope or projection is invalid.
        </p>
      </div>
    );
  }
  const packet = evidence.artifact.evidence;
  const task = asRecord(packet.task);
  const split = asRecord(packet.split);
  const policy = asRecord(packet.decision_policy);
  const blockedReasons = asArray(packet.blocked_reasons).filter((item): item is string => typeof item === "string");
  const evidenceRefs = asRecord(packet.evidence_refs);

  return (
    <div data-testid="classification-evidence" style={{ fontSize: 13 }}>
      <h2 style={{ fontSize: 14, margin: 0 }}>{classificationTitle(task)}</h2>
      {blockedReasons.length > 0 && (
        <Section title="Blocked">
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
            {blockedReasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </Section>
      )}
      <Section title="Task and split">
        <KeyValueList value={{
          positive_class: task?.positive_class,
          class_support: task?.class_support,
          split_profile: split?.profile,
          split_hash: split?.split_hash,
        }} />
      </Section>
      <Section title="Class support">
        <KeyValueList value={task?.class_support} />
      </Section>
      <Section title="Metrics">
        <MetricTable metrics={packet.metrics} />
      </Section>
      <Section title="Calibration">
        <KeyValueList value={packet.calibration} />
      </Section>
      <Section title="Baselines and controls">
        <RecordArray value={packet.baselines} label="Baselines" />
        <RecordArray value={packet.controls} label="Controls" />
      </Section>
      <Section title="Comparison">
        <KeyValueList value={packet.comparison} />
      </Section>
      <Section title="Explanations and stability">
        <KeyValueList value={packet.explanations} />
        <KeyValueList value={packet.stability} />
      </Section>
      <Section title="Shift">
        <KeyValueList value={packet.shift} />
      </Section>
      <Section title="Decision policy and holdout boundary">
        <KeyValueList value={policy} />
        <KeyValueList value={evidenceRefs} />
      </Section>
    </div>
  );
}
