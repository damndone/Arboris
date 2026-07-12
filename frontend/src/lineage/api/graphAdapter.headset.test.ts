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

  it("carries project family count when the project forest response includes families", () => {
    const backend = {
      ...fixture(),
      families: [
        { family_root: "run_a", members: ["run_a", "run_b"] },
        { family_root: "run_c", members: ["run_b", "run_c"] },
      ],
    };

    const vm = adaptHeadSet(backend);

    expect(vm.familyCount).toBe(2);
    expect(vm.familyRunCount).toBe(3);
  });

  it("carries head-level rerun_from without attaching it to an unrelated source node", () => {
    const backend = fixture();
    backend.heads = backend.heads.map((head) =>
      head.run_id === "run_b"
        ? {
            ...head,
            rerun_from: {
              owner_run_id: "run_a",
              op_node_id: "model:ols_1",
              node_hash: "M1",
              context_fingerprint: "nocv1:source",
              rerun_request_id: "req_source",
            },
          }
        : head,
    );

    const vm = adaptHeadSet(backend);
    const runBHead = vm.heads.find((h) => h.runId === "run_b")!;
    const sourceNode = vm.nodes.find((n) => n.nodeHash === "M1")!;
    const childNode = vm.nodes.find((n) => n.nodeHash === "M2")!;

    expect(runBHead.runRerunFrom?.rerun_request_id).toBe("req_source");
    expect(sourceNode.runRerunFrom).toBeUndefined();
    expect(childNode.runRerunFrom).toBeUndefined();
  });

  it("attaches run-level fallback only to the unique produced head node", () => {
    const backend = fixture();
    backend.heads = backend.heads.map((head) =>
      head.run_id === "run_b"
        ? {
            ...head,
            rerun_from: {
              owner_run_id: "run_a",
              op_node_id: "model:ols_1",
              node_hash: "M1",
              context_fingerprint: "nocv1:source",
              rerun_request_id: "req_head",
            },
          }
        : head,
    );
    backend.nodes.M2 = {
      ...backend.nodes.M2,
      produced_by_rerun_request_id: "req_head",
    };

    const vm = adaptHeadSet(backend);
    const childNode = vm.nodes.find((n) => n.nodeHash === "M2")!;
    const sourceNode = vm.nodes.find((n) => n.nodeHash === "M1")!;

    expect(childNode.runRerunFrom?.rerun_request_id).toBe("req_head");
    expect(sourceNode.runRerunFrom).toBeUndefined();
  });

  it("attaches run-level fallback to the produced op node when the run head is a report", () => {
    const backend = fixture();
    backend.nodes.R2 = {
      id: "report:html",
      kind: "report",
      display_label: "Report",
      stage: "report",
      trust: "ok",
      node_hash: "R2",
      producing_stage: "report",
      cas_ref: null,
      runs: ["run_b"],
    };
    backend.heads = backend.heads.map((head) =>
      head.run_id === "run_b"
        ? {
            ...head,
            head_node_hash: "R2",
            rerun_from: {
              owner_run_id: "run_a",
              op_node_id: "model:ols_1",
              node_hash: "M1",
              context_fingerprint: "nocv1:source",
              rerun_request_id: "req_report_head",
            },
          }
        : head,
    );
    backend.nodes.M2 = {
      ...backend.nodes.M2,
      produced_by_rerun_request_id: "req_report_head",
    };

    const vm = adaptHeadSet(backend);
    const childModel = vm.nodes.find((n) => n.nodeHash === "M2")!;
    const childReport = vm.nodes.find((n) => n.nodeHash === "R2")!;

    expect(childModel.runRerunFrom?.rerun_request_id).toBe("req_report_head");
    expect(childReport.runRerunFrom).toBeUndefined();
  });

  it("carries model stats decoration through (C-2)", () => {
    const backend = fixture();
    backend.nodes.M1.stats = {
      n_observations: 60,
      r_squared: 0.86,
      coefficients: [{ variable: "education", estimate: 0.55 }],
    };
    const vm = adaptHeadSet(backend);
    const m1 = vm.nodes.find((n) => n.nodeHash === "M1")!;
    expect(m1.stats?.r_squared).toBe(0.86);
    expect(m1.stats?.coefficients).toEqual([
      { variable: "education", estimate: 0.55 },
    ]);
    const m2 = vm.nodes.find((n) => n.nodeHash === "M2")!;
    expect(m2.stats).toBeUndefined();
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

  it("degrades to a legacy marker on the old per-run shape (edges as dict, no heads)", () => {
    // The REAL legacy ?view=headset response is the old per-run graph: nodes/edges
    // are dicts-by-id and there is no `heads` array. adaptHeadSet must not throw.
    const legacy = {
      schema_version: 3,
      legacy: true,
      nodes: { "stage:cleaned": { id: "stage:cleaned", kind: "k", display_label: "C" } },
      edges: { "e1": { id: "e1", source_id: "stage:raw", target_id: "stage:cleaned" } },
    } as unknown as HeadSetResponse;
    const vm = adaptHeadSet(legacy);
    expect(vm.legacy).toBe(true);
    expect(vm.nodes).toEqual([]);
    expect(vm.edges).toEqual([]);
    expect(vm.heads).toEqual([]);
  });
});
