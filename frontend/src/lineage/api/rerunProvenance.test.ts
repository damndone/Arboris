import { describe, expect, it } from "vitest";
import { getCompareWithSourceGate } from "./rerunProvenance";
import type {
  NodeOperationContextV1,
  RerunFromProvenance,
} from "./nodeOperationContext";

const sourceProvenance: RerunFromProvenance = {
  owner_run_id: "run_source",
  op_node_id: "model:ols_1",
  node_hash: "hash_source",
  context_fingerprint: "nocv1:source",
  rerun_request_id: "req_1",
};

function context(
  overrides: Partial<NodeOperationContextV1> = {},
): NodeOperationContextV1 {
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: "nocv1:child",
    selection: {
      forest_node_key: "hash_child",
      node_hash: "hash_child",
      display_label: "OLS",
      kind: "model",
      stage: "model",
    },
    ownership: {
      active_head_run_id: "run_child",
      candidate_run_refs: [
        {
          run_id: "run_child",
          op_node_id: "model:ols_1",
          node_hash: "hash_child",
          is_active_head: true,
          path_contains_node: true,
        },
      ],
      candidate_run_ids: ["run_child"],
      shared_by_run_ids: ["run_child"],
      owner_run_id: "run_child",
      owner_resolution: "single_candidate",
    },
    operation_target: {
      owner_run_id: "run_child",
      op_node_id: "model:ols_1",
      node_hash: "hash_child",
      node_state: "materialized",
    },
    lineage_context: {
      path_run_id: "run_child",
      upstream_path: [],
      active_head_path_contains_node: true,
    },
    node_payload: {
      decisions: [],
      artifacts: [],
      editable_schema: null,
      params: {},
    },
    capabilities: {
      can_rerun: true,
      can_ask_ai: true,
      can_compare: false,
      can_rollback_focus: false,
      can_edit_params: false,
      disabled_reasons: [],
    },
    comparison_readiness: {
      can_compare: false,
      candidate_run_ids: ["run_child"],
      active_head_run_id: "run_child",
      owner_run_id: "run_child",
      shared_by_run_ids: ["run_child"],
    },
    context_diagnostics: { warnings: [], resolution_notes: [] },
    ...overrides,
  };
}

describe("getCompareWithSourceGate", () => {
  it("passes when node-level rerun_from is present", () => {
    const result = getCompareWithSourceGate(
      context({ rerun_from: sourceProvenance }),
    );

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.source_kind).toBe("node_level_rerun_from");
    expect(result.rerun_from).toEqual(sourceProvenance);
  });

  it("fails closed without rerun_from instead of using runs[0]", () => {
    const result = getCompareWithSourceGate(
      context({
        ownership: {
          ...context().ownership,
          candidate_run_refs: [
            {
              run_id: "run_source",
              op_node_id: "model:ols_1",
              node_hash: "hash_source",
              is_active_head: false,
              path_contains_node: true,
            },
            {
              run_id: "run_child",
              op_node_id: "model:ols_1",
              node_hash: "hash_child",
              is_active_head: true,
              path_contains_node: true,
            },
          ],
          candidate_run_ids: ["run_source", "run_child"],
          shared_by_run_ids: ["run_source", "run_child"],
        },
      }),
    );

    expect(result).toEqual({ ok: false, reason: "missing_rerun_from" });
  });

  it("does not use candidate_run_ids[0] as compare source when rerun_from is absent", () => {
    const result = getCompareWithSourceGate(
      context({
        ownership: {
          ...context().ownership,
          candidate_run_ids: ["run_source_like", "run_child"],
          shared_by_run_ids: ["run_source_like", "run_child"],
        },
      }),
    );

    expect(result).toEqual({ ok: false, reason: "missing_rerun_from" });
  });

  it("fails closed when node-level and run-level rerun_from disagree", () => {
    const result = getCompareWithSourceGate(
      context({
        rerun_from: sourceProvenance,
        run_rerun_from: {
          ...sourceProvenance,
          context_fingerprint: "nocv1:other",
        },
      }),
    );

    expect(result).toEqual({ ok: false, reason: "provenance_mismatch" });
  });

  it("allows run-level fallback only for a strict single-candidate context", () => {
    const result = getCompareWithSourceGate(
      context({ run_rerun_from: sourceProvenance }),
    );

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.source_kind).toBe("run_level_rerun_from_fallback");
    expect(result.rerun_from).toEqual(sourceProvenance);
  });

  it("rejects run-level fallback when ownership has multiple candidate runs", () => {
    const result = getCompareWithSourceGate(
      context({
        run_rerun_from: sourceProvenance,
        ownership: {
          ...context().ownership,
          candidate_run_ids: ["run_source", "run_child"],
          shared_by_run_ids: ["run_source", "run_child"],
        },
      }),
    );

    expect(result).toEqual({
      ok: false,
      reason: "run_level_fallback_ambiguous",
    });
  });
});
