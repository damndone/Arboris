import { describe, expect, it } from "vitest";
import type { ForestViewModel } from "../../../lineage/api/graphViewTypes";
import { focusFromWorkbench, resolveFocus } from "../focus";

const forest = {
  schemaVersion: 1, legacy: false, edges: [], familyCount: 2, familyRunCount: 3,
  heads: [
    { runId: "run_active", headNodeHash: "active" },
    { runId: "run_latest", headNodeHash: "shared" },
  ],
  nodes: [
    { nodeKey: "n-active", nodeHash: "active", opNodeId: "model:ols_1", kind: "model", stage: "model", title: "OLS", runs: ["run_active"] },
    { nodeKey: "n-shared", nodeHash: "shared", opNodeId: "model:ols_1", kind: "model", stage: "model", title: "Shared", runs: ["run_old", "run_latest"] },
  ],
} as unknown as ForestViewModel;
const env = { projectRoot: "/p", activeRunId: "run_active", forest };

describe("A14 focus boundaries", () => {
  it("selects the family head when a shared node excludes the active run", () => {
    expect(resolveFocus({ kind: "node", id: "n-shared" }, env)).toMatchObject({
      runId: "run_latest", nodeKey: "n-shared", role: "chain", ownerIsNotActive: true,
    });
  });
  it("keeps an unresolved dataset on its declared run without inventing a node", () => {
    const resolved = resolveFocus({ kind: "dataset", id: "stage:missing", runId: "run_latest" }, env);
    expect(resolved).toMatchObject({ runId: "run_latest", role: "chain", nodeKey: null, ownerIsNotActive: true });
    expect(resolved.label).toBe("Dataset · stage:missing");
  });
  it("uses the unresolved-node fallback for a nonexistent run rail selection", () => {
    const focus = focusFromWorkbench({ projectRoot: "/p", declared: null, selectedKey: "run:run_absent" });
    const resolved = resolveFocus(focus, env);
    // The step-8 record says a selection absent from the forest stays on
    // the active chain without a node, as for an unresolved draft node.
    expect(resolved).toMatchObject({ runId: "run_active", role: "chain", nodeKey: null });
  });
});
