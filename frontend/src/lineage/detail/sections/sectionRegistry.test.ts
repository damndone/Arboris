// frontend/src/lineage/detail/sections/sectionRegistry.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  _needsTrust,
  sectionRegistry,
} from "./sectionRegistry";
import { TrustBanner } from "./TrustBanner";
import { LineageChainSection } from "./LineageChainSection";
import { BasicInfoSection } from "./BasicInfoSection";
import { DecisionSection } from "./DecisionSection";
import { CompareWithSourceSection } from "./CompareWithSourceSection";
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
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("exposes the V1.6.3 section set with source compare near operation", () => {
    expect(sectionRegistry.map((s) => s.id)).toEqual([
      "draftEditor",
      "trust",
      "askAi",
      "compareWithSource",
      "compareNodes",
      "operation",
      "estimatedEquation",
      "roleGroups",
      "code",
      "lineage",
      "basic",
      "decision",
    ]);
  });

  it("orders keep source compare between Ask AI and Operation", () => {
    expect(sectionRegistry.map((s) => s.order)).toEqual([
      5, 10, 20, 25, 26, 30, 34, 35, 40, 50, 60, 70,
    ]);
  });

  it(".filter(s => s.shouldRender(node)) on a plain model node yields roleGroups/lineage/basic by default", () => {
    // ok trust + no decisions + no code + no editableSchema → lineage
    // + basic render. roleGroups renders for model nodes (v1.6.5). Ask AI
    // is feature-flagged off by default.
    const plain = node();
    const visible = sectionRegistry.filter((s) => s.shouldRender(plain));
    expect(visible.map((s) => s.id)).toEqual([
      "estimatedEquation",
      "roleGroups",
      "lineage",
      "basic",
    ]);
  });

  it("compareWithSource renders only for forest nodes with run ownership metadata", () => {
    const entry = sectionRegistry.find((s) => s.id === "compareWithSource")!;
    expect(entry.shouldRender(node())).toBe(false);
    expect(entry.shouldRender(node({ runs: ["run_child"] } as Partial<GraphViewNode>))).toBe(true);
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

  it("Component refs match the imported section components [REV-2 #5]", () => {
    // Locks the wiring: registry[i].Component must point at the actual
    // exported component, not a stub or a wrong reference. Drift here
    // means the drawer would render the wrong section.
    const byId = Object.fromEntries(sectionRegistry.map((s) => [s.id, s]));
    expect(byId.trust.Component).toBe(TrustBanner);
    expect(byId.compareWithSource.Component).toBe(CompareWithSourceSection);
    expect(byId.lineage.Component).toBe(LineageChainSection);
    expect(byId.basic.Component).toBe(BasicInfoSection);
    expect(byId.decision.Component).toBe(DecisionSection);
  });

  describe("V1.5.2 P5 placeholders", () => {
    it("askAi is hidden by default", () => {
      const visible = sectionRegistry
        .filter((s) => s.shouldRender(node()))
        .map((s) => s.id);
      expect(visible).not.toContain("askAi");
    });

    it("askAi renders only when VITE_WORKBENCH_ASK_AI is enabled", () => {
      vi.stubEnv("VITE_WORKBENCH_ASK_AI", "1");
      const visible = sectionRegistry
        .filter((s) => s.shouldRender(node()))
        .map((s) => s.id);
      expect(visible).toContain("askAi");
    });

    it("operation renders only when editableSchema is non-empty", () => {
      const withoutSchema = sectionRegistry.find((s) => s.id === "operation")!;
      expect(withoutSchema.shouldRender(node())).toBe(false);
      expect(
        withoutSchema.shouldRender(
          node({
            editableSchema: [
              { kind: "toggle", key: "log_transform", label: "log" },
            ],
          }),
        ),
      ).toBe(true);
    });

    it("code renders only when node.code.body is present", () => {
      const codeEntry = sectionRegistry.find((s) => s.id === "code")!;
      expect(codeEntry.shouldRender(node())).toBe(false);
      expect(
        codeEntry.shouldRender(
          node({ code: { lang: "python", body: "x = 1" } }),
        ),
      ).toBe(true);
      // Empty body counts as absent.
      expect(
        codeEntry.shouldRender(node({ code: { lang: "python", body: "" } })),
      ).toBe(false);
    });
  });

  describe("needsTrust — non-needed/failed review statuses suppress banner [REV-2 #6]", () => {
    it.each(["passed", "waived", "unknown", "not_needed"] as const)(
      "trust=ok + DP.reviewStatus=%s → false",
      (status) => {
        expect(
          _needsTrust(
            node({ trust: "ok", decisions: [dp({ reviewStatus: status })] }),
          ),
        ).toBe(false);
      },
    );
  });
});
