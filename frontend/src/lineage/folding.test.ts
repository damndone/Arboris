import { describe, it, expect } from "vitest";
import { foldNodeClusters } from "./folding";
import type { GraphViewNode } from "./api/graphViewTypes";

function v(
  id: string,
  kindAffix: "cleaned" | "dropped",
  parent: string,
): GraphViewNode {
  return {
    id: `var:${id}:${kindAffix}`,
    nodeKey: `var:${id}:${kindAffix}`,
    raw: null,
    kind: "variable",
    title: `${id} (${kindAffix})`,
    summary: undefined,
    parentStageId: parent,
    stage: "transform",
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-19T00:00:00Z",
  };
}

describe("foldNodeClusters", () => {
  it("does not fold when 3 or fewer variables per parent", () => {
    const nodes = [
      v("a", "cleaned", "stage:cleaned"),
      v("b", "cleaned", "stage:cleaned"),
      v("c", "cleaned", "stage:cleaned"),
    ];
    const { kept, groups } = foldNodeClusters(nodes, new Set());
    expect(kept.map((n) => n.id)).toEqual(nodes.map((n) => n.id));
    expect(groups).toEqual([]);
  });

  it("folds 4+ kept variables into one group node", () => {
    const nodes = [
      v("a", "cleaned", "stage:cleaned"),
      v("b", "cleaned", "stage:cleaned"),
      v("c", "cleaned", "stage:cleaned"),
      v("d", "cleaned", "stage:cleaned"),
    ];
    const { kept, groups } = foldNodeClusters(nodes, new Set());
    expect(kept.length).toBe(0);
    expect(groups.length).toBe(1);
    expect(groups[0].id).toBe("group:variables:stage:cleaned");
    expect(groups[0].display_label).toBe("Variables (4)");
    expect(groups[0].parentStageId).toBe("stage:cleaned");
  });

  it("folds dropped cluster separately from kept", () => {
    const nodes = [
      v("a", "cleaned", "stage:cleaned"),
      v("b", "cleaned", "stage:cleaned"),
      v("c", "cleaned", "stage:cleaned"),
      v("d", "cleaned", "stage:cleaned"),
      v("x", "dropped", "stage:cleaned"),
      v("y", "dropped", "stage:cleaned"),
      v("z", "dropped", "stage:cleaned"),
      v("w", "dropped", "stage:cleaned"),
    ];
    const { groups } = foldNodeClusters(nodes, new Set());
    expect(groups.length).toBe(2);
    const labels = groups.map((g) => g.display_label).sort();
    expect(labels).toEqual(["Dropped variables (4)", "Variables (4)"]);
  });

  it("expanded group ids return a contained expanded group with members", () => {
    const nodes = [
      v("a", "cleaned", "stage:cleaned"),
      v("b", "cleaned", "stage:cleaned"),
      v("c", "cleaned", "stage:cleaned"),
      v("d", "cleaned", "stage:cleaned"),
    ];
    const expanded = new Set(["group:variables:stage:cleaned"]);
    const { kept, groups } = foldNodeClusters(nodes, expanded);
    expect(kept.length).toBe(0);
    expect(groups.length).toBe(1);
    expect(groups[0].id).toBe("group:variables:stage:cleaned");
    expect(groups[0].expanded).toBe(true);
    expect(groups[0].members.map((n) => n.id)).toEqual(nodes.map((n) => n.id));
  });

  it("nodes whose kind ≠ 'variable' fall through to kept untouched", () => {
    const stage = {
      ...v("a", "cleaned", "stage:cleaned"),
      kind: "dataset_stage",
      id: "stage:cleaned",
    } as GraphViewNode;
    const { kept, groups } = foldNodeClusters([stage], new Set());
    expect(kept).toEqual([stage]);
    expect(groups).toEqual([]);
  });
});

// ── v1.7 G1: fold high fan-out data-operation children (projection only) ──

function castChild(key: string, parent: string, label = `Cast ${key}`): GraphViewNode {
  return {
    id: `hash::data-casts:${key}`,
    nodeKey: `hash::data-casts:${key}`,
    raw: { id: `data-casts:${key}` },
    kind: "dataset_stage",
    title: label,
    summary: "1 column cast",
    parentStageId: parent,
    stage: "transform",
    trust: "ok",
    decisions: [],
    createdAt: "2026-07-15T00:00:00Z",
  };
}

