type JsonRecord = Record<string, unknown>;

const LOCKED_CONTRACT_VERSION = "1.0";
const LOCKED_PRODUCER_VERSION = "linear_mixed_effects@1.0";
const LOCKED_RESULT_ID = "group_time_interaction";
const LOCKED_INFERENCE_METHOD = "asymptotic_wald_z_v1";
const RESTRICTED_COMPARE_REASONS = new Set([
  "REML_FIXED_EFFECTS_DIFFER",
  "LMM_FIT_METHOD_DIFFER",
]);
const SUCCESS_RESULT_DIAGNOSTIC_CODES = new Set([
  "LMM_RANDOM_SLOPE_NEAR_ZERO",
  "LMM_RANDOM_EFFECTS_SINGULAR",
]);
const SHA256_HEX = /^[a-f0-9]{64}$/;

export type RepeatedMeasuresDiagnosticView = {
  code: string;
  severity: string;
  status: string;
  message: string;
  recovery: null;
};

export type RepeatedMeasuresRecoveryProposal = {
  action_id: "lmm.simplify_random_effects_v1";
  operation_id: "model.rerun";
  patch: { model_options: { random_slope: false } };
  required_confirmation: true;
};

export type TrajectoryGroup = {
  label: string;
  observed_mean: number[];
  fitted_mean: number[];
};

export type TrajectoryFigureContext = {
  chart_type: "lmm_group_trajectory";
  time: number[];
  groups: TrajectoryGroup[];
};

export type ComparisonFactLayers = {
  data: JsonRecord;
  parameters: JsonRecord;
  results: JsonRecord;
  conclusion: JsonRecord;
};

export type RestrictedRepeatedMeasuresComparison = {
  status: "restricted";
  reason_code: string;
  message: string;
  source_run_id: string;
  child_run_id: string;
  winner: null;
};

export type CompleteRepeatedMeasuresComparison = {
  status: "complete";
  comparison_scope: string | null;
  result_id: string;
  source_run_id: string;
  child_run_id: string;
  facts: ComparisonFactLayers | null;
  winner: null;
};

export type RepeatedMeasuresComparison =
  | RestrictedRepeatedMeasuresComparison
  | CompleteRepeatedMeasuresComparison;

export type RepeatedMeasuresResult = {
  result_id: typeof LOCKED_RESULT_ID;
  estimate: number;
  fit_method: "reml" | "ml";
  trajectory: TrajectoryFigureContext | null;
  diagnostics: RepeatedMeasuresDiagnosticView[];
};

export type RepeatedMeasuresViewModel = {
  phase: "diagnostic" | "confirmation" | "compare" | "success";
  diagnostics: RepeatedMeasuresDiagnosticView[];
  proposal: RepeatedMeasuresRecoveryProposal | null;
  comparison: RepeatedMeasuresComparison | null;
  result: RepeatedMeasuresResult | null;
  canExecute: false;
};

type LockedEnvelope = {
  contract: string;
  payload: JsonRecord;
};

function asRecord(value: unknown): JsonRecord | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  try {
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null ? value as JsonRecord : null;
  } catch {
    return null;
  }
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function ownStringKeys(value: JsonRecord): string[] | null {
  try {
    const keys = Reflect.ownKeys(value);
    return keys.every((key) => typeof key === "string") ? keys as string[] : null;
  } catch {
    return null;
  }
}

function hasOwnKey(value: JsonRecord, key: string): boolean {
  try {
    return Object.prototype.hasOwnProperty.call(value, key);
  } catch {
    return false;
  }
}

function isDenseJsonArray(value: unknown): value is unknown[] {
  if (!Array.isArray(value)) return false;
  try {
    if (Object.getPrototypeOf(value) !== Array.prototype) return false;
    const keys = Reflect.ownKeys(value);
    if (!keys.every((key) => typeof key === "string")) return false;
    if (keys.length !== value.length + 1 || !keys.includes("length")) return false;
    for (let index = 0; index < value.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(value, String(index))) return false;
    }
    return true;
  } catch {
    return false;
  }
}

