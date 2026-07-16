import { describe, expect, it } from "vitest";
import { applyAgentNavigationRef } from "./agentNavigation";
import type { AgentNavigationRef } from "./agentTypes";

const graphRef: AgentNavigationRef = {
  kind: "graph_node",
  id: "run-child::model:ols_1",
  label: "OLS",
  relation: "source",
  available: true,
  href: {
    view: "graph",
    run_id: "run-child",
    node_ref: "model:ols_1",
    forest_node_key: "run-child::model:ols_1",
  },
};

const operationRef: AgentNavigationRef = {
  kind: "operation",
  id: "oprec-9",
  label: "model.rerun · completed",
  relation: "audit",
  available: true,
  href: {
    view: "agent",
    run_id: "run-child",
    session_id: "agent_chain_child",
    operation_record_id: "oprec-9",
  },
};

const diffRef: AgentNavigationRef = {
  kind: "diff",
  id: "oprec-9",
  label: "Diff · canonical",
  relation: "result",
  available: true,
  href: {
    view: "agent",
    session_id: "agent_chain_child",
    operation_record_id: "oprec-9",
    diff: "1",
  },
};

describe("applyAgentNavigationRef", () => {
  it("opens a graph target without losing unrelated query params", () => {
    const out = applyAgentNavigationRef(
      new URLSearchParams("project_root=/foo&tab=lineage"),
      graphRef,
    );

    expect(out.get("run")).toBe("run-child");
    expect(out.get("focus")).toBe("run-child::model:ols_1");
    expect(out.get("pinned")).toBe("1");
    expect(out.get("tab")).toBe("lineage");
    expect(out.get("project_root")).toBe("/foo");
  });

  it("focuses an operation in the Agent panel", () => {
    const out = applyAgentNavigationRef(
      new URLSearchParams("run=run-source"),
      operationRef,
    );

    expect(out.get("run")).toBe("run-child");
    expect(out.get("panel")).toBe("agent");
    expect(out.get("agent_session")).toBe("agent_chain_child");
    expect(out.get("operation")).toBe("oprec-9");
  });

  it("deep-links an operation diff in the Agent panel", () => {
    const out = applyAgentNavigationRef(
      new URLSearchParams("run=run-source"),
      diffRef,
    );

    expect(out.get("panel")).toBe("agent");
    expect(out.get("agent_session")).toBe("agent_chain_child");
    expect(out.get("operation")).toBe("oprec-9");
    expect(out.get("diff")).toBe("1");
  });

  it("ignores unavailable refs", () => {
    const out = applyAgentNavigationRef(
      new URLSearchParams("run=run-source"),
      { ...graphRef, available: false },
    );

    expect(out.toString()).toBe("run=run-source");
  });
});
