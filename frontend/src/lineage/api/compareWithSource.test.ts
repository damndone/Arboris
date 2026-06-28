import { describe, expect, it } from "vitest";
import { buildCompareWithSourceResult } from "./compareWithSource";
import type { NodeOperationContextV1 } from "./nodeOperationContext";

function baseContext(
  runId: string,
  fingerprint: string,
  params: Record<string, unknown>,
  metrics: Record<string, unknown>,
): NodeOperationContextV1 {
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: fingerprint,
    selection: {
      forest_node_key: `${runId}:key`,
      node_hash: `${runId}:hash`,
      display_label: "OLS",
      kind: "model",
      stage: "model",
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
      upstream_path: [
        { key: `${runId}:source`, label: "Source", kind: "dataset", stage: "source" },
      ],
      active_head_path_contains_node: true,
    },
    node_payload: {
      decisions: [],
      artifacts: [],
      editable_schema: null,
      params,
      metrics,
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

describe("buildCompareWithSourceResult", () => {
  it("builds summary field diffs and empty sections", () => {
    const result = buildCompareWithSourceResult({
      source: baseContext(
        "run_source",
        "nocv1:source",
        { covariance: "clustered" },
        { r_squared: 0.42 },
      ),
      current: baseContext(
        "run_child",
        "nocv1:child",
        { covariance: "robust" },
        { r_squared: 0.51 },
      ),
      provenance: {
        source_kind: "node_level_rerun_from",
        rerun_request_id: "req_1",
      },
    });

    expect(result.sections.params.items[0]).toMatchObject({
      field_id: "covariance",
      change_type: "changed",
      old_value: "clustered",
      new_value: "robust",
    });
    expect(result.sections.metrics.items[0].delta).toBeCloseTo(0.09);
    expect(result.sections.diagnostics).toMatchObject({
      changed: false,
      total_changed: 0,
      items: [],
    });
  });

  it("truncates long field sections but preserves total changed count", () => {
    const sourceParams = Object.fromEntries(
      Array.from({ length: 12 }, (_, index) => [`p${index}`, index]),
    );
    const currentParams = Object.fromEntries(
      Array.from({ length: 12 }, (_, index) => [`p${index}`, index + 1]),
    );

    const result = buildCompareWithSourceResult({
      source: baseContext("run_source", "nocv1:source", sourceParams, {}),
      current: baseContext("run_child", "nocv1:child", currentParams, {}),
      provenance: {
        source_kind: "run_level_rerun_from_fallback",
        rerun_request_id: "req_2",
      },
    });

    expect(result.sections.params.total_changed).toBe(12);
    expect(result.sections.params.items).toHaveLength(10);
    expect(result.sections.params.truncated).toBe(true);
  });
});