function hasRequiredOwnKeys(value: JsonRecord, required: readonly string[]): boolean {
  return ownStringKeys(value) !== null && required.every((key) => hasOwnKey(value, key));
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const keys = ownStringKeys(value);
  return keys !== null
    && keys.length === expected.length
    && expected.every((key) => hasOwnKey(value, key))
    && keys.every((key) => expected.includes(key));
}

function hasAllowedKeys(
  value: JsonRecord,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  const keys = ownStringKeys(value);
  return keys !== null
    && required.every((key) => hasOwnKey(value, key))
    && keys.every((key) => allowed.has(key));
}

function blocked(
  code: string,
  message: string,
): RepeatedMeasuresViewModel {
  return {
    phase: "diagnostic",
    diagnostics: [{
      code,
      severity: "error",
      status: "blocked",
      message,
      recovery: null,
    }],
    proposal: null,
    comparison: null,
    result: null,
    canExecute: false,
  };
}

function emptyView(): RepeatedMeasuresViewModel {
  return {
    phase: "diagnostic",
    diagnostics: [],
    proposal: null,
    comparison: null,
    result: null,
    canExecute: false,
  };
}

function parseLockedEnvelope(packet: unknown): LockedEnvelope | null {
  const envelope = asRecord(packet);
  if (
    envelope === null
    || !hasExactKeys(envelope, ["contract", "contract_version", "producer_version", "payload"])
    || !isNonEmptyString(envelope.contract)
    || envelope.contract_version !== LOCKED_CONTRACT_VERSION
    || envelope.producer_version !== LOCKED_PRODUCER_VERSION
  ) return null;

  const payload = asRecord(envelope.payload);
  return payload === null ? null : { contract: envelope.contract, payload };
}

function lockedRecoveryProposal(value: unknown): RepeatedMeasuresRecoveryProposal | null {
  const candidate = asRecord(value);
  const patch = asRecord(candidate?.patch);
  const options = asRecord(patch?.model_options);
  if (
    candidate === null
    || patch === null
    || options === null
    || !hasExactKeys(candidate, ["action_id", "operation_id", "patch", "required_confirmation"])
    || !hasExactKeys(patch, ["model_options"])
    || !hasExactKeys(options, ["random_slope"])
    || candidate.action_id !== "lmm.simplify_random_effects_v1"
    || candidate.operation_id !== "model.rerun"
    || candidate.required_confirmation !== true
    || options.random_slope !== false
  ) return null;

  return {
    action_id: "lmm.simplify_random_effects_v1",
    operation_id: "model.rerun",
    patch: { model_options: { random_slope: false } },
    required_confirmation: true,
  };
}

function parseDiagnosticView(value: unknown): RepeatedMeasuresDiagnosticView | null {
  const diagnostic = asRecord(value);
  if (
    diagnostic === null
    || !hasExactKeys(diagnostic, ["code", "severity", "status", "evidence", "action_candidate"])
    || !isNonEmptyString(diagnostic.code)
    || (diagnostic.severity !== "info" && diagnostic.severity !== "warning" && diagnostic.severity !== "error")
    || (diagnostic.status !== "complete" && diagnostic.status !== "blocked" && diagnostic.status !== "failed")
    || asRecord(diagnostic.evidence) === null
    || (diagnostic.action_candidate !== null && asRecord(diagnostic.action_candidate) === null)
  ) return null;

  return {
    code: diagnostic.code,
    severity: diagnostic.severity as string,
    status: diagnostic.status as string,
    message: "未识别的诊断；请检查完整运行记录。",
    recovery: null,
  };
}

function parseSuccessfulResultDiagnostics(value: unknown): RepeatedMeasuresDiagnosticView[] | null {
  if (!isDenseJsonArray(value)) return null;
  const diagnostics: RepeatedMeasuresDiagnosticView[] = [];
  for (const diagnostic of value) {
    const source = asRecord(diagnostic);
    const parsed = parseDiagnosticView(diagnostic);
    if (
      source === null
      || parsed === null
      || parsed.status !== "complete"
      || parsed.severity !== "warning"
      || !SUCCESS_RESULT_DIAGNOSTIC_CODES.has(parsed.code)
      || (source.action_candidate !== null && lockedRecoveryProposal(source.action_candidate) === null)
    ) {
      return null;
    }
    diagnostics.push(parsed);
  }
  return diagnostics;
}

