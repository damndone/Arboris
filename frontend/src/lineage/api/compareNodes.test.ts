import { describe, expect, it } from "vitest";
import { buildNodeComparison } from "./compareNodes";
import type { NodeOperationContextV1 } from "./nodeOperationContext";

type Decision = NodeOperationContextV1["node_payload"]["decisions"][number];

function decision(overrides: Partial<Decision> & { id: string }): Decision {
  return {
    id: overrides.id,
    question: overrides.question ?? "Standard errors",
    picked: overrides.picked ?? "robust",
    alternatives: overrides.alternatives ?? [],
    why: overrides.why ?? "",
    evidence: overrides.evidence ?? [],
    reviewStatus: overrides.reviewStatus ?? "passed",
  };
}

function ctx(opts: {
  runId: string;
  key?: string;
  kind?: string;
  stage?: string;
  params?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  decisions?: Decision[];
  diagnostics?: Array<{ level: string; message: string }>;
  upstream?: string[];
}): NodeOperationContextV1 {
  const runId = opts.runId;
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: `${runId}:fp`,
    selection: {
      forest_node_key: opts.key ?? `${runId}:model`,
      node_hash: `${runId}:hash`,
      display_label: "OLS",
      kind: opts.kind ?? "model",
      stage: opts.stage ?? "model",
    },
    ownership: {
      active_head_run_id: runId,
      candidate_run_refs: [],
      candidate_run_ids: [runId],
      shared_by_run_ids: [runId],
      owner_run_id: runId,
      owner_resolution: "single_candidate",
    },
    operation_target: {
      owner_run_id: runId,
      op_node_id: "model:ols_1",
      node_hash: `${runId}:hash`,
      node_state: "materialized",
    },
    lineage_context: {
      path_run_id: runId,
      upstream_path: (opts.upstream ?? ["shared:source"]).map((key) => ({
        key,
        label: key,
        kind: "dataset",
        stage: "source",
      })),
      active_head_path_contains_node: true,
    },
    node_payload: {
      decisions: opts.decisions ?? [],
      artifacts: [],
      editable_schema: null,
      params: opts.params ?? {},
      metrics: opts.metrics,
      execution_diagnostics: opts.diagnostics,
    },
    capabilities: {
      can_rerun: true,
      can_ask_ai: true,
      can_compare: true,
      can_rollback_focus: false,
      can_edit_params: false,
      disabled_reasons: [],
    },
    comparison_readiness: {
      can_compare: true,
      candidate_run_ids: [runId],
      active_head_run_id: runId,
      owner_run_id: runId,
      shared_by_run_ids: [runId],
    },
    context_diagnostics: { warnings: [], resolution_notes: [] },
  };
}

describe("buildNodeComparison", () => {
  it("diffs params with a signed numeric delta and totals changes", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", params: { covariance: "clustered", alpha: 0.05 } }),
      ctx({ runId: "b", params: { covariance: "robust", alpha: 0.1 } }),
    );
    expect(result.compare_version).toBe("compare-nodes/v1");
    expect(result.sections.params.items).toContainEqual(
      expect.objectContaining({ field_id: "covariance", old_value: "clustered", new_value: "robust" }),
    );
    const alpha = result.sections.params.items.find((d) => d.field_id === "alpha");
    expect(alpha?.delta).toBeCloseTo(0.05);
    expect(result.total_changed).toBe(2);
  });

  it("diffs metrics", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", metrics: { r_squared: 0.8 } }),
      ctx({ runId: "b", metrics: { r_squared: 0.86 } }),
    );
    expect(result.sections.metrics.items[0].delta).toBeCloseTo(0.06);
  });

  it("diffs decisions by id (picked / reviewStatus changes)", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", decisions: [decision({ id: "se", picked: "robust", reviewStatus: "needed" })] }),
      ctx({ runId: "b", decisions: [decision({ id: "se", picked: "clustered", reviewStatus: "passed" })] }),
    );
    expect(result.sections.decisions.changed).toBe(true);
    expect(result.sections.decisions.items[0]).toMatchObject({
      field_id: "se",
      change_type: "changed",
      old_value: { picked: "robust", reviewStatus: "needed" },
      new_value: { picked: "clustered", reviewStatus: "passed" },
    });
  });

  it("reports identical decisions as unchanged", () => {
    const same = [decision({ id: "se", picked: "robust", reviewStatus: "passed" })];
    const result = buildNodeComparison(
      ctx({ runId: "a", decisions: same }),
      ctx({ runId: "b", decisions: [decision({ id: "se", picked: "robust", reviewStatus: "passed" })] }),
    );
    expect(result.sections.decisions.changed).toBe(false);
  });

  it("diffs execution diagnostics as added/removed entries", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", diagnostics: [{ level: "warning", message: "few obs" }] }),
      ctx({ runId: "b", diagnostics: [{ level: "warning", message: "collinear" }] }),
    );
    expect(result.sections.diagnostics.total_changed).toBe(2);
    const kinds = result.sections.diagnostics.items.map((d) => d.change_type).sort();
    expect(kinds).toEqual(["added", "removed"]);
  });

  it("diffs the upstream path", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", upstream: ["a:source", "a:clean"] }),
      ctx({ runId: "b", upstream: ["b:source"] }),
    );
    expect(result.sections.upstream_path.changed).toBe(true);
  });

  it("flags same_node when both selections are the same forest node", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", key: "shared:model" }),
      ctx({ runId: "b", key: "shared:model" }),
    );
    expect(result.same_node).toBe(true);
  });

  it("flags cross_kind when comparing different kinds", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", kind: "model", stage: "model" }),
      ctx({ runId: "b", kind: "dataset", stage: "source" }),
    );
    expect(result.cross_kind).toBe(true);
    expect(result.total_changed).toBe(0);
  });

  it("produces no changes for identical nodes", () => {
    const result = buildNodeComparison(
      ctx({ runId: "a", params: { covariance: "robust" }, metrics: { r_squared: 0.8 } }),
      ctx({ runId: "b", params: { covariance: "robust" }, metrics: { r_squared: 0.8 } }),
    );
    expect(result.total_changed).toBe(0);
  });
});
