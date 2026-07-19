import { describe, expect, it } from "vitest";

import { buildRepeatedMeasuresViewModel } from "./repeatedMeasuresViewModel";

describe("buildRepeatedMeasuresViewModel", () => {
  it("keeps an unknown diagnostic safely blocked and proposal-free", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.diagnostic",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "blocked",
        diagnostics: [
          {
            code: "LMM_FUTURE_DIAGNOSTIC",
            severity: "error",
            status: "blocked",
            evidence: { source: "fixture" },
            action_candidate: {
              action_id: "unsafe.action",
              operation_id: "model.rerun",
              patch: { model_options: { random_slope: false } },
              required_confirmation: true,
            },
          },
        ],
      },
    });

    expect(viewModel.phase).toBe("diagnostic");
    expect(viewModel.diagnostics).toEqual([
      {
        code: "LMM_FUTURE_DIAGNOSTIC",
        severity: "error",
        status: "blocked",
        message: "未识别的诊断；请检查完整运行记录。",
        recovery: null,
      },
    ]);
  });

  it("keeps the locked recovery proposal confirmation-bound", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.recovery_proposal",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        proposal_status: "pending_confirmation",
        action_candidate: {
          action_id: "lmm.simplify_random_effects_v1",
          operation_id: "model.rerun",
          patch: { model_options: { random_slope: false } },
          required_confirmation: true,
        },
      },
    });

    expect(viewModel).toMatchObject({
      phase: "confirmation",
      canExecute: false,
      proposal: {
        action_id: "lmm.simplify_random_effects_v1",
        operation_id: "model.rerun",
        patch: { model_options: { random_slope: false } },
        required_confirmation: true,
      },
    });
  });

  it("rejects a recovery proposal that changes anything beyond random slope", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.recovery_proposal",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        proposal_status: "pending_confirmation",
        action_candidate: {
          action_id: "lmm.simplify_random_effects_v1",
          operation_id: "model.rerun",
          patch: { model_options: { random_slope: false, fit_method: "ml" } },
          required_confirmation: true,
        },
      },
    });

    expect(viewModel).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      diagnostics: [{
        code: "LMM_RECOVERY_PROPOSAL_INVALID",
        status: "blocked",
        recovery: null,
      }],
    });
  });

  it("renders a restricted comparison without inventing a winner", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "restricted",
        reason_code: "REML_FIXED_EFFECTS_DIFFER",
        source_run_id: "lmm-source-v1",
        child_run_id: "lmm-child-v1",
        user_safe_message: "两个模型使用 REML 且固定效应结构不同；似然、AIC 和似然比检验不作为有效的直接比较依据。",
      },
    });

    expect(viewModel).toMatchObject({
      phase: "compare",
      comparison: {
        status: "restricted",
        reason_code: "REML_FIXED_EFFECTS_DIFFER",
        winner: null,
      },
    });
  });

  it("fails closed when a restricted comparison lacks its safe message", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "restricted",
        reason_code: "REML_FIXED_EFFECTS_DIFFER",
      },
    });

    expect(viewModel).toMatchObject({
      phase: "diagnostic",
      comparison: null,
      diagnostics: [{ code: "LMM_COMPARE_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("exposes a successful result only from a complete result packet", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
      },
    });

    expect(viewModel).toMatchObject({
      phase: "success",
      result: {
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
      },
    });
  });

  it("keeps a complete child comparison factual without naming a winner", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "complete",
        comparison_scope: "same_fixed_effects_ml",
        source_run_id: "lmm-source-v1",
        child_run_id: "lmm-child-v1",
        result_id: "group_time_interaction",
      },
    });

    expect(viewModel).toMatchObject({
      phase: "compare",
      comparison: {
        status: "complete",
        comparison_scope: "same_fixed_effects_ml",
        winner: null,
      },
    });
  });
});