function parseDiagnosticPayload(payload: JsonRecord): RepeatedMeasuresDiagnosticView[] | null {
  if (
    !hasAllowedKeys(payload, ["status", "diagnostics"], ["fixture_id"])
    || (payload.status !== "complete" && payload.status !== "blocked" && payload.status !== "failed")
    || !isDenseJsonArray(payload.diagnostics)
    || payload.diagnostics.length === 0
  ) return null;

  const diagnostics: RepeatedMeasuresDiagnosticView[] = [];
  for (const value of payload.diagnostics) {
    const diagnostic = parseDiagnosticView(value);
    if (diagnostic === null) return null;
    diagnostics.push(diagnostic);
  }
  return diagnostics;
}

function parseRecoveryPayload(payload: JsonRecord): RepeatedMeasuresRecoveryProposal | null {
  if (
    !hasAllowedKeys(payload, ["proposal_status", "action_candidate"], ["fixture_id"])
    || payload.proposal_status !== "pending_confirmation"
  ) return null;
  return lockedRecoveryProposal(payload.action_candidate);
}

function parseRestrictedComparison(payload: JsonRecord): RestrictedRepeatedMeasuresComparison | null {
  if (
    !hasAllowedKeys(
      payload,
      ["compare_status", "reason_code", "user_safe_message", "source_run_id", "child_run_id"],
      ["fixture_id"],
    )
    || payload.compare_status !== "restricted"
    || !isNonEmptyString(payload.reason_code)
    || !RESTRICTED_COMPARE_REASONS.has(payload.reason_code)
    || !isNonEmptyString(payload.user_safe_message)
    || !isNonEmptyString(payload.source_run_id)
    || !isNonEmptyString(payload.child_run_id)
  ) return null;

  return {
    status: "restricted",
    reason_code: payload.reason_code,
    message: payload.user_safe_message,
    source_run_id: payload.source_run_id,
    child_run_id: payload.child_run_id,
    winner: null,
  };
}

function parseFullComparisonTarget(value: unknown): string | null {
  const target = asRecord(value);
  if (
    target === null
    || !hasExactKeys(target, ["result_id", "role", "label", "resolution_source", "target_hash"])
    || target.result_id !== LOCKED_RESULT_ID
    || target.role !== "primary"
    || (target.label !== null && !isNonEmptyString(target.label))
    || !isNonEmptyString(target.resolution_source)
    || !isNonEmptyString(target.target_hash)
    || !SHA256_HEX.test(target.target_hash)
  ) return null;
  return LOCKED_RESULT_ID;
}

function hasCompletePrimaryComparisonEvidence(
  results: JsonRecord,
  conclusion: JsonRecord,
): boolean {
  if (!hasOwnKey(results, LOCKED_RESULT_ID)) return false;
  const primaryResult = asRecord(results[LOCKED_RESULT_ID]);
  return primaryResult !== null
    && hasExactKeys(primaryResult, ["status", "changed", "fields"])
    && primaryResult.status === "complete"
    && typeof primaryResult.changed === "boolean"
    && asRecord(primaryResult.fields) !== null
    && hasExactKeys(conclusion, ["target_result_id", "status", "classification", "reason_code", "evidence"])
    && conclusion.target_result_id === LOCKED_RESULT_ID
    && conclusion.status === "complete"
    && isNonEmptyString(conclusion.classification)
    && (conclusion.reason_code === null || isNonEmptyString(conclusion.reason_code))
    && asRecord(conclusion.evidence) !== null;
}

