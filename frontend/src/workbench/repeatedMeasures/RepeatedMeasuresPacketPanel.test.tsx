import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RepeatedMeasuresPacketPanel } from "./RepeatedMeasuresPacketPanel";

const recoveryPacket = {
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
};

describe("RepeatedMeasuresPacketPanel", () => {
  it("does not enter a running state before the user confirms a recovery proposal", () => {
    const onConfirm = vi.fn();
    render(
      <RepeatedMeasuresPacketPanel
        packet={recoveryPacket}
        requestedState="running"
        confirmed={false}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByText("需要确认")).toBeInTheDocument();
    expect(screen.queryByText("运行中")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "确认恢复方案" }));
    expect(onConfirm).toHaveBeenCalledWith(recoveryPacket.payload.action_candidate);
  });

  it("shows a running state only after a valid proposal is confirmed", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={recoveryPacket}
        requestedState="running"
        confirmed
      />,
    );

    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.queryByText("运行成功")).toBeNull();
  });

  it("shows a restricted comparison without a winner claim", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={{
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
        }}
      />,
    );

    expect(screen.getByText(/不作为有效的直接比较依据/)).toBeInTheDocument();
    expect(screen.queryByText(/赢家|winner/i)).toBeNull();
  });

  it("renders all complete server comparison values without deriving a winner", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={{
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
            data_diff: { retained_rows: "unchanged" },
            parameter_diff: { random_slope: "changed" },
            result_diff: {
              group_time_interaction: { status: "complete", changed: true, fields: {} },
            },
            conclusion_diff: {
              target_result_id: "group_time_interaction",
              status: "complete",
              classification: "recorded",
              reason_code: null,
              evidence: {},
            },
            validation_status: "complete",
            integrity_findings: [],
            logical_key: "compare:lmm-source-v1:lmm-child-v1",
            strategy_version: "linear_mixed_effects_v1",
            schema_version: "compare_packet_v1",
          },
        }}
      />,
    );

    expect(screen.getByText("比较事实")).toBeInTheDocument();
    expect(screen.getByText("样本与数据")).toBeInTheDocument();
    expect(screen.getByText("参数")).toBeInTheDocument();
    expect(screen.getByText(/retained_rows/)).toBeInTheDocument();
    expect(screen.getByText(/unchanged/)).toBeInTheDocument();
    expect(screen.getByText(/random_slope/)).toBeInTheDocument();
    expect(screen.getAllByText(/changed/)).not.toHaveLength(0);
    expect(screen.queryByText(/赢家|winner/i)).toBeNull();
  });

  it("renders supplied LMM facts and marks absent facts as unavailable", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={{
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
            optimizer: "lbfgs",
            nobs: 480,
            n_groups: 80,
            observations_per_group: { subject_1: 6 },
            coefficients: {
              group_time_interaction: {
                result_id: "group_time_interaction",
                estimate: 0.9,
                inference_method: "asymptotic_wald_z_v1",
                source_id: "model_results.linear_mixed_effects_1.coefficients.group_time_interaction",
              },
            },
            random_effects: { intercept_variance: 0.7, residual_variance: 0.5 },
            warnings: ["LMM_RANDOM_EFFECTS_SINGULAR"],
          },
        }}
      />,
    );

    expect(screen.getByText("服务端模型事实")).toBeInTheDocument();
    expect(screen.getByText("lbfgs")).toBeInTheDocument();
    expect(screen.getByText("480")).toBeInTheDocument();
    expect(screen.getByText(/subject_1/)).toBeInTheDocument();
    expect(screen.getByText(/model_results\.linear_mixed_effects_1\.coefficients\.group_time_interaction/)).toBeInTheDocument();
    expect(screen.getByText(/intercept_variance/)).toBeInTheDocument();
    expect(screen.getAllByText("未提供")).not.toHaveLength(0);
  });

  it("renders a terminal diagnostic instead of a success claim", () => {
    render(
      <RepeatedMeasuresPacketPanel
        requestedState="running"
        packet={{
          contract: "linear_mixed_effects.diagnostic",
          contract_version: "1.0",
          producer_version: "linear_mixed_effects@1.0",
          payload: {
            status: "failed",
            diagnostics: [{
              code: "LMM_CONVERGENCE_FAILED",
              severity: "error",
              status: "failed",
              evidence: { optimizer: "lbfgs" },
              action_candidate: null,
            }],
          },
        }}
      />,
    );

    expect(screen.getByText("诊断")).toBeInTheDocument();
    expect(screen.queryByText("运行成功")).toBeNull();
  });

  it("shows success only for a complete result packet", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={{
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
        }}
      />,
    );

    expect(screen.getByText("运行成功")).toBeInTheDocument();
    expect(screen.getByText("0.9")).toBeInTheDocument();
  });

  it("renders trusted complete warning diagnostics with a successful result", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={{
          contract: "linear_mixed_effects.result",
          contract_version: "1.0",
          producer_version: "linear_mixed_effects@1.0",
          payload: {
            status: "complete",
            result_id: "group_time_interaction",
            estimate: 0.9,
            fit_method: "reml",
            inference_method: "asymptotic_wald_z_v1",
            diagnostics: [{
              code: "LMM_RANDOM_EFFECTS_SINGULAR",
              severity: "warning",
              status: "complete",
              evidence: { slope_variance: 0 },
              action_candidate: null,
            }],
          },
        }}
      />,
    );

    expect(screen.getByText("运行成功")).toBeInTheDocument();
    expect(screen.getByLabelText("Repeated measures result warnings")).toBeInTheDocument();
    expect(screen.getByText("LMM_RANDOM_EFFECTS_SINGULAR")).toBeInTheDocument();
  });

  it("renders only server-provided trajectory values from a complete result packet", () => {
    render(
      <RepeatedMeasuresPacketPanel
        packet={{
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
        }}
      />,
    );

    expect(screen.getByLabelText("组别轨迹数据表")).toBeInTheDocument();
    expect(screen.getByText("3.2")).toBeInTheDocument();
  });

  it.each([
    ["pending", "等待执行"],
    ["running", "运行中"],
  ] as const)("does not trust a packet-free %s state", (requestedState, label) => {
    render(<RepeatedMeasuresPacketPanel packet={null} requestedState={requestedState} />);

    expect(screen.queryByText(label)).toBeNull();
    expect(screen.getByText("验证")).toBeInTheDocument();
    expect(screen.queryByText("运行成功")).toBeNull();
  });

  it("renders a blocked diagnostic instead of a caller-supplied running state for an empty diagnostic packet", () => {
    render(
      <RepeatedMeasuresPacketPanel
        requestedState="running"
        packet={{
          contract: "linear_mixed_effects.diagnostic",
          contract_version: "1.0",
          producer_version: "linear_mixed_effects@1.0",
          payload: { status: "blocked", diagnostics: [] },
        }}
      />,
    );

    expect(screen.getByText("诊断")).toBeInTheDocument();
    expect(screen.queryByText("运行中")).toBeNull();
  });

  it("safely falls back for an unrecognized packet instead of displaying a requested running state", () => {
    render(
      <RepeatedMeasuresPacketPanel
        requestedState="running"
        packet={{ contract: "future.packet", payload: {} }}
      />,
    );

    expect(screen.getByText("诊断")).toBeInTheDocument();
    expect(screen.queryByText("运行中")).toBeNull();
  });
});
