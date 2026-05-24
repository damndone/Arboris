import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { ReactFlowProvider } from "reactflow";
import { GraphNode } from "./GraphNode";
import type {
  DecisionReviewStatus,
  DecisionViewModel,
  GraphViewNode,
  Stage,
  Trust,
} from "../api/graphViewTypes";

// GraphNode uses React Flow <Handle>, which requires ReactFlowProvider in tree.
function render(ui: ReactElement) {
  return rtlRender(<ReactFlowProvider>{ui}</ReactFlowProvider>);
}

function vn(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    summary: "OLS · HC1 · n = 32",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    ...overrides,
  };
}

function vd(reviewStatus: DecisionReviewStatus = "needed"): DecisionViewModel {
  return {
    id: "d1",
    question: "Model type",
    picked: "OLS",
    alternatives: [],
    why: "",
    evidence: [],
    reviewStatus,
  };
}

describe("GraphNode (T8.3 visual refresh)", () => {
  it("renders kind label, title, and summary", () => {
    render(<GraphNode data={{ node: vn() }} selected={false} />);
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText("OLS · HC1 · n = 32")).toBeInTheDocument();
    expect(screen.getByText("model")).toBeInTheDocument();
  });

  it("hides meta line when summary is undefined", () => {
    render(<GraphNode data={{ node: vn({ summary: undefined }) }} selected={false} />);
    expect(screen.queryByTestId("node-summary")).toBeNull();
  });

  it("shows no badge when trust=ok and no review needed", () => {
    render(<GraphNode data={{ node: vn() }} selected={false} />);
    expect(screen.queryByTestId("node-badge")).toBeNull();
  });

  it("shows review badge when trust=review", () => {
    render(<GraphNode data={{ node: vn({ trust: "review" }) }} selected={false} />);
    const badge = screen.getByTestId("node-badge");
    expect(badge).toHaveTextContent("Review");
    expect(badge.className).toContain("ln-graph-node__badge--review");
  });

  it("shows review badge when any decision needs review (even if trust=ok)", () => {
    render(
      <GraphNode
        data={{ node: vn({ decisions: [vd("needed")] }) }}
        selected={false}
      />,
    );
    const badge = screen.getByTestId("node-badge");
    expect(badge).toHaveTextContent("Review");
  });

  it("shows review badge when any decision failed review (even if trust=ok)", () => {
    render(
      <GraphNode
        data={{ node: vn({ decisions: [vd("failed")] }) }}
        selected={false}
      />,
    );
    expect(screen.getByTestId("node-badge")).toHaveTextContent("Review");
  });

  it("shows caution badge when trust=caution (takes priority over review)", () => {
    render(
      <GraphNode
        data={{ node: vn({ trust: "caution", decisions: [vd("needed")] }) }}
        selected={false}
      />,
    );
    const badge = screen.getByTestId("node-badge");
    expect(badge).toHaveTextContent("Caution");
    expect(badge.className).toContain("ln-graph-node__badge--caution");
  });

  // REV-2: non-triggering decision states must not surface a badge when
  // trust=ok. Otherwise we'd over-flag nodes whose DPs are already cleared.
  const benign: DecisionReviewStatus[] = [
    "passed",
    "not_needed",
    "waived",
    "unknown",
  ];
  for (const status of benign) {
    it(`shows no badge when trust=ok and decision.reviewStatus=${status}`, () => {
      render(
        <GraphNode
          data={{ node: vn({ decisions: [vd(status)] }) }}
          selected={false}
        />,
      );
      expect(screen.queryByTestId("node-badge")).toBeNull();
    });
  }

  it("shows review badge when trust=review even with no decisions [REV-2]", () => {
    render(
      <GraphNode
        data={{ node: vn({ trust: "review", decisions: [] }) }}
        selected={false}
      />,
    );
    expect(screen.getByTestId("node-badge")).toHaveTextContent("Review");
  });

  it("applies selected outline class when selected", () => {
    render(<GraphNode data={{ node: vn() }} selected={true} />);
    expect(screen.getByTestId("graph-node").className).toContain(
      "ln-graph-node--selected",
    );
  });

  describe("stage × trust matrix (DoD T8.3)", () => {
    const stages: Stage[] = [
      "source",
      "eda",
      "clean",
      "transform",
      "model",
      "diag",
      "viz",
      "report",
    ];
    const trusts: Trust[] = ["ok", "review", "caution"];

    for (const stage of stages) {
      for (const trust of trusts) {
        it(`renders stage=${stage} trust=${trust} without crashing`, () => {
          render(
            <GraphNode data={{ node: vn({ stage, trust }) }} selected={false} />,
          );
          const node = screen.getByTestId("graph-node");
          expect(node).toHaveAttribute("data-stage", stage);
          expect(node).toHaveAttribute("data-trust", trust);
          // Bar uses a CSS var (via --node-color); verify the inline style sets it.
          expect(node.style.getPropertyValue("--node-color")).toBe(
            `var(--stage-${stage})`,
          );
        });
      }
    }

    it("stage=unknown falls back to neutral --label-tertiary (not a stage token)", () => {
      render(
        <GraphNode
          data={{ node: vn({ stage: "unknown" }) }}
          selected={false}
        />,
      );
      const node = screen.getByTestId("graph-node");
      expect(node.style.getPropertyValue("--node-color")).toBe(
        "var(--label-tertiary)",
      );
    });
  });
});
