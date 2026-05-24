// frontend/src/lineage/detail/DetailDrawer.test.tsx
//
// T6.10 fleshes out the Inspector-equivalence table; this file currently
// covers T6.2 contract only (drawer chrome + section registry composition).
// Section visual tests live in each section's own test file.

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
    expect(screen.queryByTestId("decision-section-stub")).toBeNull();
  });

  it("node with decisions → all 4 sections render (DoD scenario)", () => {
    // Trust banner + lineage chain are real post-T6.4/T6.5; basic + decision
    // are still stubs until T6.6/T6.7 flesh them out.
    const node = makeNode({ trust: "review", decisions: [dp()] });
    renderDrawer(makeCtx(node));
    expect(screen.getByTestId("trust-banner-review-suggested")).toBeInTheDocument();
    expect(screen.getByTestId("lineage-chain-section")).toBeInTheDocument();
    expect(screen.getByTestId("basic-info-section")).toBeInTheDocument();
    expect(screen.getByTestId("decision-section-stub")).toBeInTheDocument();
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
          "[data-testid='decision-section-stub']," +
          "[data-testid='decision-section']",
      ),
    ).map((el) => el.getAttribute("data-testid"));
    expect(tids).toEqual([
      "trust-banner-review-suggested", // order 10
      "lineage-chain-section", // order 50
      "basic-info-section", // order 60 (still stub)
      "decision-section-stub", // order 70 (still stub)
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
});
