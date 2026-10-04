import { describe, expect, it } from "vitest";

import type { ForestViewModel } from "../../lineage/api/graphViewTypes";
import { FOCUS_PROVIDERS, focusFromWorkbench, resolveFocus } from "./focus";

// Two run families: the active OLS run and an IV run whose head is another run.
const forest = {
  schemaVersion: 1,
  legacy: false,
  edges: [],
  familyCount: 2,
  familyRunCount: 2,
  heads: [
    { runId: "run_ols", headNodeHash: "h-ols", fromNode: null, rerunOf: null, rerunReason: null, status: "completed", createdAt: null },
    { runId: "run_iv", headNodeHash: "h-iv", fromNode: null, rerunOf: null, rerunReason: null, status: "completed", createdAt: null },
  ],
  nodes: [
    { nodeKey: "n-raw-ols", nodeHash: "r1", opNodeId: "stage:raw", kind: "dataset", stage: "raw", title: "Raw input data", runs: ["run_ols"] },
    { nodeKey: "n-ols", nodeHash: "h-ols", opNodeId: "model:ols_1", kind: "model", stage: "model", title: "ols_robust", runs: ["run_ols"] },
    { nodeKey: "n-iv", nodeHash: "h-iv", opNodeId: "model:iv_2sls_1", kind: "model", stage: "model", title: "iv_2sls", runs: ["run_iv"] },
  ],
} as unknown as ForestViewModel;
const env = { projectRoot: "/p", activeRunId: "run_ols", forest };

describe("Agent focus", () => {
  it("has one provider per focus kind", () => {
    expect(Object.keys(FOCUS_PROVIDERS).sort()).toEqual(["dataset", "node", "plan", "project", "report"]);
  });

  it("acts on a selected node in the run that owns it, not the active head", () => {
    const resolved = resolveFocus(focusFromWorkbench({ projectRoot: "/p", declared: null, selectedKey: "n-iv" }), env);
    expect(resolved).toMatchObject({ role: "chain", runId: "run_iv", nodeKey: "n-iv", ownerIsNotActive: true });
    expect(resolved.label).toBe("Run iv · iv_2sls");
  });

  it("lets the Data page's dataset win over the graph selection", () => {
    const resolved = resolveFocus(
      focusFromWorkbench({ projectRoot: "/p", declared: { kind: "dataset", id: "stage:raw", runId: "run_ols" }, selectedKey: "n-iv" }),
      env,
    );
    expect(resolved).toMatchObject({ role: "chain", runId: "run_ols", nodeKey: "n-raw-ols" });
    expect(resolved.label).toBe("Dataset · Raw input data");
  });

  it("is the project Agent on a blank canvas, and a run's head model on the run rail", () => {
    expect(resolveFocus(focusFromWorkbench({ projectRoot: "/p", declared: null, selectedKey: null }), env).role).toBe("main");
    const run = resolveFocus(focusFromWorkbench({ projectRoot: "/p", declared: null, selectedKey: "run:run_iv" }), env);
    expect(run).toMatchObject({ runId: "run_iv", nodeKey: "n-iv" });
  });

  it("keeps an unknown selection on the active run's chain", () => {
    const resolved = resolveFocus(focusFromWorkbench({ projectRoot: "/p", declared: null, selectedKey: "draft:x:model_1" }), env);
    expect(resolved).toMatchObject({ role: "chain", runId: "run_ols", nodeKey: null });
  });
});

describe("a leftover detail tab", () => {
  it("does not outrank a run switched after it", () => {
    const resolved = resolveFocus(
      focusFromWorkbench({ projectRoot: "/p", declared: null, selectedKey: "n-iv", staleSelectionRunId: "run_ols" }),
      env,
    );
    expect(resolved).toMatchObject({ runId: "run_ols", nodeKey: "n-ols" });
  });
});
