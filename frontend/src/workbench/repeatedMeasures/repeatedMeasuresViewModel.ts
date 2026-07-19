type JsonRecord = Record<string, unknown>;

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

export type RestrictedRepeatedMeasuresComparison = {
  status: "restricted";
  reason_code: string;
  message: string;
  winner: null;
};

export type CompleteRepeatedMeasuresComparison = {
  status: "complete";
  comparison_scope: string;
  result_id: string;
  source_run_id: string;
  child_run_id: string;
  winner: null;
};

export type RepeatedMeasuresComparison =
  | RestrictedRepeatedMeasuresComparison
  | CompleteRepeatedMeasuresComparison;

export type RepeatedMeasuresResult = {
  result_id: string;
  estimate: number;
  fit_method: string;
};

export type RepeatedMeasuresViewModel = {
  phase: "diagnostic" | "confirmation" | "compare" | "success";
  diagnostics: RepeatedMeasuresDiagnosticView[];
  proposal: RepeatedMeasuresRecoveryProposal | null;
  comparison: RepeatedMeasuresComparison | null;
  result: RepeatedMeasuresResult | null;
  canExecute: false;
};

const UNKNOWN_DIAGNOSTIC_MESSAGE = "未识别的诊断；请检查完整运行记录。";

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "unknown";
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => key in value);
}

function unknownDiagnosticView(payload: JsonRecord | null): RepeatedMeasuresViewModel {
  const diagnostics = Array.isArray(payload?.diagnostics) ? payload.diagnostics : [];
  return {
    phase: "diagnostic",
    diagnostics: diagnostics.map((value) => {
      const diagnostic = asRecord(value);
      return {
        code: asString(diagnostic?.code),
        severity: asString(diagnostic?.severity),
        status: asString(diagnostic?.status),
        message: UNKNOWN_DIAGNOSTIC_MESSAGE,
        recovery: null,
      };
    }),
    proposal: null,
    comparison: null,
    result: null,
    canExecute: false,
  };
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
    || options?.random_slope !== false
  ) return null;

  return {
    action_id: "lmm.simplify_random_effects_v1",
    operation_id: "model.rerun",
    patch: { model_options: { random_slope: false } },
    required_confirmation: true,
  };
}

export function buildRepeatedMeasuresViewModel(packet: unknown): RepeatedMeasuresViewModel {
  const envelope = asRecord(packet);
  const payload = envelope ? asRecord(envelope.payload) : null;

  if (envelope?.contract === "linear_mixed_effects.recovery_proposal") {
    const proposal = lockedRecoveryProposal(payload?.action_candidate);
    if (proposal) {
      return {
        phase: "confirmation",
        diagnostics: [],
        proposal,
        comparison: null,
        result: null,
        canExecute: false,
      };
    }
    return {
      phase: "diagnostic",
      diagnostics: [{
        code: "LMM_RECOVERY_PROPOSAL_INVALID",
        severity: "error",
        status: "blocked",
        message: "恢复方案不符合已锁定的合同；未生成执行建议。",
        recovery: null,
      }],
      proposal: null,
      comparison: null,
      result: null,
      canExecute: false,
    };
  }

  if (
    envelope?.contract === "linear_mixed_effects.diagnostic"
    && typeof payload?.status === "string"
    && Array.isArray(payload.diagnostics)
  ) {
    return unknownDiagnosticView(payload);
  }

  if (envelope?.contract === "analysis_loop.compare" && payload?.compare_status === "restricted") {
    if (
      typeof payload.reason_code !== "string"
      || payload.reason_code === ""
      || typeof payload.user_safe_message !== "string"
      || payload.user_safe_message === ""
    ) {
      return {
        phase: "diagnostic",
        diagnostics: [{
          code: "LMM_COMPARE_PACKET_INVALID",
          severity: "error",
          status: "blocked",
          message: "比较数据不完整；未显示比较结论。",
          recovery: null,
        }],
        proposal: null,
        comparison: null,
        result: null,
        canExecute: false,
      };
    }
    return {
      phase: "compare",
      diagnostics: [],
      proposal: null,
      comparison: {
        status: "restricted",
        reason_code: payload.reason_code,
        message: payload.user_safe_message,
        winner: null,
      },
      result: null,
      canExecute: false,
    };
  }

  if (
    envelope?.contract === "analysis_loop.compare"
    && payload?.compare_status === "complete"
    && typeof payload.comparison_scope === "string"
    && typeof payload.result_id === "string"
    && typeof payload.source_run_id === "string"
    && typeof payload.child_run_id === "string"
  ) {
    return {
      phase: "compare",
      diagnostics: [],
      proposal: null,
      comparison: {
        status: "complete",
        comparison_scope: payload.comparison_scope,
        result_id: payload.result_id,
        source_run_id: payload.source_run_id,
        child_run_id: payload.child_run_id,
        winner: null,
      },
      result: null,
      canExecute: false,
    };
  }

  if (
    envelope?.contract === "linear_mixed_effects.result"
    && payload?.status === "complete"
    && typeof payload.result_id === "string"
    && typeof payload.estimate === "number"
    && Number.isFinite(payload.estimate)
    && typeof payload.fit_method === "string"
  ) {
    return {
      phase: "success",
      diagnostics: [],
      proposal: null,
      comparison: null,
      result: {
        result_id: payload.result_id,
        estimate: payload.estimate,
        fit_method: payload.fit_method,
      },
      canExecute: false,
    };
  }

  if (envelope !== null) {
    return {
      phase: "diagnostic",
      diagnostics: [{
        code: "LMM_PACKET_UNRECOGNIZED",
        severity: "error",
        status: "blocked",
        message: "无法识别的模型数据包；未显示运行或比较结论。",
        recovery: null,
      }],
      proposal: null,
      comparison: null,
      result: null,
      canExecute: false,
    };
  }

  return unknownDiagnosticView(null);
}