function parseCompleteComparison(payload: JsonRecord): CompleteRepeatedMeasuresComparison | null {
  const canonicalRequired = [
    "compare_status",
    "comparison_scope",
    "result_id",
    "source_run_id",
    "child_run_id",
  ];
  if (
    hasAllowedKeys(payload, canonicalRequired, ["fixture_id"])
    && payload.compare_status === "complete"
    && isNonEmptyString(payload.comparison_scope)
    && payload.result_id === LOCKED_RESULT_ID
    && isNonEmptyString(payload.source_run_id)
    && isNonEmptyString(payload.child_run_id)
  ) {
    return {
      status: "complete",
      comparison_scope: payload.comparison_scope,
      result_id: payload.result_id,
      source_run_id: payload.source_run_id,
      child_run_id: payload.child_run_id,
      facts: null,
      winner: null,
    };
  }

  const fullRequired = [
    "compare_status",
    "source_run_id",
    "child_run_id",
    "target",
    "data_diff",
    "parameter_diff",
    "result_diff",
    "conclusion_diff",
    "validation_status",
    "integrity_findings",
    "logical_key",
    "strategy_version",
    "schema_version",
  ];
  if (!hasAllowedKeys(payload, fullRequired, ["reason_code", "user_safe_message"])) return null;
  const targetResultId = parseFullComparisonTarget(payload.target);
  const data = asRecord(payload.data_diff);
  const parameters = asRecord(payload.parameter_diff);
  const results = asRecord(payload.result_diff);
  const conclusion = asRecord(payload.conclusion_diff);
  if (
    payload.compare_status !== "complete"
    || targetResultId === null
    || data === null
    || parameters === null
    || results === null
    || conclusion === null
    || ownStringKeys(data) === null
    || ownStringKeys(parameters) === null
    || ownStringKeys(results) === null
    || ownStringKeys(conclusion) === null
    || !isNonEmptyString(payload.source_run_id)
    || !isNonEmptyString(payload.child_run_id)
    || !isNonEmptyString(payload.logical_key)
    || payload.validation_status !== "pass"
    || !isNonEmptyString(payload.strategy_version)
    || !isNonEmptyString(payload.schema_version)
    || !isDenseJsonArray(payload.integrity_findings)
    || payload.integrity_findings.length !== 0
    || !hasCompletePrimaryComparisonEvidence(results, conclusion)
  ) return null;

  return {
    status: "complete",
    comparison_scope: null,
    result_id: targetResultId,
    source_run_id: payload.source_run_id,
    child_run_id: payload.child_run_id,
    facts: { data, parameters, results, conclusion },
    winner: null,
  };
}

function finiteNumberArray(value: unknown): number[] | null {
  if (!isDenseJsonArray(value)) return null;
  const values: number[] = [];
  for (const item of value) {
    if (typeof item !== "number" || !Number.isFinite(item)) return null;
    values.push(item);
  }
  return values;
}

function isStrictlyIncreasing(values: readonly number[]): boolean {
  return values.every((value, index) => index === 0 || value > values[index - 1]);
}

function parseTrajectoryContext(value: unknown): TrajectoryFigureContext | null {
  const context = asRecord(value);
  if (
    context === null
    || !hasExactKeys(context, ["chart_type", "time", "groups"])
    || context.chart_type !== "lmm_group_trajectory"
  ) return null;
  const time = finiteNumberArray(context.time);
  if (
    time === null
    || time.length === 0
    || !isStrictlyIncreasing(time)
    || !isDenseJsonArray(context.groups)
    || context.groups.length === 0
  ) {
    return null;
  }
  const groups: TrajectoryGroup[] = [];
  const labels = new Set<string>();
  for (const value of context.groups) {
    const entry = asRecord(value);
    if (
      entry === null
      || !hasExactKeys(entry, ["label", "observed_mean", "fitted_mean"])
      || !isNonEmptyString(entry.label)
    ) return null;
    const observed = finiteNumberArray(entry.observed_mean);
    const fitted = finiteNumberArray(entry.fitted_mean);
    if (
      observed === null
      || fitted === null
      || observed.length !== time.length
      || fitted.length !== time.length
    ) return null;
    if (labels.has(entry.label)) return null;
    labels.add(entry.label);
    groups.push({ label: entry.label, observed_mean: observed, fitted_mean: fitted });
  }
  return { chart_type: "lmm_group_trajectory", time, groups };
}

