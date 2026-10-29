import { describe, expect, test, vi } from "vitest";
import { applyMode, availableModes, currentMode, cycleMode } from "./AgentModeMenu";

function controls(executionMode: "ask" | "auto", executionPolicy: "proposal_only" | "auto_read_only") {
  return { executionMode, executionPolicy, setExecutionMode: vi.fn(), setExecutionPolicy: vi.fn() };
}

describe("AgentModeMenu", () => {
  test("three modes from the two settings", () => {
    expect(currentMode(controls("ask", "proposal_only"))).toBe("review");
    expect(currentMode(controls("ask", "auto_read_only"))).toBe("read_only");
    expect(currentMode(controls("auto", "auto_read_only"))).toBe("auto");
    expect(currentMode(controls("auto", "proposal_only"))).toBe("review");
  });

  test("each mode sets both settings it needs", () => {
    const agent = controls("auto", "auto_read_only");
    applyMode(agent, "review");
    expect(agent.setExecutionMode).toHaveBeenCalledWith("ask");
    expect(agent.setExecutionPolicy).toHaveBeenCalledWith("proposal_only");
    applyMode(agent, "auto");
    expect(agent.setExecutionMode).toHaveBeenLastCalledWith("auto");
    expect(agent.setExecutionPolicy).toHaveBeenLastCalledWith("auto_read_only");
  });

  test.each(["proposal_only", "auto_read_only"] as const)("Auto clears the previous %s policy", (policy) => {
    const agent = {
      executionMode: "ask" as "ask" | "auto", executionPolicy: policy as "proposal_only" | "auto_read_only",
      setExecutionMode(mode: "ask" | "auto") { this.executionMode = mode; },
      setExecutionPolicy(next: "proposal_only" | "auto_read_only") { this.executionPolicy = next; },
    };
    applyMode(agent, "auto");
    expect([agent.executionMode, agent.executionPolicy]).toEqual(["auto", "auto_read_only"]);
    expect(currentMode(agent)).toBe("auto");
  });

  test("cycling goes review → read-only → auto → review, skipping what is not offered", () => {
    const agent = controls("auto", "auto_read_only");
    cycleMode(agent);
    expect(agent.setExecutionMode).toHaveBeenLastCalledWith("ask");
    expect(agent.setExecutionPolicy).toHaveBeenLastCalledWith("proposal_only");
    const noAuto = { executionPolicy: "auto_read_only" as const, setExecutionPolicy: vi.fn() };
    expect(availableModes(noAuto)).toEqual(["review", "read_only"]);
    cycleMode(noAuto);
    expect(noAuto.setExecutionPolicy).toHaveBeenLastCalledWith("proposal_only");
  });
});
