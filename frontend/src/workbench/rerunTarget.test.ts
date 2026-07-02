import { describe, it, expect } from "vitest";
import { pickRerunTargetKey } from "./rerunTarget";
import type { GraphViewModel, GraphViewNode } from "../lineage/api/graphViewTypes";

function n(nodeKey: string, kind: string, stage: string): GraphViewNode {
  return {
    id: nodeKey,
    nodeKey,
    raw: null,
    stage: stage as GraphViewNode["stage"],
    kind,
    title: nodeKey,
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

function model(nodes: GraphViewNode[]): GraphViewModel {
  return {
    schemaVersion: 1,
    runId: "r1",
    legacy: false,
    nodes,
    edges: [],
    stats: {} as GraphViewModel["stats"],
  };
}

describe("pickRerunTargetKey", () => {
  it("targets the primary (terminal) model node, ignoring the selection", () => {
    const m = model([
      n("src", "dataset_stage", "source"),
      n("clean", "dataset_stage", "clean"),
      n("model:ols_1", "model", "model"),
    ]);
    // Even with a non-model node selected, Rerun goes to the model node.
    expect(pickRerunTargetKey(m, "clean")).toBe("model:ols_1");
    expect(pickRerunTargetKey(m, null)).toBe("model:ols_1");
  });

  it("uses stage=model when kind is not literally 'model'", () => {
    const m = model([n("src", "dataset_stage", "source"), n("mnode", "estimator", "model")]);
    expect(pickRerunTargetKey(m, null)).toBe("mnode");
  });

  it("falls back to the selected node when there is no model node", () => {
    const m = model([n("src", "dataset_stage", "source"), n("clean", "dataset_stage", "clean")]);
    expect(pickRerunTargetKey(m, "clean")).toBe("clean");
  });

  it("falls back to the first node when nothing is selected and no model exists", () => {
    const m = model([n("src", "dataset_stage", "source")]);
    expect(pickRerunTargetKey(m, null)).toBe("src");
  });

  it("returns null for an empty graph", () => {
    expect(pickRerunTargetKey(model([]), null)).toBeNull();
  });
});
