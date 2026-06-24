import { describe, it, expect } from "vitest";
import { adaptHeadSet } from "./graphAdapter";
import type { HeadSetResponse } from "./graphViewTypes";

// A two-head family sharing the cleaning prefix `C` (same node_hash), forking into
// two sibling model nodes M1/M2, each with its own report. The backend already dedups
// by node_hash, so the shared C appears once in `nodes`; the adapter must preserve that.
function fixture(): HeadSetResponse {
  return {
    schema_version: 4,
    legacy: false,
    nodes: {
      "raw-key": { id: "stage:raw", kind: "dataset_stage", display_label: "Raw",
        stage: "source", trust: "ok", node_hash: null, producing_stage: null,
        cas_ref: null, runs: ["run_a", "run_b"] },
      C: { id: "stage:cleaned", kind: "dataset_stage", display_label: "Cleaned",
        stage: "clean", trust: "ok", node_hash: "C", producing_stage: "cleaning",
        cas_ref: { node_hash: "C", artifact: "processed/cleaned_dataset.parquet" },
        runs: ["run_a", "run_b"] },
      M1: { id: "model:ols_1", kind: "model", display_label: "OLS", stage: "model",
        trust: "ok", node_hash: "M1", producing_stage: "estimation", cas_ref: null,
        runs: ["run_a"], editable: true, op_type: "ols", schema_id: "ols@v1",
        editable_schema_source: "run_inputs",
        editable_schema: [
          { key: "model_type", kind: "select", label: "Model", role: "model" },
          { key: "covariance", kind: "select", label: "Covariance", required: false,
            options: ["robust", "clustered", "unadjusted"], value: "robust" },
        ] },
      M2: { id: "model:ols_1", kind: "model", display_label: "OLS", stage: "model",
        trust: "ok", node_hash: "M2", producing_stage: "estimation", cas_ref: null,
        runs: ["run_b"], editable: true, op_type: "ols", schema_id: "ols@v1",
        editable_schema_source: "run_inputs",
        editable_schema: [
          { key: "covariance", kind: "select", label: "Covariance",
            options: ["robust", "clustered", "unadjusted"], value: "unadjusted" },
        ] },
    },
    edges: [
      { source: "raw-key", target: "C" },
      { source: "C", target: "M1" },
      { source: "C", target: "M2" },
    ],
    heads: [
      { run_id: "run_a", head_node_hash: "M1", from_node: null, rerun_of: null,
        rerun_reason: null, status: "completed", created_at: "2026-06-23T00:00:00Z" },
      { run_id: "run_b", head_node_hash: "M2", from_node: "model:ols_1",
        rerun_of: "run_a", rerun_reason: "manual_override", status: "completed",
        created_at: "2026-06-23T01:00:00Z" },
    ],
  };
}

describe("adaptHeadSet", () => {
  it("dedups the shared prefix to a single node", () => {
    const vm = adaptHeadSet(fixture());
    const cleaningNodes = vm.nodes.filter((n) => n.producingStage === "cleaning");
    expect(cleaningNodes).toHaveLength(1);
    expect(cleaningNodes[0].nodeHash).toBe("C");
  });

  it("keeps both sibling model nodes", () => {
    const vm = adaptHeadSet(fixture());
    const models = vm.nodes.filter((n) => n.producingStage === "estimation");
    expect(models.map((n) => n.nodeHash).sort()).toEqual(["M1", "M2"]);
  });

  it("maps heads with camelCased fields", () => {
    const vm = adaptHeadSet(fixture());
    expect(vm.heads).toHaveLength(2);
    const b = vm.heads.find((h) => h.runId === "run_b")!;
    expect(b.headNodeHash).toBe("M2");
    expect(b.fromNode).toBe("model:ols_1");
    expect(b.rerunOf).toBe("run_a");
  });

  it("carries the backfilled editable schema value through", () => {
    const vm = adaptHeadSet(fixture());
    const m2 = vm.nodes.find((n) => n.nodeHash === "M2")!;
    const cov = m2.editableSchema!.find((c) => c.key === "covariance")!;
    expect(cov.value).toBe("unadjusted");
    expect(m2.editableSchemaSource).toBe("run_inputs");
  });

  it("preserves edges as source/target with synthesized ids", () => {
    const vm = adaptHeadSet(fixture());
    expect(vm.edges).toHaveLength(3);
    const forks = vm.edges.filter((e) => e.source === "C");
    expect(forks.map((e) => e.target).sort()).toEqual(["M1", "M2"]);
  });
});
