import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { ReactFlowProvider } from "reactflow";
import { GraphNode, type GraphNodeState } from "./GraphNode";
import type { Role } from "../roles";
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

// Helper: render GraphNode with state defaulted to "related" (the
// no-selection default) and the React Flow `selected` prop derived from
// state, so test sites only have to specify what they're actually
// testing (the node + optional tri-state).
function mountNode(
  node: GraphViewNode,
  state: GraphNodeState = "related",
  extra: Partial<{ role: Role; rolesTag: string }> = {},
): void {
  render(
    <GraphNode
      data={{ node, state, ...extra }}
      selected={state === "selected"}
    />,
  );
}

describe("GraphNode (T8.3 visual refresh + T8.5 tri-state)", () => {
  it("renders kind label, title, and summary", () => {
    mountNode(vn());
    expect(screen.getByText("Primary OLS")).toBeInTheDocument();
    expect(screen.getByText("OLS · HC1 · n = 32")).toBeInTheDocument();
    expect(screen.getByText("model")).toBeInTheDocument();
  });

  it("hides meta line when summary is undefined", () => {
    mountNode(vn({ summary: undefined }));
    expect(screen.queryByTestId("node-summary")).toBeNull();
  });

  it("shows a role badge + role colour on a variable node", () => {
    mountNode(
      vn({
        id: "var:education:cleaned",
        kind: "variable",
        stage: "transform",
        title: "education (cleaned)",
      } as Partial<GraphViewNode>),
      "related",
      { role: "focal" },
    );
    const badge = screen.getByTestId("node-role-badge");
    expect(badge).toHaveTextContent("X");
    expect(badge).toHaveAttribute("data-role", "focal");
  });

  it("shows a roles tag on the model node when provided", () => {
    mountNode(vn(), "related", { rolesTag: "unspecified" });
    expect(screen.getByTestId("node-roles-tag")).toHaveTextContent(
      "roles: unspecified",
    );
  });

  it("stamps a forest identity badge on a model node with nodeHash + runs", () => {
    mountNode(
      vn({
        nodeHash: "bb21bce0deadbeef",
        runs: ["20260630_021506_881210_d5cbd8a7"],
      } as Partial<GraphViewNode>),
    );
    const badge = screen.getByTestId("node-model-badge");
    expect(badge).toHaveTextContent("021506");
    expect(badge).toHaveTextContent("bb21b");
    expect(badge).toHaveTextContent("source");
  });

  it("marks a rerun forest model node with the rerun role", () => {
    mountNode(
      vn({
        nodeHash: "cc44d",
        runs: ["a_b"],
        rerunFrom: { owner_run_id: "x" },
      } as Partial<GraphViewNode>),
    );
    expect(screen.getByTestId("model-node-badge")).toHaveAttribute("data-role", "rerun");
  });

  it("renders no identity badge for a single-run model node (no nodeHash)", () => {
    mountNode(vn());
    expect(screen.queryByTestId("node-model-badge")).toBeNull();
  });

  it("shows no badge when trust=ok and no review needed", () => {
    mountNode(vn());
    expect(screen.queryByTestId("node-badge")).toBeNull();
  });

  it("shows review badge when trust=review", () => {
    mountNode(vn({ trust: "review" }));
    const badge = screen.getByTestId("node-badge");
    expect(badge).toHaveTextContent("Review");
    expect(badge.className).toContain("ln-graph-node__badge--review");
  });

  it("shows review badge when any decision needs review (even if trust=ok)", () => {
    mountNode(vn({ decisions: [vd("needed")] }));
    expect(screen.getByTestId("node-badge")).toHaveTextContent("Review");
  });

  it("shows review badge when any decision failed review (even if trust=ok)", () => {
    mountNode(vn({ decisions: [vd("failed")] }));
    expect(screen.getByTestId("node-badge")).toHaveTextContent("Review");
  });

  it("shows caution badge when trust=caution (takes priority over review)", () => {
    mountNode(vn({ trust: "caution", decisions: [vd("needed")] }));
    const badge = screen.getByTestId("node-badge");
    expect(badge).toHaveTextContent("Caution");
    expect(badge.className).toContain("ln-graph-node__badge--caution");
  });

  // v1.6.6 ④: BLOCKER is its own strongest variant, distinct from caution.
  it("shows blocker badge when trust=blocker (highest priority)", () => {
    mountNode(vn({ trust: "blocker", decisions: [vd("needed")] }));
    const badge = screen.getByTestId("node-badge");
    expect(badge).toHaveTextContent("Blocker");
    expect(badge.className).toContain("ln-graph-node__badge--blocker");
  });

  it("surfaces trustReason as the badge tooltip (title attr)", () => {
    mountNode(vn({ trust: "blocker", trustReason: "singular design matrix" }));
    expect(screen.getByTestId("node-badge")).toHaveAttribute(
      "title",
      "singular design matrix",
    );
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
      mountNode(vn({ decisions: [vd(status)] }));
      expect(screen.queryByTestId("node-badge")).toBeNull();
    });
  }

  it("shows review badge when trust=review even with no decisions [REV-2]", () => {
    mountNode(vn({ trust: "review", decisions: [] }));
    expect(screen.getByTestId("node-badge")).toHaveTextContent("Review");
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
          mountNode(vn({ stage, trust }));
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
      mountNode(vn({ stage: "unknown" }));
      const node = screen.getByTestId("graph-node");
      expect(node.style.getPropertyValue("--node-color")).toBe(
        "var(--label-tertiary)",
      );
    });
  });

  describe("tri-state highlighting (T8.5)", () => {
    it("state=selected applies selected outline class", () => {
      mountNode(vn(), "selected");
      const node = screen.getByTestId("graph-node");
      expect(node.className).toContain("ln-graph-node--selected");
      expect(node.className).not.toContain("ln-graph-node--dim");
      expect(node).toHaveAttribute("data-state", "selected");
    });

    it("state=related applies no extra classes (default opacity)", () => {
      mountNode(vn(), "related");
      const node = screen.getByTestId("graph-node");
      expect(node.className).not.toContain("ln-graph-node--selected");
      expect(node.className).not.toContain("ln-graph-node--dim");
      expect(node).toHaveAttribute("data-state", "related");
    });

    it("state=dim applies the dim class", () => {
      mountNode(vn(), "dim");
      const node = screen.getByTestId("graph-node");
      expect(node.className).toContain("ln-graph-node--dim");
      expect(node.className).not.toContain("ln-graph-node--selected");
      expect(node).toHaveAttribute("data-state", "dim");
    });
  });

  // V1.5.2 P6 — 5-level highlight model. Plan §8.
  describe("V1.5.2 focus / focus-upstream / search overlay", () => {
    it("state=focus applies the focus class (distinct from selected)", () => {
      mountNode(vn(), "focus");
      const node = screen.getByTestId("graph-node");
      expect(node.className).toContain("ln-graph-node--focus");
      expect(node.className).not.toContain("ln-graph-node--selected");
      expect(node).toHaveAttribute("data-state", "focus");
    });

    it("state=focus-upstream applies its own class (above related, below focus)", () => {
      mountNode(vn(), "focus-upstream");
      const node = screen.getByTestId("graph-node");
      const classes = node.className.split(/\s+/);
      expect(classes).toContain("ln-graph-node--focus-upstream");
      // Whole-class check — "--focus" alone must not be present even though
      // it's a substring of "--focus-upstream".
      expect(classes).not.toContain("ln-graph-node--focus");
      expect(node).toHaveAttribute("data-state", "focus-upstream");
    });

    it("isSearchHit layers on top of any state (does not displace it)", () => {
      // Search hit + selected → both classes apply.
      rtlRender(
        <ReactFlowProvider>
          <GraphNode
            data={{ node: vn(), state: "selected", isSearchHit: true }}
            selected
          />
        </ReactFlowProvider>,
      );
      const node = screen.getByTestId("graph-node");
      expect(node.className).toContain("ln-graph-node--selected");
      expect(node.className).toContain("ln-graph-node--search-hit");
      expect(node).toHaveAttribute("data-search-hit", "true");
    });

    it("isSearchHit absent → no search-hit class, no data attr", () => {
      mountNode(vn(), "related");
      const node = screen.getByTestId("graph-node");
      expect(node.className).not.toContain("ln-graph-node--search-hit");
      expect(node.getAttribute("data-search-hit")).toBeNull();
    });

    it("F5: isSearchCursor adds the cursor class + data attr", () => {
      rtlRender(
        <ReactFlowProvider>
          <GraphNode
            data={{
              node: vn(),
              state: "related",
              isSearchHit: true,
              isSearchCursor: true,
            }}
            selected={false}
          />
        </ReactFlowProvider>,
      );
      const node = screen.getByTestId("graph-node");
      // Cursor is also a hit — both classes present, cursor wins via CSS.
      expect(node.className).toContain("ln-graph-node--search-hit");
      expect(node.className).toContain("ln-graph-node--search-cursor");
      expect(node).toHaveAttribute("data-search-cursor", "true");
    });

    it("F5: isSearchCursor absent → no cursor class, no data attr", () => {
      rtlRender(
        <ReactFlowProvider>
          <GraphNode
            data={{ node: vn(), state: "related", isSearchHit: true }}
            selected={false}
          />
        </ReactFlowProvider>,
      );
      const node = screen.getByTestId("graph-node");
      expect(node.className).not.toContain("ln-graph-node--search-cursor");
      expect(node.getAttribute("data-search-cursor")).toBeNull();
    });
  });

  describe("v1.6.7 draft lifecycle visual states (S2)", () => {
    it("tags a draft node with its lifecycle state for styling", () => {
      mountNode(vn({ isDraft: true, draftId: "d1", lifecycleState: "draft", title: "draft · ols" }));
      const el = screen.getByTestId("graph-node-lifecycle");
      expect(el).toHaveAttribute("data-lifecycle", "draft");
    });

    it("marks a pending draft node", () => {
      mountNode(vn({ isDraft: true, draftId: "d1", lifecycleState: "pending", title: "draft · ols" }));
      expect(screen.getByTestId("graph-node-lifecycle")).toHaveAttribute("data-lifecycle", "pending");
    });

    it("leaves a real (non-draft) node without the lifecycle testid", () => {
      mountNode(vn());
      expect(screen.queryByTestId("graph-node-lifecycle")).toBeNull();
    });
  });
});
