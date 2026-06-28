import { describe, expect, it } from "vitest";
import {
  explainResolveNodeOperationContext,
  makeOwnerResolutionSeedFixture,
  resolveNodeOperationContext,
} from "./nodeOperationContext";

describe("resolveNodeOperationContext", () => {
  it("carries node and run rerun provenance into the resolved context", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const nodeRerunFrom = {
      owner_run_id: "run_source",
      op_node_id: "model:shared_ols",
      node_hash: "hash_source_model",
      context_fingerprint: "nocv1:source",
      rerun_request_id: "req_node",
    };
    const runRerunFrom = { ...nodeRerunFrom };
    const result = resolveNodeOperationContext({
      forest: {
        ...seed.forest,
        nodes: seed.forest.nodes.map((node) =>
          node.nodeKey === seed.sharedNodeKey
            ? {
                ...node,
                rerunFrom: nodeRerunFrom,
                runRerunFrom,
              }
            : node,
        ),
      },
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.rerun_from).toEqual(nodeRerunFrom);
    expect(result.context.run_rerun_from).toEqual(runRerunFrom);
    expect(result.context.resolver_trace).toEqual(
      expect.arrayContaining([
        `selected forest node: ${seed.sharedNodeKey}`,
        `active_head_run_id: ${seed.activeHeadRunId}`,
      ]),
    );
  });

  it("prefers active head when it owns the shared node and is not runs[0]", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_run_id).toBe(seed.activeHeadRunId);
    expect(result.context.ownership.owner_resolution).toBe(
      "active_head_contains_node",
    );
    expect(result.context.operation_target.op_node_id).toBe(
      seed.sharedOpNodeId,
    );
  });

  it("returns ambiguous_owner_run instead of falling back to first candidate", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: "run_not_owner",
    });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("ambiguous_owner_run");
    expect(result.candidate_run_refs?.map((r) => r.run_id)).toEqual([
      "run_a",
      "run_c",
    ]);
  });

  it("allows run-scoped selected hint to override active head", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
      selected_run_hint: "run_a",
      selected_run_hint_source: "run_scoped_surface",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_run_id).toBe("run_a");
    expect(result.context.ownership.owner_resolution).toBe("selected_run_hint");
  });

  it("does not let an unscoped selected hint override active head", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
      selected_run_hint: "run_a",
      selected_run_hint_source: "none",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_run_id).toBe(seed.activeHeadRunId);
  });

  it("manual candidate selection resolves context without changing active head", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: "run_not_owner",
      selected_run_hint: "run_a",
      selected_run_hint_source: "manual_candidate_selection",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_resolution).toBe(
      "manual_candidate_selection",
    );
    expect(result.context.ownership.active_head_run_id).toBe("run_not_owner");
  });

  it("changes fingerprint when owner head freshness changes and context is otherwise stable", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const first = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    const refreshed = resolveNodeOperationContext({
      forest: {
        ...seed.forest,
        heads: seed.forest.heads.map((head) =>
          head.runId === seed.activeHeadRunId
            ? { ...head, createdAt: "2026-06-27T00:02:00Z" }
            : head,
        ),
      },
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });

    expect(first.ok).toBe(true);
    expect(refreshed.ok).toBe(true);
    if (!first.ok) throw new Error(first.reason);
    if (!refreshed.ok) throw new Error(refreshed.reason);
    expect(refreshed.context.context_fingerprint).not.toBe(
      first.context.context_fingerprint,
    );
    const {
      context_fingerprint: _firstFingerprint,
      resolver_trace: _firstTrace,
      ...firstContext
    } = first.context;
    const {
      context_fingerprint: _refreshedFingerprint,
      resolver_trace: _refreshedTrace,
      ...refreshedContext
    } = refreshed.context;
    expect(refreshedContext).toEqual(firstContext);
  });

  it("changes fingerprint when selected node candidate owner set changes", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const first = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    const expanded = resolveNodeOperationContext({
      forest: {
        ...seed.forest,
        nodes: seed.forest.nodes.map((node) =>
          node.nodeKey === seed.sharedNodeKey
            ? { ...node, runs: [...node.runs, "run_d"] }
            : node,
        ),
        heads: [
          ...seed.forest.heads,
          {
            runId: "run_d",
            headNodeHash: seed.sharedNodeKey,
            fromNode: seed.sharedOpNodeId,
            rerunOf: "run_a",
            rerunReason: "manual_override",
            status: "completed",
            createdAt: "2026-06-27T00:03:00Z",
          },
        ],
      },
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });

    expect(first.ok).toBe(true);
    expect(expanded.ok).toBe(true);
    if (!first.ok) throw new Error(first.reason);
    if (!expanded.ok) throw new Error(expanded.reason);
    expect(expanded.context.context_fingerprint).not.toBe(
      first.context.context_fingerprint,
    );
    expect(expanded.context.ownership.candidate_run_ids).toEqual([
      "run_a",
      "run_c",
      "run_d",
    ]);
    expect(expanded.context.ownership.shared_by_run_ids).toEqual([
      "run_a",
      "run_c",
      "run_d",
    ]);
    expect(expanded.context.comparison_readiness.can_compare).toBe(true);
  });

  it("excludes merged-forest upstream nodes that are not in the owner run", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const source = seed.forest.nodes.find((node) => node.nodeKey === "hash_source");
    if (!source) throw new Error("missing fixture source node");
    const runAOnlySource = {
      ...source,
      id: "hash_run_a_only_source",
      nodeKey: "hash_run_a_only_source",
      nodeHash: "hash_run_a_only_source",
      opNodeId: "source:run_a_only",
      title: "Run A only source",
      runs: ["run_a"],
    };
    const result = resolveNodeOperationContext({
      forest: {
        ...seed.forest,
        nodes: [...seed.forest.nodes, runAOnlySource],
        edges: [
          ...seed.forest.edges,
          {
            id: "hash_run_a_only_source->hash_shared_model",
            source: runAOnlySource.nodeKey,
            target: seed.sharedNodeKey,
          },
        ],
      },
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(
      result.context.lineage_context.upstream_path.map((node) => node.key),
    ).toEqual(["hash_source", seed.sharedNodeKey]);
  });

  it("fails closed when active-head resolution has no operation node id", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: {
        ...seed.forest,
        nodes: seed.forest.nodes.map((node) =>
          node.nodeKey === seed.sharedNodeKey ? { ...node, opNodeId: "" } : node,
        ),
      },
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("missing_op_node");
  });

  it("fails closed when single-candidate resolution has no operation node id", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: {
        ...seed.forest,
        nodes: seed.forest.nodes.map((node) =>
          node.nodeKey === seed.sharedNodeKey
            ? { ...node, opNodeId: "", runs: ["run_c"] }
            : node,
        ),
      },
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: null,
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("missing_op_node");
  });

  it("explain helper includes owner-resolution trace", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const trace = explainResolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
      selected_run_hint: "run_a",
      selected_run_hint_source: "run_scoped_surface",
    });
    expect(trace).toContain("selected forest node");
    expect(trace).toContain("selected_run_hint: run_a");
    expect(trace).toContain("selected_run_hint_source: run_scoped_surface");
    expect(trace).toContain("candidate_run_refs");
    expect(trace).toContain("selected_run_hint");
    expect(trace).toContain("context_fingerprint: nocv1:");
  });
});
