import { describe, expect, test, vi } from "vitest";
import { applyMode, availableModes, currentMode, cycleMode } from "./AgentModeMenu";

function controls(executionMode: "ask" | "auto", executionPolicy: "proposal_only" | "auto_read_only") {
  return { executionMode, executionPolicy, setExecutionMode: vi.fn(), setExecutionPolicy: vi.fn() };
}

describe("AgentModeMenu", () => {
  test("three modes from the two settings", () => {
    expect(currentMode(controls("ask", "proposal_only"))).toBe("review");
    expect(currentMode(controls("ask", "auto_read_only"))).toBe("read_only");
    expect(currentMode(controls("auto", "proposal_only"))).toBe("auto");
  });

  test("each mode sets both settings it needs", () => {
    const agent = controls("auto", "auto_read_only");
    applyMode(agent, "review");
    expect(agent.setExecutionMode).toHaveBeenCalledWith("ask");
    expect(agent.setExecutionPolicy).toHaveBeenCalledWith("proposal_only");
    applyMode(agent, "auto");
    expect(agent.setExecutionMode).toHaveBeenLastCalledWith("auto");
  });

  test("cycling goes review → read-only → auto → review, skipping what is not offered", () => {
    const agent = controls("auto", "proposal_only");
    cycleMode(agent);
    expect(agent.setExecutionMode).toHaveBeenLastCalledWith("ask");
    expect(agent.setExecutionPolicy).toHaveBeenLastCalledWith("proposal_only");
    const noAuto = { executionPolicy: "auto_read_only" as const, setExecutionPolicy: vi.fn() };
    expect(availableModes(noAuto)).toEqual(["review", "read_only"]);
    cycleMode(noAuto);
    expect(noAuto.setExecutionPolicy).toHaveBeenLastCalledWith("proposal_only");
  });
});
