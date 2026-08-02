import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  AI_ACTIVITY_EVENT,
  appendAiActivity,
  askAiHistoryForNode,
  loadAiActivity,
  makeActivityId,
  type AskAiActivityRecord,
} from "./aiActivityLog";

function askRecord(over: Partial<AskAiActivityRecord> = {}): AskAiActivityRecord {
  return {
    kind: "ask_ai",
    id: makeActivityId(),
    at: new Date().toISOString(),
    node_key: "nk1",
    node_label: "OLS (primary)",
    question: "Explain this node",
    status: "answered",
    answer: "It is an OLS model.",
    ...over,
  };
}

describe("aiActivityLog", () => {
  beforeEach(() => window.localStorage.clear());

  it("appends newest-first, isolated per project", () => {
    appendAiActivity("/p/a", askRecord({ question: "q1" }));
    appendAiActivity("/p/a", askRecord({ question: "q2" }));
    appendAiActivity("/p/b", askRecord({ question: "other project" }));

    const a = loadAiActivity("/p/a");
    expect(a.map((r) => (r.kind === "ask_ai" ? r.question : ""))).toEqual(["q2", "q1"]);
    expect(loadAiActivity("/p/b")).toHaveLength(1);
  });

  it("caps at 50 records", () => {
    for (let i = 0; i < 55; i++) appendAiActivity("/p/a", askRecord({ id: `r${i}` }));
    expect(loadAiActivity("/p/a")).toHaveLength(50);
    expect(loadAiActivity("/p/a")[0].id).toBe("r54");
  });

  it("filters per-node ask_ai history, mixed kinds excluded", () => {
    appendAiActivity("/p/a", askRecord({ node_key: "nk1", question: "on nk1" }));
    appendAiActivity("/p/a", askRecord({ node_key: "nk2", question: "on nk2" }));
    appendAiActivity("/p/a", {
      kind: "report_generate",
      id: makeActivityId(),
      at: new Date().toISOString(),
      run_id: "run1",
      instruction: "write it",
      fact_count: 5,
      excluded_count: 0,
      report_record_id: "rpt1",
    });
    const hist = askAiHistoryForNode("/p/a", "nk1");
    expect(hist).toHaveLength(1);
    expect(hist[0].question).toBe("on nk1");
  });

  it("retains terminal Notebook plans and failed report attempts per project", () => {
    appendAiActivity("/p/a", {
      kind: "notebook_plan",
      id: makeActivityId(),
      at: "2026-08-01T16:30:00Z",
      notebook_id: "nb_1",
      interaction_mode: "plan",
      goal: "Forecast the series.",
      status: "error",
      error: "NOTEBOOK_PLANNING_UNAVAILABLE",
    });
    appendAiActivity("/p/a", {
      kind: "report_generate",
      id: makeActivityId(),
      at: "2026-08-01T16:31:00Z",
      run_id: "run1",
      instruction: "write it",
      fact_count: 5,
      excluded_count: 0,
      status: "error",
      error: "LLM unavailable",
    });

    expect(loadAiActivity("/p/a")).toEqual([
      expect.objectContaining({ kind: "report_generate", status: "error" }),
      expect.objectContaining({ kind: "notebook_plan", status: "error" }),
    ]);
  });

  it("dispatches the live-refresh event on append", () => {
    const listener = vi.fn();
    window.addEventListener(AI_ACTIVITY_EVENT, listener);
    appendAiActivity("/p/a", askRecord());
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AI_ACTIVITY_EVENT, listener);
  });

  it("survives corrupted storage", () => {
    window.localStorage.setItem("workbench:ai-activity:/p/a", "{not json");
    expect(loadAiActivity("/p/a")).toEqual([]);
    expect(() => appendAiActivity("/p/a", askRecord())).not.toThrow();
    expect(loadAiActivity("/p/a")).toHaveLength(1);
  });
});
