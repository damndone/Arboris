// frontend/src/lineage/detail/DetailDrawer.test.tsx
//
// T6.10 equivalence map (plan §9 + §15.1): every V1.4.1 Inspector.test.tsx
// scenario is reproduced in the V1.5.0 structure. The new structure
// distributes assertions across the unit that owns the behavior; this
// drawer-level file holds composition + integration tests only.
//
// ┌─────────────────────────────────────────────┬─────────────────────────────────────────────┐
// │ V1.4.1 Inspector.test.tsx                   │ V1.5.0 location                             │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ "renders title and eyebrow"                 │ DetailHeader.test "title <h2> carries       │
// │                                             │ DETAIL_HEADER_TITLE_ID" + "kind label"      │
// │                                             │ + "breadcrumb shows runId · nodeKey"        │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ "renders About prose for MODEL kind"        │ DetailHeader.test "summary line renders     │
// │                                             │ when node.summary is set"                   │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ 'renders green "All clear" callout when     │ sectionRegistry.test "ok trust + no DPs →   │
// │  no review needed and trust ok'             │ only lineage+basic" + this file's           │
// │                                             │ "ok-trust no DPs → only basic+lineage"      │
// │                                             │ (no trust banner = "all clear" by absence)  │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ 'renders orange "Review required" when      │ TrustBanner.test "review-required wins"     │
// │  DPs need review'                           │ + "multi-DP pluralises" + "body uses        │
// │                                             │ dpRegistry-derived title"                   │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ "renders red trust callout when             │ TrustBanner.test "trust=caution → 'Caution' │
// │  trust=warning and no DP"                   │ variant" + "trustReason used as body".      │
// │                                             │ NOTE: V1.5.0 adapter normalises warning →   │
// │                                             │ review (orange); caution/blocker → caution  │
// │                                             │ (red). The red callout case is now caution. │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ "calls onClose when close button clicked"   │ DetailHeader.test "close button has         │
// │                                             │ aria-label=Close and fires onClose"         │
// ├─────────────────────────────────────────────┼─────────────────────────────────────────────┤
// │ "has role=dialog and aria-labelledby"       │ This file: "renders role=dialog with        │
// │                                             │ aria-labelledby pointing at the header h2"  │
// └─────────────────────────────────────────────┴─────────────────────────────────────────────┘
//
// Section-system tests (NEW in V1.5.0, no V1.4.1 equivalent):
//   - "ok-trust node with no DPs → only basic + lineage sections"
//   - "node with decisions → all 4 sections render (DoD scenario)"
//   - "sections render in registry `order` regardless of array position"
//   - "explicit node prop wins over context selection"
//   - "renders nothing when context yields no node / orphan selectedKey"
//   - "full integration: trust + lineage + basic + decision sections
//      mount together with realistic content" (T6.10 — this file)

