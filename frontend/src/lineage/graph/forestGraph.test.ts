import { describe, it, expect } from "vitest";
import { tracePath, headActiveSet, parentMap } from "./forestGraph";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";

function node(id: string, runs: string[]): HeadSetNode {
  return {
    id, nodeKey: id, opNodeId: id, raw: {}, stage: "clean", kind: "k", title: id,
    parentStageId: null, trust: "ok", decisions: [], nodeHash: id,
    producingStage: null, casRef: null, runs,
  };
}

function forest(): ForestViewModel {
  return {
    schemaVersion: 4,
    legacy: false,
    nodes: [
      node("raw", ["a", "b"]),
      node("C", ["a", "b"]),
      node("M1", ["a"]),
      node("M2", ["b"]),
    ],
    edges: [
      { id: "raw->C", source: "raw", target: "C" },
      { id: "C->M1", source: "C", target: "M1" },
      { id: "C->M2", source: "C", target: "M2" },
    ],
    heads: [],
  };
}

describe("forestGraph", () => {
  it("parentMap maps targets to their sources", () => {
    const pm = parentMap(forest().edges);
    expect(pm.get("C")).toEqual(["raw"]);
    expect(pm.get("M2")).toEqual(["C"]);
    expect(pm.get("raw")).toBeUndefined();
  });

  it("tracePath returns root → node inclusive", () => {
    expect(tracePath(forest(), "M2")).toEqual(["raw", "C", "M2"]);
    expect(tracePath(forest(), "raw")).toEqual(["raw"]);
  });

  it("headActiveSet returns the run's node keys (shared prefix included)", () => {
    expect(headActiveSet(forest(), "a")).toEqual(new Set(["raw", "C", "M1"]));
    expect(headActiveSet(forest(), "b")).toEqual(new Set(["raw", "C", "M2"]));
  });

  it("tracePath is cycle-guarded", () => {
    const f = forest();
    f.edges.push({ id: "M2->C", source: "M2", target: "C" }); // inject a cycle
    expect(() => tracePath(f, "M2")).not.toThrow();
  });
});
