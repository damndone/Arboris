import { describe, it, expect } from "vitest";
import { foldVariableClusters } from "./folding";
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

describe("foldVariableClusters", () => {
  it("does not fold when 3 or fewer variables per parent", () => {
    const nodes = [
      v("a", "cleaned", "stage:cleaned"),
      v("b", "cleaned", "stage:cleaned"),
      v("c", "cleaned", "stage:cleaned"),
    ];
    const { kept, groups } = foldVariableClusters(nodes, new Set());
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
    const { kept, groups } = foldVariableClusters(nodes, new Set());
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
    const { groups } = foldVariableClusters(nodes, new Set());
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
    const { kept, groups } = foldVariableClusters(nodes, expanded);
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
    const { kept, groups } = foldVariableClusters([stage], new Set());
    expect(kept).toEqual([stage]);
    expect(groups).toEqual([]);
  });
});