import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DetailDrawer } from "./DetailDrawer";
import { LineageContext, type LineageContextValue } from "../LineageContext";
import type {
  DecisionViewModel,
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";

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

function makeNode(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    summary: "OLS · n=10",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

function makeCtx(
  node: GraphViewNode | null,
  selectedKey: string | null = node?.id ?? null,
): LineageContextValue {
  const model: GraphViewModel = {
    schemaVersion: 3,
    runId: "run-1",
    legacy: false,
    nodes: node ? [node] : [],
    edges: [],
    stats: { nodeCount: node ? 1 : 0, edgeCount: 0, leafCount: 0, hasDpCount: 0 },
  };
  return { model, selectedKey, select: vi.fn() };
}

function renderDrawer(
  ctx: LineageContextValue,
  props: { node?: GraphViewNode; onClose?: () => void } = {},
) {
  return render(
    <LineageContext.Provider value={ctx}>
      <DetailDrawer node={props.node} onClose={props.onClose ?? vi.fn()} />
    </LineageContext.Provider>,
  );
}

describe("DetailDrawer", () => {
  it("renders role=dialog with aria-labelledby pointing at the header h2", () => {
    const node = makeNode();
    renderDrawer(makeCtx(node));
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-labelledby")).toBe("detail-drawer-title");
    expect(document.getElementById("detail-drawer-title")).not.toBeNull();
  });

  it("ok-trust node with no DPs → only basic + lineage sections (no trust, no decision)", () => {
    renderDrawer(makeCtx(makeNode()));
    expect(screen.getByTestId("basic-info-section")).toBeInTheDocument();
    expect(screen.getByTestId("lineage-chain-section")).toBeInTheDocument();
    expect(screen.queryByTestId("trust-banner-review-suggested")).toBeNull();
    expect(screen.queryByTestId("trust-banner-caution")).toBeNull();
    expect(screen.queryByTestId("decision-section")).toBeNull();
  });

  it("node with decisions → all 4 sections render (DoD scenario)", () => {
    // Trust banner + lineage chain are real post-T6.4/T6.5; basic + decision
    // are still stubs until T6.6/T6.7 flesh them out.
    const node = makeNode({ trust: "review", decisions: [dp()] });
    renderDrawer(makeCtx(node));
    expect(screen.getByTestId("trust-banner-review-suggested")).toBeInTheDocument();
    expect(screen.getByTestId("lineage-chain-section")).toBeInTheDocument();
    expect(screen.getByTestId("basic-info-section")).toBeInTheDocument();
    expect(screen.getByTestId("decision-section")).toBeInTheDocument();
  });

  it("sections render in registry `order` regardless of array position", () => {
    const node = makeNode({ trust: "review", decisions: [dp()] });
    const { container } = renderDrawer(makeCtx(node));
    // Collect by id-prefix patterns so this test survives stubs being
    // replaced by real components across T6.5–T6.7. Each section is
    // identified by its testid pattern.
    const tids = Array.from(
      container.querySelectorAll(
        "[data-testid^='trust-banner-']," +
          "[data-testid='lineage-chain-section']," +
          "[data-testid='basic-info-section']," +
          "[data-testid='basic-info-section']," +
          "[data-testid='decision-section']," +
          "[data-testid='decision-section']",
      ),
    ).map((el) => el.getAttribute("data-testid"));
    expect(tids).toEqual([
      "trust-banner-review-suggested", // order 10
      "lineage-chain-section", // order 50
      "basic-info-section", // order 60 (still stub)
      "decision-section", // order 70 (still stub)
    ]);
  });

  it("resolves node from selectedKey in context when no prop is passed", () => {
    const node = makeNode();
    renderDrawer(makeCtx(node, "n1"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders nothing when neither prop nor context yields a node", () => {
    const { container } = renderDrawer(makeCtx(null, null));
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when selectedKey points at a missing node", () => {
    // Cross-run leak guard at the drawer level (workbench also guards this).
    const node = makeNode();
    const { container } = renderDrawer(makeCtx(node, "n-ghost"));
    expect(container.firstChild).toBeNull();
  });

  it("explicit node prop wins over context selection", () => {
    const ctxNode = makeNode({ id: "ctx-node", title: "From context" });
    const propNode = makeNode({ id: "prop-node", title: "From prop" });
    renderDrawer(makeCtx(ctxNode, "ctx-node"), { node: propNode });
    expect(screen.getByText("From prop")).toBeInTheDocument();
    expect(screen.queryByText("From context")).toBeNull();
  });

  it("integration: trust + lineage + basic + decision sections all mount together (T6.10)", () => {
    // End-to-end check that the four real sections + the header chrome
    // co-exist without conflicting. Uses a node that triggers all four
    // gates simultaneously.
    const decisions = [
      dp({
        id: "model_type_auto_select",
        question: "Which model type?",
        reviewStatus: "needed",
      }),
      dp({
        id: "ols_default_robust_se",
        question: "Robust SE?",
        reviewStatus: "not_needed",
      }),
    ];
    const fullNode = makeNode({
      title: "Primary OLS",
      summary: "OLS · HC1 · n=10",
      trust: "review",
      decisions,
    });
    renderDrawer(makeCtx(fullNode));

    // Header chrome
    expect(document.getElementById("detail-drawer-title")).not.toBeNull();
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText(/OLS · HC1 · n=10/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    // Trust banner — review-required wins over trust=review (TrustBanner contract)
    expect(
      screen.getByTestId("trust-banner-review-required"),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 choice needs confirmation/i)).toBeInTheDocument();
    // Lineage chain (heading)
    expect(screen.getByText("Lineage path")).toBeInTheDocument();
    // Basic info K/V (3 rows)
    expect(screen.getByTestId("basic-info-kind").textContent).toBe("model");
    expect(screen.getByTestId("basic-info-stage").textContent).toBe("Model");
    expect(screen.getByTestId("basic-info-created").textContent).toBe(
      new Date("2026-05-22T00:00:00Z").toLocaleString(),
    );
    // Decision section heading with count
    expect(screen.getByText("Decisions (2)")).toBeInTheDocument();
  });
});
