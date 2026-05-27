// frontend/src/workbench/RunSnapshotAdapter.test.ts
//
// V1.5.2 — locks the index / walk semantics of RunSnapshotAdapter.
//
// Walks share their tiebreaker (lex-smallest neighbour) and depth cap
// (MAX_HOPS=100) with the existing pathBuilder; the tests assert the
// same behaviour. If pathBuilder changes, this file changes — and
// vice-versa.

import { describe, expect, it } from "vitest";
import { buildRunSnapshot } from "./RunSnapshotAdapter";
import type {
  GraphViewEdge,
  GraphViewModel,
  GraphViewNode,
  Stage,
} from "../lineage/api/graphViewTypes";

function n(
  id: string,
  overrides: Partial<GraphViewNode> = {},
): GraphViewNode {
  return {
    id,
    nodeKey: id,
    raw: null,
    stage: (overrides.stage ?? "transform") as Stage,
    kind: overrides.kind ?? "transform",
    title: overrides.title ?? id,
    parentStageId: overrides.parentStageId ?? null,
    trust: overrides.trust ?? "ok",
    decisions: overrides.decisions ?? [],
    ...overrides,
  };
}

function e(source: string, target: string): GraphViewEdge {
  return { id: `${source}->${target}`, source, target };
}

function model(
  nodes: GraphViewNode[],
  edges: GraphViewEdge[],
): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "r1",
    legacy: false,
    nodes,
    edges,
    stats: {
      nodeCount: nodes.length,
      edgeCount: edges.length,
      leafCount: 0,
      hasDpCount: 0,
    },
  };
}

describe("buildRunSnapshot", () => {
  describe("nodeByKey", () => {
    it("indexes every node by nodeKey", () => {
      const snap = buildRunSnapshot(
        model([n("a"), n("b"), n("c")], []),
      );
      expect(snap.nodeByKey.get("a")?.id).toBe("a");
      expect(snap.nodeByKey.get("c")?.id).toBe("c");
      expect(snap.nodeByKey.size).toBe(3);
    });
  });

  describe("nodesByStage", () => {
    it("groups by stage, preserving insertion order", () => {
      const snap = buildRunSnapshot(
        model(
          [
            n("a", { stage: "model" }),
            n("b", { stage: "clean" }),
            n("c", { stage: "model" }),
          ],
          [],
        ),
      );
      expect(snap.nodesByStage.get("model")?.map((x) => x.id)).toEqual([
        "a",
        "c",
      ]);
      expect(snap.nodesByStage.get("clean")?.map((x) => x.id)).toEqual([
        "b",
      ]);
    });
  });

  describe("variables / models", () => {
    it("picks variables via kind=variable or kind ending in _var", () => {
      const snap = buildRunSnapshot(
        model(
          [
            n("v1", { kind: "variable" }),
            n("v2", { kind: "income_var" }),
            n("v3", { kind: "transform" }),
          ],
          [],
        ),
      );
      expect(snap.variables.map((x) => x.id)).toEqual(["v1", "v2"]);
    });

    it("picks models via kind=model or stage=model", () => {
      const snap = buildRunSnapshot(
        model(
          [
            n("m1", { kind: "model" }),
            n("m2", { stage: "model", kind: "ols_model" }),
            n("o", { stage: "clean", kind: "transform" }),
          ],
          [],
        ),
      );
      expect(snap.models.map((x) => x.id)).toEqual(["m1", "m2"]);
    });
  });

  describe("upstreamOf", () => {
    it("walks ancestors and excludes the start node", () => {
      // a → b → c → d
      const snap = buildRunSnapshot(
        model(
          [n("a"), n("b"), n("c"), n("d")],
          [e("a", "b"), e("b", "c"), e("c", "d")],
        ),
      );
      expect(snap.upstreamOf("d").map((x) => x.id)).toEqual([
        "c",
        "b",
        "a",
      ]);
    });

    it("returns [] for unknown start key", () => {
      const snap = buildRunSnapshot(model([n("a")], []));
      expect(snap.upstreamOf("nope")).toEqual([]);
    });

    it("deduplicates diamonds", () => {
      //   a
      //  / \
      // b   c
      //  \ /
      //   d
      const snap = buildRunSnapshot(
        model(
          [n("a"), n("b"), n("c"), n("d")],
          [e("a", "b"), e("a", "c"), e("b", "d"), e("c", "d")],
        ),
      );
      const ids = snap.upstreamOf("d").map((x) => x.id);
      // a appears once even though both b and c link to it.
      expect(new Set(ids).size).toBe(ids.length);
      expect(ids).toContain("a");
      expect(ids).toContain("b");
      expect(ids).toContain("c");
    });
  });

  describe("downstreamOf", () => {
    it("walks descendants and excludes the start node", () => {
      const snap = buildRunSnapshot(
        model(
          [n("a"), n("b"), n("c")],
          [e("a", "b"), e("b", "c")],
        ),
      );
      expect(snap.downstreamOf("a").map((x) => x.id)).toEqual(["b", "c"]);
    });
  });

  describe("lineagePathTo", () => {
    it("returns ancestors earliest-first, target last", () => {
      const snap = buildRunSnapshot(
        model(
          [n("a"), n("b"), n("c"), n("d")],
          [e("a", "b"), e("b", "c"), e("c", "d")],
        ),
      );
      expect(snap.lineagePathTo("d").map((x) => x.id)).toEqual([
        "a",
        "b",
        "c",
        "d",
      ]);
    });

    it("returns [] for unknown node", () => {
      const snap = buildRunSnapshot(model([n("a")], []));
      expect(snap.lineagePathTo("nope")).toEqual([]);
    });

    it("returns [target] for a node with no parents", () => {
      const snap = buildRunSnapshot(model([n("a")], []));
      expect(snap.lineagePathTo("a").map((x) => x.id)).toEqual(["a"]);
    });
  });

  describe("searchIndex", () => {
    it("emits a node entry per node", () => {
      const snap = buildRunSnapshot(
        model([n("a", { title: "Alpha" })], []),
      );
      const node = snap.searchIndex.filter((it) => it.kind === "node");
      expect(node.map((it) => it.label)).toEqual(["Alpha"]);
    });

    it("emits a variable entry when kind matches", () => {
      const snap = buildRunSnapshot(
        model(
          [n("v", { kind: "income_var", title: "income" })],
          [],
        ),
      );
      const vars = snap.searchIndex.filter((it) => it.kind === "variable");
      expect(vars.map((it) => it.nodeKey)).toEqual(["v"]);
    });

    it("emits a decision entry per decision with nodeKey + detail", () => {
      const snap = buildRunSnapshot(
        model(
          [
            n("m", {
              kind: "model",
              title: "Primary",
              decisions: [
                {
                  id: "model_type_auto_select",
                  question: "Which model type?",
                  picked: "ols",
                  alternatives: ["ols", "logit"],
                  why: "y is continuous",
                  evidence: [],
                  reviewStatus: "not_needed",
                },
              ],
            }),
          ],
          [],
        ),
      );
      const dec = snap.searchIndex.filter((it) => it.kind === "decision");
      expect(dec).toHaveLength(1);
      expect(dec[0].nodeKey).toBe("m");
      expect(dec[0].detail).toBe("model_type_auto_select");
      expect(dec[0].haystack).toContain("ols");
    });
  });
});
