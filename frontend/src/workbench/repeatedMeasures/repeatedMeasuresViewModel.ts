type JsonRecord = Record<string, unknown>;

export type LmmTrajectory = {
  chart_type: "lmm_group_trajectory";
  time: number[];
  groups: Array<{ label: string; observed_mean: number[]; fitted_mean: number[] }>;
};

type PrimaryCoefficient = {
  result_id: "group_time_interaction";
  label: string;
  estimate: number;
  std_error: number;
  p_value: number;
  confidence_interval: [number, number];
  confidence_level: number;
  inference_method: string;
  source_id: string;
};

type DisplayDiagnostic = { code: string };

type TrustedSourceMetadata = {
  artifactId: string;
  artifactPath: string;
  artifactSha256: string;
  sourceContract: string;
  sourceContractVersion: string;
  sourceProducerVersion: string;
  sourcePacketDigest: string;
};

export type RepeatedMeasuresViewModel =
  | {
      kind: "complete";
      primaryCoefficient: PrimaryCoefficient;
      diagnostics: DisplayDiagnostic[];
      trajectory: LmmTrajectory | null;
      sourceMetadata: TrustedSourceMetadata;
    }
  | { kind: "failed"; terminalDiagnostics: string[]; trajectory: null }
  | { kind: "rejected" };

const DIGEST = /^[0-9a-f]{64}$/;
const OUTER_FIELDS = new Set([
  "artifact_id",
  "artifact_path",
  "artifact_sha256",
  "model_id",
  "model_type",
  "source_contract",
  "source_contract_version",
  "source_producer_version",
  "source_packet_digest",
  "execution_binding",
  "payload",
  "legacy_compatibility",
]);
const EXECUTION_BINDING_FIELDS = new Set([
  "schema_version",
  "run_id",
  "executed_input_digest",
]);
const RECOVERABLE_CODES = new Set([
  "LMM_RANDOM_SLOPE_NEAR_ZERO",
  "LMM_RANDOM_EFFECTS_SINGULAR",
]);
const FAILED_CODES = new Set([
  "LMM_CONVERGENCE_FAILED",
  "LMM_UNEXPECTED_FIT_EXCEPTION",
]);
const UNBALANCED_CODE = "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME";
const SNAPSHOT_REJECTED = Symbol("snapshot-rejected");

/**
 * Copies only JSON-shaped own enumerable data properties.  Validation below
 * reads this copy, never server-owned objects, so an accessor cannot run while
 * a result is being inspected.  A Proxy that cannot provide descriptors is
 * rejected by the same fail-closed rule.
 */
function snapshotJson(
  value: unknown,
  ancestors = new WeakSet<object>(),
): unknown | typeof SNAPSHOT_REJECTED {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : SNAPSHOT_REJECTED;
  if (typeof value !== "object") return SNAPSHOT_REJECTED;
  try {
    if (ancestors.has(value)) return SNAPSHOT_REJECTED;
    ancestors.add(value);
    const descriptors = Object.getOwnPropertyDescriptors(value);
    if (Object.getOwnPropertySymbols(value).length !== 0) return SNAPSHOT_REJECTED;
    if (Array.isArray(value)) {
      const length = descriptors.length;
      if (!length || !("value" in length) || typeof length.value !== "number") return SNAPSHOT_REJECTED;
      const copy: unknown[] = [];
      const expectedKeys = new Set(["length"]);
      for (let index = 0; index < length.value; index += 1) expectedKeys.add(String(index));
      if (Object.keys(descriptors).some((key) => !expectedKeys.has(key))) return SNAPSHOT_REJECTED;
      for (let index = 0; index < length.value; index += 1) {
        const descriptor = descriptors[String(index)];
        if (!descriptor || !descriptor.enumerable || !("value" in descriptor)) return SNAPSHOT_REJECTED;
        const item = snapshotJson(descriptor.value, ancestors);
        if (item === SNAPSHOT_REJECTED) return SNAPSHOT_REJECTED;
        copy.push(item);
      }
      ancestors.delete(value);
      return copy;
    }
    if (Object.getPrototypeOf(value) !== Object.prototype) return SNAPSHOT_REJECTED;
    const copy: JsonRecord = {};
    for (const [key, descriptor] of Object.entries(descriptors)) {
      if (!descriptor.enumerable || !("value" in descriptor)) return SNAPSHOT_REJECTED;
      const item = snapshotJson(descriptor.value, ancestors);
      if (item === SNAPSHOT_REJECTED) return SNAPSHOT_REJECTED;
      copy[key] = item;
    }
    ancestors.delete(value);
    return copy;
  } catch {
    return SNAPSHOT_REJECTED;
  }
}

function plainRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype;
}

function hasExactKeys(value: JsonRecord, fields: Set<string>): boolean {
  return Object.getOwnPropertySymbols(value).length === 0
    && Object.keys(value).length === fields.size
    && Object.keys(value).every((key) => fields.has(key));
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function validateExecutionBinding(value: unknown): JsonRecord | null {
  if (!plainRecord(value) || !hasExactKeys(value, EXECUTION_BINDING_FIELDS)) return null;
  if (value.schema_version !== 1 || !nonEmptyString(value.run_id)) return null;
  if (typeof value.executed_input_digest !== "string" || !DIGEST.test(value.executed_input_digest)) return null;
  return value;
}

function validateOuter(value: unknown): JsonRecord | null {
  if (!plainRecord(value) || !hasExactKeys(value, OUTER_FIELDS)) return null;
  if (!nonEmptyString(value.artifact_id) || !nonEmptyString(value.artifact_path)) return null;
  if (typeof value.artifact_sha256 !== "string" || !DIGEST.test(value.artifact_sha256)) return null;
  if (value.model_id !== "linear_mixed_effects_1" || value.model_type !== "linear_mixed_effects") return null;
  if (value.source_contract !== "linear_mixed_effects.result" || value.source_contract_version !== "1.0") return null;
  if (!nonEmptyString(value.source_producer_version)) return null;
  if (typeof value.source_packet_digest !== "string" || !DIGEST.test(value.source_packet_digest)) return null;
  if (validateExecutionBinding(value.execution_binding) === null) return null;
  if (value.legacy_compatibility !== "projected_from_versioned_packet") return null;
  return plainRecord(value.payload) ? value : null;
}

function validatePrimaryCoefficient(value: unknown): PrimaryCoefficient | null {
  const fields = new Set([
    "result_id", "label", "estimate", "std_error", "p_value", "confidence_interval",
    "confidence_level", "inference_method", "source_id",
  ]);
  if (!plainRecord(value) || !hasExactKeys(value, fields)) return null;
  if (value.result_id !== "group_time_interaction" || !nonEmptyString(value.label)) return null;
  if (!finiteNumber(value.estimate) || !finiteNumber(value.std_error) || !finiteNumber(value.p_value)) return null;
  if (!Array.isArray(value.confidence_interval) || value.confidence_interval.length !== 2
    || !finiteNumber(value.confidence_interval[0]) || !finiteNumber(value.confidence_interval[1])) return null;
  if (!finiteNumber(value.confidence_level) || !nonEmptyString(value.inference_method) || !nonEmptyString(value.source_id)) return null;
  return value as PrimaryCoefficient;
}

export function parseCanonicalTrajectory(
  value: unknown,
  expectedLabels?: readonly [string, string],
): LmmTrajectory | null {
  const snapshot = snapshotJson(value);
  if (snapshot === SNAPSHOT_REJECTED) return null;
  value = snapshot;
  const fields = new Set(["chart_type", "time", "groups"]);
  if (!plainRecord(value) || !hasExactKeys(value, fields) || value.chart_type !== "lmm_group_trajectory") return null;
  const time = value.time;
  const rawGroups = value.groups;
  if (!Array.isArray(time) || time.length === 0 || !time.every(finiteNumber)) return null;
  if (time.some((point, index) => index > 0 && time[index - 1] >= point)) return null;
  if (!Array.isArray(rawGroups) || rawGroups.length !== 2) return null;
  const groupFields = new Set(["label", "observed_mean", "fitted_mean"]);
  const groups: LmmTrajectory["groups"] = [];
  for (const group of rawGroups) {
    if (!plainRecord(group) || !hasExactKeys(group, groupFields) || !nonEmptyString(group.label)
      || group.label.length > 128) return null;
    if (!Array.isArray(group.observed_mean) || !Array.isArray(group.fitted_mean)
      || group.observed_mean.length !== time.length || group.fitted_mean.length !== time.length
      || !group.observed_mean.every(finiteNumber) || !group.fitted_mean.every(finiteNumber)) return null;
    groups.push({ label: group.label, observed_mean: group.observed_mean, fitted_mean: group.fitted_mean });
  }
  const labels = groups.map((group) => group.label);
  if (new Set(labels).size !== 2 || labels[0] >= labels[1]) return null;
  if (expectedLabels !== undefined) {
    const canonicalLabels = [...expectedLabels].sort();
    if (labels[0] !== canonicalLabels[0] || labels[1] !== canonicalLabels[1]) return null;
  }
  return { chart_type: "lmm_group_trajectory", time, groups };
}

function validateRecoveryCandidate(value: unknown): boolean {
  const fields = new Set(["action_id", "operation_id", "patch", "required_confirmation"]);
  if (!plainRecord(value) || !hasExactKeys(value, fields)) return false;
  if (value.action_id !== "lmm.simplify_random_effects_v1" || value.operation_id !== "model.rerun"
    || value.required_confirmation !== true || !plainRecord(value.patch)) return false;
  const patchFields = new Set(["model_options"]);
  const options = value.patch.model_options;
  return hasExactKeys(value.patch, patchFields) && plainRecord(options)
    && hasExactKeys(options, new Set(["random_slope"])) && options.random_slope === false;
}

function validateUnbalancedEvidence(
  value: unknown,
  expectedLabels: readonly [string, string],
): boolean {
  const fields = new Set(["reason", "group_support", "first_nonshared_time"]);
  if (!plainRecord(value) || !hasExactKeys(value, fields)
    || value.reason !== "unbalanced_observed_time_support" || !finiteNumber(value.first_nonshared_time)
    || !Array.isArray(value.group_support) || value.group_support.length !== 2) return false;
  const supportFields = new Set(["label", "observed_time_sha256"]);
  const labels: string[] = [];
  for (const support of value.group_support) {
    if (!plainRecord(support) || !hasExactKeys(support, supportFields) || !nonEmptyString(support.label)
      || support.label.length > 128
      || typeof support.observed_time_sha256 !== "string" || !DIGEST.test(support.observed_time_sha256)) return false;
    labels.push(support.label);
  }
  const canonicalLabels = [...expectedLabels].sort();
  return new Set(labels).size === 2 && labels[0] < labels[1]
    && labels[0] === canonicalLabels[0] && labels[1] === canonicalLabels[1]
    && (value.group_support[0] as JsonRecord).observed_time_sha256
      !== (value.group_support[1] as JsonRecord).observed_time_sha256;
}

function validateDiagnostic(value: unknown): JsonRecord | null {
  const fields = new Set(["code", "severity", "status", "evidence", "action_candidate"]);
  return plainRecord(value) && hasExactKeys(value, fields) && nonEmptyString(value.code)
    && plainRecord(value.evidence) ? value : null;
}

function validateRecoverableDiagnostic(diagnostic: JsonRecord): boolean {
  if (!RECOVERABLE_CODES.has(diagnostic.code as string) || diagnostic.severity !== "warning"
    || diagnostic.status !== "complete") return false;
  if (diagnostic.code === "LMM_RANDOM_SLOPE_NEAR_ZERO") return validateRecoveryCandidate(diagnostic.action_candidate);
  return diagnostic.action_candidate === null || validateRecoveryCandidate(diagnostic.action_candidate);
}

function validateCompleteDiagnostics(
  value: unknown,
  warnings: unknown,
  hasTrajectory: boolean,
  expectedLabels: readonly [string, string],
): DisplayDiagnostic[] | null {
  if (!Array.isArray(value) || !Array.isArray(warnings) || !warnings.every((item) => typeof item === "string")) return null;
  const diagnostics = value.map(validateDiagnostic);
  if (diagnostics.some((diagnostic) => diagnostic === null)) return null;
  const valid = diagnostics as JsonRecord[];
  const codes = valid.map((diagnostic) => diagnostic.code as string);
  if (new Set(codes).size !== codes.length) return null;
  const warningCodes = valid.filter((diagnostic) => diagnostic.severity === "warning")
    .map((diagnostic) => diagnostic.code as string);
  if (warnings.length !== warningCodes.length || warnings.some((code, index) => code !== warningCodes[index])) return null;

  if (!hasTrajectory) {
    const unbalanced = valid.filter((diagnostic) => diagnostic.code === UNBALANCED_CODE);
    if (unbalanced.length !== 1 || warnings.filter((code) => code === UNBALANCED_CODE).length !== 1) return null;
    if (!unbalanced[0] || unbalanced[0].severity !== "warning" || unbalanced[0].status !== "complete"
      || unbalanced[0].action_candidate !== null || !validateUnbalancedEvidence(unbalanced[0].evidence, expectedLabels)) return null;
    if (!valid.every((diagnostic) => diagnostic.code === UNBALANCED_CODE || validateRecoverableDiagnostic(diagnostic))) return null;
    return valid.map((diagnostic) => ({ code: diagnostic.code as string }));
  }

  for (const diagnostic of valid) {
    if (!validateRecoverableDiagnostic(diagnostic)) return null;
  }
  return valid.map((diagnostic) => ({ code: diagnostic.code as string }));
}

export function buildRepeatedMeasuresViewModel(value: unknown): RepeatedMeasuresViewModel {
  const snapshot = snapshotJson(value);
  if (snapshot === SNAPSHOT_REJECTED) return { kind: "rejected" };
  value = snapshot;
  const outer = validateOuter(value);
  if (outer === null) return { kind: "rejected" };
  const payload = outer.payload as JsonRecord;
  const outerBinding = validateExecutionBinding(outer.execution_binding);
  const payloadBinding = validateExecutionBinding(payload.execution_binding);
  if (outerBinding === null || payloadBinding === null
    || outerBinding.run_id !== payloadBinding.run_id
    || outerBinding.executed_input_digest !== payloadBinding.executed_input_digest) return { kind: "rejected" };
  if (payload.schema_version !== 1 || payload.contract_version !== "1.0"
    || !nonEmptyString(payload.estimator_version) || payload.model_id !== "linear_mixed_effects_1"
    || payload.model_type !== "linear_mixed_effects" || payload.primary_target_id !== "group_time_interaction"
    || !nonEmptyString(payload.reference_group) || !nonEmptyString(payload.comparison_group)
    || payload.reference_group.length > 128 || payload.comparison_group.length > 128
    || payload.reference_group === payload.comparison_group
    || !plainRecord(payload.coefficients)) return { kind: "rejected" };
  const expectedLabels: [string, string] = [payload.reference_group, payload.comparison_group];
  const sourceMetadata: TrustedSourceMetadata = {
    artifactId: outer.artifact_id as string,
    artifactPath: outer.artifact_path as string,
    artifactSha256: outer.artifact_sha256 as string,
    sourceContract: outer.source_contract as string,
    sourceContractVersion: outer.source_contract_version as string,
    sourceProducerVersion: outer.source_producer_version as string,
    sourcePacketDigest: outer.source_packet_digest as string,
  };

  if (payload.status === "failed") {
    if (payload.converged !== false || payload.figure_context !== null || Object.keys(payload.coefficients).length !== 0
      || !plainRecord(payload.random_effects) || Object.keys(payload.random_effects).length !== 0
      || !Array.isArray(payload.diagnostics) || payload.diagnostics.length === 0
      || !Array.isArray(payload.warnings) || payload.warnings.length !== 0) return { kind: "rejected" };
    const diagnostics = payload.diagnostics.map(validateDiagnostic);
    if (diagnostics.some((diagnostic) => diagnostic === null)) return { kind: "rejected" };
    const terminal = diagnostics as JsonRecord[];
    const codes = terminal.map((diagnostic) => diagnostic.code as string);
    if (new Set(codes).size !== codes.length) return { kind: "rejected" };
    for (const diagnostic of terminal) {
      if (!FAILED_CODES.has(diagnostic.code as string) || diagnostic.severity !== "error"
        || diagnostic.status !== "failed" || diagnostic.action_candidate !== null) return { kind: "rejected" };
      const evidence = diagnostic.evidence as JsonRecord;
      if (diagnostic.code === "LMM_CONVERGENCE_FAILED"
        && (!hasExactKeys(evidence, new Set(["optimizer"])) || evidence.optimizer !== "lbfgs")) return { kind: "rejected" };
      if (diagnostic.code === "LMM_UNEXPECTED_FIT_EXCEPTION" && !hasExactKeys(evidence, new Set())) return { kind: "rejected" };
    }
    return { kind: "failed", terminalDiagnostics: codes, trajectory: null };
  }

  if (payload.status !== "complete" || payload.converged !== true) return { kind: "rejected" };
  const primary = validatePrimaryCoefficient(payload.coefficients.group_time_interaction);
  if (primary === null) return { kind: "rejected" };
  const trajectory = payload.figure_context === null ? null : parseCanonicalTrajectory(payload.figure_context, expectedLabels);
  if (payload.figure_context !== null && trajectory === null) return { kind: "rejected" };
  const diagnostics = validateCompleteDiagnostics(payload.diagnostics, payload.warnings, trajectory !== null, expectedLabels);
  if (diagnostics === null) return { kind: "rejected" };
  return { kind: "complete", primaryCoefficient: primary, diagnostics, trajectory, sourceMetadata };
}
