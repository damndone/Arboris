// frontend/src/lineage/detail/sections/sectionRegistry.test.ts
import { describe, expect, it } from "vitest";
import {
  _needsTrust,
  sectionRegistry,
} from "./sectionRegistry";
import type {
  DecisionViewModel,
  GraphViewNode,
} from "../../api/graphViewTypes";

function dp(overrides: Partial<DecisionViewModel> = {}): DecisionViewModel {
  return {
    id: "model_type_auto_select",
    question: "Which model type?",
    picked: "ols",
    alternatives: ["ols", "logit"],
    why: "y is continuous",
    evidence: [],
    reviewStatus: "not_needed",
    ...overrides,
  };
}

function node(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

describe("sectionRegistry", () => {
  it("exposes exactly the 4 V1.5.0 sections (trust/lineage/basic/decision)", () => {
    expect(sectionRegistry.map((s) => s.id)).toEqual([
      "trust",
      "lineage",
      "basic",
      "decision",
    ]);
  });

  it("orders match spec §8.1: 10/50/60/70", () => {
    expect(sectionRegistry.map((s) => s.order)).toEqual([10, 50, 60, 70]);
  });

  it(".filter(s => s.shouldRender(node)) works on a ViewModel fixture", () => {
    // ok trust + no decisions → only lineage + basic render
    const plain = node();
    const visible = sectionRegistry.filter((s) => s.shouldRender(plain));
    expect(visible.map((s) => s.id)).toEqual(["lineage", "basic"]);
  });

  it("decision section renders when decisions.length > 0", () => {
    const n = node({ decisions: [dp()] });
    const ids = sectionRegistry.filter((s) => s.shouldRender(n)).map((s) => s.id);
    expect(ids).toContain("decision");
  });

  it("decision section does NOT render when decisions empty", () => {
    const ids = sectionRegistry
      .filter((s) => s.shouldRender(node({ decisions: [] })))
      .map((s) => s.id);
    expect(ids).not.toContain("decision");
  });

  describe("needsTrust", () => {
    it("trust=ok + all DPs not_needed → false", () => {
      expect(_needsTrust(node({ trust: "ok", decisions: [dp()] }))).toBe(false);
    });

    it("trust=review → true", () => {
      expect(_needsTrust(node({ trust: "review" }))).toBe(true);
    });

    it("trust=caution → true", () => {
      expect(_needsTrust(node({ trust: "caution" }))).toBe(true);
    });

    it("trust=ok but a DP has reviewStatus=needed → true", () => {
      expect(
        _needsTrust(
          node({
            trust: "ok",
            decisions: [dp({ reviewStatus: "needed" })],
          }),
        ),
      ).toBe(true);
    });

    it("trust=ok but a DP has reviewStatus=failed → true", () => {
      expect(
        _needsTrust(
          node({
            trust: "ok",
            decisions: [dp({ reviewStatus: "failed" })],
          }),
        ),
      ).toBe(true);
    });
  });

  it("orders are unique (no slot collisions)", () => {
    const orders = sectionRegistry.map((s) => s.order);
    expect(new Set(orders).size).toBe(orders.length);
  });

  it("orders are monotonically increasing as authored (catches accidental reordering)", () => {
    const sorted = [...sectionRegistry].sort((a, b) => a.order - b.order);
    expect(sorted.map((s) => s.id)).toEqual(sectionRegistry.map((s) => s.id));
  });
});
