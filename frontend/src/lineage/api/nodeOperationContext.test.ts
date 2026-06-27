import { describe, expect, it } from "vitest";
import {
  explainResolveNodeOperationContext,
  makeOwnerResolutionSeedFixture,
  resolveNodeOperationContext,
} from "./nodeOperationContext";

describe("resolveNodeOperationContext", () => {
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

  it("explain helper includes owner-resolution trace", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const trace = explainResolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    expect(trace).toContain("selected forest node");
    expect(trace).toContain("candidate_run_refs");
    expect(trace).toContain("active_head_contains_node");
  });
});
