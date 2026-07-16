import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentCapabilityPopover } from "./AgentCapabilityPopover";

const catalog = {
  capabilities: [
    {
      operation_id: "graph.fork",
      operation_version: "v1",
      effect_level: "mutation",
      scope: "current chain/node",
      scope_requirements: ["chain", "active_head"],
      risk_level: "mutating",
      confirmation_policy: "required",
      ui_description: "从当前节点创建一个新 Chain 分支。",
      example_prompts: ["从当前节点创建一个新分支。"],
      natural_language_enabled: true,
    },
  ],
  boundary: {
    advisory: [{ id: "analysis.explain", label: "比较结果和解释诊断", description: "只读解释。" }],
    unsupported: [{ id: "data.cleaning", label: "修改数据清洗规则", description: "没有 typed operation。" }],
  },
};

describe("AgentCapabilityPopover", () => {
  it("renders registry-backed executable, advisory, and unsupported boundaries", () => {
    render(<AgentCapabilityPopover catalog={catalog} />);
    fireEvent.click(screen.getByTestId("agent-capability-trigger"));

    expect(screen.getByTestId("agent-capability-executable")).toHaveTextContent("graph.fork");
    expect(screen.getByTestId("agent-capability-executable")).toHaveTextContent("required");
    expect(screen.getByTestId("agent-capability-advisory")).toHaveTextContent("比较结果和解释诊断");
    expect(screen.getByTestId("agent-capability-unsupported")).toHaveTextContent("修改数据清洗规则");
  });

  it("is honest when the capability projection is unavailable", () => {
    render(<AgentCapabilityPopover catalog={null} />);
    fireEvent.click(screen.getByTestId("agent-capability-trigger"));
    expect(screen.getByTestId("agent-capability-popover")).toHaveTextContent(
      "Capabilities unavailable",
    );
  });
});