function codeChild(key: string, parent: string): GraphViewNode {
  return {
    id: `hash::code-exec:${key}`,
    nodeKey: `hash::code-exec:${key}`,
    raw: { id: `code-exec:${key}` },
    kind: "dataset_stage",
    title: "Run code",
    summary: "2 rows",
    parentStageId: parent,
    stage: "transform",
    trust: "ok",
    decisions: [],
    createdAt: "2026-07-15T00:00:00Z",
  };
}

describe("foldNodeClusters — data operation children (G1)", () => {
  it("folds code.execute children alongside casts — any data op can fan out", () => {
    const nodes = [
      castChild("a", "stage:cleaned"),
      castChild("b", "stage:cleaned"),
      codeChild("c", "stage:cleaned"),
      codeChild("d", "stage:cleaned"),
      codeChild("e", "stage:cleaned"),
    ];
    const { kept, groups } = foldNodeClusters(nodes, new Set());

    expect(groups).toHaveLength(1);
    expect(groups[0].display_label).toBe("Data operations (5)");
    expect(kept).toHaveLength(0);
  });

  it("does not fold 3 or fewer cast children", () => {
    const nodes = [
      castChild("a", "stage:cleaned"),
      castChild("b", "stage:cleaned"),
      castChild("c", "stage:cleaned"),
    ];
    const { kept, groups } = foldNodeClusters(nodes, new Set());
    expect(groups).toHaveLength(0);
    expect(kept).toHaveLength(3);
  });

  it("folds >3 same-parent cast children into one Data operations card", () => {
    const nodes = [
      castChild("a", "stage:cleaned"),
      castChild("b", "stage:cleaned"),
      castChild("c", "stage:cleaned"),
      castChild("d", "stage:cleaned"),
      castChild("e", "stage:cleaned"),
    ];
    const { kept, groups } = foldNodeClusters(nodes, new Set());

    expect(groups).toHaveLength(1);
    expect(groups[0].display_label).toBe("Data operations (5)");
    expect(groups[0].id).toBe("group:data-operations:stage:cleaned");
    expect(groups[0].variant).toBe("data_operation");
    expect(groups[0].expanded).toBe(false);
    // every child stays individually reachable through the group
    expect(groups[0].member_ids).toHaveLength(5);
    expect(kept).toHaveLength(0);
  });

  it("buckets cast children per parent and matches the singular data-cast prefix", () => {
    const singular: GraphViewNode = {
      ...castChild("s1", "stage:other"),
      id: "hash::data-cast:s1",
      nodeKey: "hash::data-cast:s1",
      raw: { id: "data-cast:s1" },
    };
    const nodes = [
      castChild("a", "stage:cleaned"),
      castChild("b", "stage:cleaned"),
      castChild("c", "stage:cleaned"),
      castChild("d", "stage:cleaned"),
      singular,
    ];
    const { kept, groups } = foldNodeClusters(nodes, new Set());

    expect(groups).toHaveLength(1);
    expect(groups[0].parentStageId).toBe("stage:cleaned");
    // the lone child under a different parent is not folded
    expect(kept.map((n) => n.nodeKey)).toEqual(["hash::data-cast:s1"]);
  });

  it("expands a data operations group when requested", () => {
    const nodes = ["a", "b", "c", "d"].map((k) => castChild(k, "stage:cleaned"));
    const expanded = new Set(["group:data-operations:stage:cleaned"]);
    const { groups } = foldNodeClusters(nodes, expanded);
    expect(groups[0].expanded).toBe(true);
  });

  it("leaves ordinary dataset nodes (the source itself) unfolded", () => {
    const source: GraphViewNode = {
      id: "hash::stage:cleaned",
      nodeKey: "hash::stage:cleaned",
      raw: { id: "stage:cleaned" },
      kind: "dataset_stage",
      title: "Cleaned data",
      parentStageId: "stage:raw",
      stage: "clean",
      trust: "ok",
      decisions: [],
    };
    const { kept, groups } = foldNodeClusters([source], new Set());
    expect(groups).toHaveLength(0);
    expect(kept).toHaveLength(1);
  });
});
