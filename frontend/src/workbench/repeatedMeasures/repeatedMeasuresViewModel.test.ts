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

  it.each([
    ["wrong contract version", { contract_version: "2.0" }],
    ["wrong producer", { producer_version: "untrusted@1.0" }],
    ["unexpected envelope field", { trace_id: "forged" }],
    ["missing envelope field", { producer_version: undefined }],
  ])("fails closed for a %s", (_label, override) => {
    const packet = {
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
      ...override,
    };
    if ("producer_version" in override && override.producer_version === undefined) {
      delete packet.producer_version;
    }

    expect(buildRepeatedMeasuresViewModel(packet)).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      canExecute: false,
      diagnostics: [{ code: "LMM_PACKET_UNRECOGNIZED", status: "blocked" }],
    });
  });

  it("fails closed when recovery envelope fields are inherited", () => {
    const inheritedPayload = Object.assign(Object.create({
      proposal_status: "pending_confirmation",
      action_candidate: {
        action_id: "lmm.simplify_random_effects_v1",
        operation_id: "model.rerun",
        patch: { model_options: { random_slope: false } },
        required_confirmation: true,
      },
    }), { fixture_id: "prototype-forgery" });
    const forgedPacket = Object.assign(Object.create({
      contract: "linear_mixed_effects.recovery_proposal",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: inheritedPayload,
    }), {
      unrelated_one: true,
      unrelated_two: true,
      unrelated_three: true,
      unrelated_four: true,
    });

    expect(buildRepeatedMeasuresViewModel(forgedPacket)).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      canExecute: false,
      diagnostics: [{ code: "LMM_PACKET_UNRECOGNIZED", status: "blocked" }],
    });
  });

  it("fails closed when recovery payload fields are inherited", () => {
    const inheritedPayload = Object.assign(Object.create({
      proposal_status: "pending_confirmation",
      action_candidate: {
        action_id: "lmm.simplify_random_effects_v1",
        operation_id: "model.rerun",
        patch: { model_options: { random_slope: false } },
        required_confirmation: true,
      },
    }), { fixture_id: "prototype-forgery" });

    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.recovery_proposal",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: inheritedPayload,
    })).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      canExecute: false,
      diagnostics: [{ code: "LMM_PACKET_UNRECOGNIZED", status: "blocked" }],
    });
  });

  it("fails closed when an otherwise valid envelope has a symbol field", () => {
    const packet = Object.assign({
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
    }, { [Symbol("forged")]: true });

    expect(buildRepeatedMeasuresViewModel(packet)).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      canExecute: false,
      diagnostics: [{ code: "LMM_PACKET_UNRECOGNIZED", status: "blocked" }],
    });
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

  it("fails closed when a recovery child object has a non-JSON prototype", () => {
    const patch = Object.assign(Object.create({}), {
      model_options: { random_slope: false },
    });

    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.recovery_proposal",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        proposal_status: "pending_confirmation",
        action_candidate: {
          action_id: "lmm.simplify_random_effects_v1",
          operation_id: "model.rerun",
          patch,
          required_confirmation: true,
        },
      },
    })).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      diagnostics: [{ code: "LMM_RECOVERY_PROPOSAL_INVALID", status: "blocked" }],
    });
  });

  it("rejects a recovery proposal outside the locked confirmation state", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.recovery_proposal",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        proposal_status: "executed",
        action_candidate: {
          action_id: "lmm.simplify_random_effects_v1",
          operation_id: "model.rerun",
          patch: { model_options: { random_slope: false } },
          required_confirmation: true,
        },
      },
    });

    expect(viewModel).toMatchObject({
      phase: "diagnostic",
      proposal: null,
      diagnostics: [{ code: "LMM_RECOVERY_PROPOSAL_INVALID", status: "blocked" }],
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

  it.each([
    ["a source run", { source_run_id: "" }],
    ["a child run", { child_run_id: "" }],
    ["a locked restriction reason", { reason_code: "FUTURE_REASON" }],
  ])("fails closed when a restricted comparison lacks %s", (_label, override) => {
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
        ...override,
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
        inference_method: "asymptotic_wald_z_v1",
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

  it("accepts the locked data-only trajectory context", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
        inference_method: "asymptotic_wald_z_v1",
        figure_context: {
          chart_type: "lmm_group_trajectory",
          time: [0, 1],
          groups: [{
            label: "treated",
            observed_mean: [10, 3],
            fitted_mean: [10, 3.2],
          }],
        },
      },
    });

    expect(viewModel).toMatchObject({
      phase: "success",
      result: {
        trajectory: {
          chart_type: "lmm_group_trajectory",
          groups: [{ label: "treated", fitted_mean: [10, 3.2] }],
        },
      },
    });
  });

  it("fails closed for a sparse trajectory array", () => {
    const time = [0, 1];
    delete time[1];

    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
        inference_method: "asymptotic_wald_z_v1",
        figure_context: {
          chart_type: "lmm_group_trajectory",
          time,
          groups: [{
            label: "treated",
            observed_mean: [10, 3],
            fitted_mean: [10, 3.2],
          }],
        },
      },
    })).toMatchObject({
      phase: "diagnostic",
      result: null,
      diagnostics: [{ code: "LMM_RESULT_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("fails closed for a trajectory array with a symbol field", () => {
    const time = Object.assign([0, 1], { [Symbol("forged")]: true });

    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
        inference_method: "asymptotic_wald_z_v1",
        figure_context: {
          chart_type: "lmm_group_trajectory",
          time,
          groups: [{
            label: "treated",
            observed_mean: [10, 3],
            fitted_mean: [10, 3.2],
          }],
        },
      },
    })).toMatchObject({
      phase: "diagnostic",
      result: null,
      diagnostics: [{ code: "LMM_RESULT_PACKET_INVALID", status: "blocked" }],
    });
  });

  it.each([
    ["unordered time", [1, 0], [{
      label: "treated",
      observed_mean: [10, 3],
      fitted_mean: [10, 3.2],
    }]],
    ["duplicate group labels", [0, 1], [
      {
        label: "treated",
        observed_mean: [10, 3],
        fitted_mean: [10, 3.2],
      },
      {
        label: "treated",
        observed_mean: [9, 2],
        fitted_mean: [9, 2.1],
      },
    ]],
  ])("fails closed for a trajectory with %s", (_label, time, groups) => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
        inference_method: "asymptotic_wald_z_v1",
        figure_context: {
          chart_type: "lmm_group_trajectory",
          time,
          groups,
        },
      },
    })).toMatchObject({
      phase: "diagnostic",
      result: null,
      diagnostics: [{ code: "LMM_RESULT_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("keeps a converged result with complete warning diagnostics", () => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
        inference_method: "asymptotic_wald_z_v1",
        converged: true,
        diagnostics: [{
          code: "LMM_RANDOM_EFFECTS_SINGULAR",
          severity: "warning",
          status: "complete",
          evidence: { slope_variance: 0 },
          action_candidate: null,
        }],
      },
    })).toMatchObject({
      phase: "success",
      result: { result_id: "group_time_interaction" },
    });
  });

  it.each([
    ["an empty result id", { result_id: "" }],
    ["an unknown fit method", { fit_method: "gls" }],
    ["an unknown inference method", { inference_method: "invented" }],
    ["a non-converged full result", { converged: false }],
    ["a conflicting primary target id", { primary_target_id: "other_target" }],
    ["a full result with terminal diagnostics", {
      diagnostics: [{
        code: "LMM_CONVERGENCE_FAILED",
        severity: "error",
        status: "failed",
        evidence: { optimizer: "lbfgs" },
        action_candidate: null,
      }],
    }],
    ["an unknown complete result diagnostic", {
      diagnostics: [{
        code: "LMM_FUTURE_DIAGNOSTIC",
        severity: "warning",
        status: "complete",
        evidence: { source: "fixture" },
        action_candidate: null,
      }],
    }],
  ])("fails closed for a complete result with %s", (_label, override) => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        status: "complete",
        result_id: "group_time_interaction",
        estimate: 0.9,
        fit_method: "reml",
        inference_method: "asymptotic_wald_z_v1",
        ...override,
      },
    });

    expect(viewModel).toMatchObject({
      phase: "diagnostic",
      result: null,
      diagnostics: [{ code: "LMM_RESULT_PACKET_INVALID", status: "blocked" }],
    });
  });

  it.each([
    ["inherited result fields", Object.create({
      status: "complete",
      result_id: "group_time_interaction",
      estimate: 0.9,
      fit_method: "reml",
      inference_method: "asymptotic_wald_z_v1",
    }), "LMM_PACKET_UNRECOGNIZED"],
    ["a symbol result field", Object.assign({
      status: "complete",
      result_id: "group_time_interaction",
      estimate: 0.9,
      fit_method: "reml",
      inference_method: "asymptotic_wald_z_v1",
    }, { [Symbol("forged")]: true }), "LMM_RESULT_PACKET_INVALID"],
  ])("fails closed for %s", (_label, payload, diagnosticCode) => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload,
    })).toMatchObject({
      phase: "diagnostic",
      result: null,
      diagnostics: [{ code: diagnosticCode, status: "blocked" }],
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

  it("fails closed when a full comparison target result id is inherited", () => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "complete",
        source_run_id: "lmm-source-v1",
        child_run_id: "lmm-child-v1",
        target: Object.create({ result_id: "forged-result-id" }),
        data_diff: {},
        parameter_diff: {},
        result_diff: {},
        conclusion_diff: {},
        validation_status: "pass",
        integrity_findings: [],
        logical_key: "compare:lmm-source-v1:lmm-child-v1",
        strategy_version: "linear_mixed_effects_v1",
        schema_version: "1",
      },
    })).toMatchObject({
      phase: "diagnostic",
      comparison: null,
      diagnostics: [{ code: "LMM_COMPARE_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("fails closed when a full comparison target does not match the LMM primary result", () => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "complete",
        source_run_id: "lmm-source-v1",
        child_run_id: "lmm-child-v1",
        target: { result_id: "other_target" },
        data_diff: {},
        parameter_diff: {},
        result_diff: {},
        conclusion_diff: {},
        validation_status: "pass",
        integrity_findings: [],
        logical_key: "compare:lmm-source-v1:lmm-child-v1",
        strategy_version: "linear_mixed_effects_v1",
        schema_version: "1",
      },
    })).toMatchObject({
      phase: "diagnostic",
      comparison: null,
      diagnostics: [{ code: "LMM_COMPARE_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("fails closed when full comparison evidence omits primary result and conclusion facts", () => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "complete",
        source_run_id: "lmm-source-v1",
        child_run_id: "lmm-child-v1",
        target: {
          result_id: "group_time_interaction",
          role: "primary",
          label: "treated group × time",
          resolution_source: "explicit_result_id",
          target_hash: "a".repeat(64),
        },
        data_diff: {},
        parameter_diff: {},
        result_diff: {},
        conclusion_diff: {},
        validation_status: "pass",
        integrity_findings: [],
        logical_key: "compare:lmm-source-v1:lmm-child-v1",
        strategy_version: "linear_mixed_effects_v1",
        schema_version: "1",
      },
    })).toMatchObject({
      phase: "diagnostic",
      comparison: null,
      diagnostics: [{ code: "LMM_COMPARE_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("fails closed when full comparison facts report failed validation", () => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "analysis_loop.compare",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: {
        compare_status: "complete",
        source_run_id: "lmm-source-v1",
        child_run_id: "lmm-child-v1",
        target: { result_id: "group_time_interaction" },
        data_diff: {},
        parameter_diff: {},
        result_diff: {},
        conclusion_diff: {},
        validation_status: "fail",
        integrity_findings: ["VALIDATION_NOT_COMPLETE"],
        logical_key: "compare:lmm-source-v1:lmm-child-v1",
        strategy_version: "linear_mixed_effects_v1",
        schema_version: "1",
      },
    })).toMatchObject({
      phase: "diagnostic",
      comparison: null,
      diagnostics: [{ code: "LMM_COMPARE_PACKET_INVALID", status: "blocked" }],
    });
  });

  it("fails closed when a diagnostic packet has no trusted diagnostics", () => {
    const viewModel = buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.diagnostic",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: { status: "blocked", diagnostics: [] },
    });

    expect(viewModel).toMatchObject({
      phase: "diagnostic",
      diagnostics: [{ code: "LMM_DIAGNOSTIC_PACKET_INVALID", status: "blocked" }],
    });
  });
});
