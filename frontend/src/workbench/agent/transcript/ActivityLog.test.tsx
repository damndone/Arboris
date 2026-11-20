import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentMessage } from "../agentTypes";
import { activeToolActivityLabel, toolStep, updateActiveToolCalls } from "../toolActivity";
import { ActivityLog, ToolStepRow, activityItems, planSteps, resultLines } from "./ActivityLog";

const tool = (id: string, name: string, content = '{"ok": true, "output": {}}'): AgentMessage => ({
  entry_id: id, at: "2026-11-01T00:00:00Z", role: "tool", content, name, stop_reason: null, error: null, navigation: [],
});

describe("activityItems", () => {
  it("folds reads in a row and keeps everything else in order", () => {
    const items = activityItems([tool("a", "inspect_data_schema"), tool("b", "list_project_datasets"), tool("c", "run_operation"),
      tool("d", "inspect_data_schema"), tool("e", "run_operation"), tool("f", "inspect_result_summary"), tool("g", "check_model_claims"), tool("h", "read_reports")]);
    expect(items.map((item) => item.kind === "step" ? item.message.entry_id : item.messages.map((m) => m.entry_id).join(""))).toEqual(["ab", "c", "d", "e", "fgh"]);
  });
});

describe("thoughts", () => {
  const thought = (id: string): AgentMessage => ({ ...tool(id, ""), role: "assistant", content: "", reasoning: "hmm", name: null, stop_reason: "tool_calls" });
  it("travel with the reads around them", () => {
    const items = activityItems([thought("t0"), tool("a", "inspect_data_schema"), thought("t1"), tool("b", "read_reports"), thought("t2"), tool("c", "run_operation"), thought("t3")]);
    expect(items.map((item) => item.kind === "step" ? item.message.entry_id : item.messages.map((m) => m.entry_id).join(""))).toEqual(["t0", "at1b", "t2", "c", "t3"]);
  });
});

describe("toolStep", () => {
  it("names the operation", () => {
    expect(toolStep("run_operation ✓ ok", { target: "Frequency table of a", seconds: 2 })).toMatchObject({ title: "Ran", target: "Frequency table of a", seconds: 2 });
    expect(toolStep("run_operation ✗ failed — bad", { target: "Frequency table of a", seconds: null })).toMatchObject({ title: "Tried", state: "failed" });
    expect(toolStep("run_operation ✓ proposal ready", { target: "x", seconds: null })).toMatchObject({ title: "Proposed", state: "waiting" });
    expect(toolStep("run_operation ✓ ok")).toMatchObject({ title: "Ran an operation", target: null });
  });
});

describe("results", () => {
  it("shows the output, or the reason when refused", () => {
    expect(resultLines('{"ok": true, "output": {"a": 1}}').join("")).toContain('"a": 1');
    expect(resultLines('{"ok": false, "error": "x", "error_details": [{"message": "why", "path": "changes"}]}').join("")).toContain("changes");
    expect(resultLines('{"ok": false, "error": "x", "error_details": [{"message": "why"}]}')).toEqual([]);
    expect(resultLines("plain")).toEqual(["plain"]);
  });

  it("opens to head and tail, the middle on request", () => {
    const output = Object.fromEntries(Array.from({ length: 40 }, (_, i) => [`k${i}`, i]));
    render(<ToolStepRow step={toolStep("show_chart ✓ ok")} content={JSON.stringify({ ok: true, output })} />);
    const details = document.querySelector("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(screen.getByText(/k0/)).not.toHaveTextContent("k20");
    fireEvent.click(screen.getByRole("button", { name: /lines/ }));
    expect(screen.getByText(/k20/)).toBeTruthy();
  });

  it("marks a group with a refused read and leaves it open", () => {
    render(<ActivityLog live={false} steps={[tool("a", "inspect_data_schema"), tool("b", "inspect_data_schema", '{"ok": false, "error": "x"}')]} render={(m) => <div key={m.entry_id}>{m.entry_id}</div>} />);
    expect(screen.getByTestId("agent-explored")).toHaveAttribute("open");
  });

  it("says Exploring while the turn runs", () => {
    render(<ActivityLog live steps={[tool("a", "inspect_data_schema"), tool("b", "read_reports")]} render={(m) => <div key={m.entry_id}>{m.entry_id}</div>} />);
    expect(screen.getByTestId("agent-explored")).toHaveTextContent("Exploring");
  });
});

describe("the plan a step saved", () => {
  const saved = JSON.stringify({ ok: true, output: { plan: { steps: [
    { title: "Summarize AQI", status: "done" }, { title: "Compare groups", status: "pending" },
  ] } } });

  it("reads the steps of update_plan", () => {
    expect(planSteps(saved).map(step => step.title)).toEqual(["Summarize AQI", "Compare groups"]);
    expect(planSteps('{"ok": true, "output": {}}')).toEqual([]);
    expect(planSteps("not json")).toEqual([]);
    expect(planSteps(undefined)).toEqual([]);
  });

  it("shows them as a checklist without opening the row", () => {
    render(<ToolStepRow step={toolStep("update_plan ✓ ok")} content={saved} />);
    const list = screen.getByTestId("agent-plan-steps");
    expect(list).toHaveTextContent("✔ Summarize AQI");
    expect(list).toHaveTextContent("□ Compare groups");
  });
});

describe("the step in progress", () => {
  const started = (tool_id: string, target?: string) => updateActiveToolCalls([], [{
    event_type: "tool_execution_start", session_id: "s", command_id: "c",
    payload: { tool_call_id: "t", tool_id, target },
  } as never]);

  it("says what it is doing, on what", () => {
    expect(activeToolActivityLabel(started("run_operation", "Paired t-test of a, b"))).toBe("Running Paired t-test of a, b");
    expect(activeToolActivityLabel(started("inspect_data_schema"))).toBe("Reading data schema");
    expect(activeToolActivityLabel(started("calculate", "a / b"))).toBe("Calculating a / b");
  });
});