function parseResult(payload: JsonRecord): RepeatedMeasuresResult | null {
  const required = [
    "status",
    "result_id",
    "estimate",
    "fit_method",
    "inference_method",
  ];
  const diagnostics = hasOwnKey(payload, "diagnostics")
    ? parseSuccessfulResultDiagnostics(payload.diagnostics)
    : [];
  if (
    !hasRequiredOwnKeys(payload, required)
    || payload.status !== "complete"
    || payload.result_id !== LOCKED_RESULT_ID
    || typeof payload.estimate !== "number"
    || !Number.isFinite(payload.estimate)
    || (payload.fit_method !== "reml" && payload.fit_method !== "ml")
    || payload.inference_method !== LOCKED_INFERENCE_METHOD
    || (hasOwnKey(payload, "converged") && payload.converged !== true)
    || (hasOwnKey(payload, "primary_target_id") && payload.primary_target_id !== LOCKED_RESULT_ID)
    || diagnostics === null
    || (hasOwnKey(payload, "result_identity") && !isNonEmptyString(payload.result_identity))
  ) return null;
  const hasTrajectory = hasOwnKey(payload, "figure_context");
  const trajectory = hasTrajectory ? parseTrajectoryContext(payload.figure_context) : null;
  if (hasTrajectory && trajectory === null) return null;
  return {
    result_id: LOCKED_RESULT_ID,
    estimate: payload.estimate,
    fit_method: payload.fit_method,
    trajectory,
    diagnostics,
  };
}

export function buildRepeatedMeasuresViewModel(packet: unknown): RepeatedMeasuresViewModel {
  if (packet === null || packet === undefined) return emptyView();
  const envelope = parseLockedEnvelope(packet);
  if (envelope === null) {
    return blocked("LMM_PACKET_UNRECOGNIZED", "无法识别的模型数据包；未显示运行或比较结论。");
  }

  if (envelope.contract === "linear_mixed_effects.recovery_proposal") {
    const proposal = parseRecoveryPayload(envelope.payload);
    return proposal
      ? {
        phase: "confirmation",
        diagnostics: [],
        proposal,
        comparison: null,
        result: null,
        canExecute: false,
      }
      : blocked("LMM_RECOVERY_PROPOSAL_INVALID", "恢复方案不符合已锁定的合同；未生成执行建议。");
  }

  if (envelope.contract === "linear_mixed_effects.diagnostic") {
    const diagnostics = parseDiagnosticPayload(envelope.payload);
    return diagnostics === null
      ? blocked("LMM_DIAGNOSTIC_PACKET_INVALID", "诊断数据不完整；未显示运行状态或恢复建议。")
      : {
        phase: "diagnostic",
        diagnostics,
        proposal: null,
        comparison: null,
        result: null,
        canExecute: false,
      };
  }

  if (envelope.contract === "analysis_loop.compare") {
    const restricted = parseRestrictedComparison(envelope.payload);
    if (restricted !== null) {
      return {
        phase: "compare",
        diagnostics: [],
        proposal: null,
        comparison: restricted,
        result: null,
        canExecute: false,
      };
    }
    const complete = parseCompleteComparison(envelope.payload);
    return complete !== null
      ? {
        phase: "compare",
        diagnostics: [],
        proposal: null,
        comparison: complete,
        result: null,
        canExecute: false,
      }
      : blocked("LMM_COMPARE_PACKET_INVALID", "比较数据不完整；未显示比较结论。");
  }

  if (envelope.contract === "linear_mixed_effects.result") {
    const result = parseResult(envelope.payload);
    return result !== null
      ? {
        phase: "success",
        diagnostics: [],
        proposal: null,
        comparison: null,
        result,
        canExecute: false,
      }
      : blocked("LMM_RESULT_PACKET_INVALID", "结果数据不完整；未显示运行结论。");
  }

  return blocked("LMM_PACKET_UNRECOGNIZED", "无法识别的模型数据包；未显示运行或比较结论。");
}
