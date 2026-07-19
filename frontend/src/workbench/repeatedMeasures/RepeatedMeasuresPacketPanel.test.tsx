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
            user_safe_message: "两个模型使用 REML 且固定效应结构不同；似然、AIC 和似然比检验不作为有效的直接比较依据。",
          },
        }}
      />,
    );

    expect(screen.getByText(/不作为有效的直接比较依据/)).toBeInTheDocument();
    expect(screen.queryByText(/赢家|winner/i)).toBeNull();
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
          },
        }}
      />,
    );

    expect(screen.getByText("运行成功")).toBeInTheDocument();
    expect(screen.getByText("0.9")).toBeInTheDocument();
  });

  it.each([
    ["pending", "等待执行"],
    ["running", "运行中"],
  ] as const)("renders the packet-free %s state without claiming success", (requestedState, label) => {
    render(<RepeatedMeasuresPacketPanel packet={{}} requestedState={requestedState} />);

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText("运行成功")).toBeNull();
  });
});
