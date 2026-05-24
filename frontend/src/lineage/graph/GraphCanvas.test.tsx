import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GraphCanvas } from "./GraphCanvas";
import { adaptRunGraph } from "../api/graphAdapter";
import type { GraphResponse, LineageEdge, LineageNode } from "../types";

// Bridge: tests still build the raw backend GraphResponse fixture (so they
// exercise the real adapter path), and pass `adaptRunGraph(g)` into the
// canvas which now requires a V1.5.0 GraphViewModel.
function model(g: GraphResponse) {
  return adaptRunGraph(g);
}

function node(overrides: Partial<LineageNode>): LineageNode {
  return {
    id: "node",
    kind: "variable",
    display_label: "Node",
    summary: null,
    created_at: "",
    parent_stage_id: null,
    branch_id: "main",
    trust: "ok",
    trust_reason: null,
    archived: false,
    payload_ref: null,
    decision_points: [],
    annotations: [],
    ...overrides,
  };
}

function graph(): GraphResponse {
  const nodes: Record<string, LineageNode> = {
    "stage:cleaned": node({
      id: "stage:cleaned",
      kind: "dataset_stage",
      display_label: "Cleaned data",
      summary: "Cleaned: 10 rows",
    }),
  };
  for (let i = 1; i <= 4; i++) {
    nodes[`var:x${i}:cleaned`] = node({
      id: `var:x${i}:cleaned`,
      display_label: `x${i} (cleaned)`,
      summary: "Kept as numeric",
      parent_stage_id: "stage:cleaned",
    });
  }
  return {
    schema_version: 2,
    run_id: "r1",
    legacy: false,
    stats: { node_count: 5, edge_count: 0, leaf_count: 4, has_dp_count: 0 },
    nodes,
    edges: {},
    branches: {},
  };
}

function mixedVariantGraph(): GraphResponse {
  // 4 cleaned + 4 dropped on the same parent stage. Both clusters cross the
  // FOLD_THRESHOLD (>3) so both should fold by default.
  const nodes: Record<string, LineageNode> = {
    "stage:cleaned": node({
      id: "stage:cleaned",
      kind: "dataset_stage",
      display_label: "Cleaned data",
      summary: "Cleaned: 10 rows",
    }),
  };
  for (let i = 1; i <= 4; i++) {
    nodes[`var:x${i}:cleaned`] = node({
      id: `var:x${i}:cleaned`,
      display_label: `x${i} (cleaned)`,
      summary: "Kept as numeric",
      parent_stage_id: "stage:cleaned",
    });
  }
  for (let i = 1; i <= 4; i++) {
    nodes[`var:y${i}:dropped`] = node({
      id: `var:y${i}:dropped`,
      display_label: `y${i} (dropped)`,
      summary: "Dropped: constant",
      parent_stage_id: "stage:cleaned",
    });
  }
  return {
    schema_version: 2,
    run_id: "r1",
    legacy: false,
    stats: { node_count: 9, edge_count: 0, leaf_count: 8, has_dp_count: 0 },
    nodes,
    edges: {},
    branches: {},
  };
}

describe("GraphCanvas", () => {
  it("renders a fold-back marker for expanded variable groups", async () => {
    render(
      <GraphCanvas
        model={model(graph())}
        selectedNodeId={null}
        expandedGroups={new Set(["group:variables:stage:cleaned"])}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );

    expect(await screen.findByText("▼ Variables (expanded)")).toBeInTheDocument();
    expect(screen.getByText("Tap to fold back")).toBeInTheDocument();
  });

  it("keeps a sibling 'dropped' group folded when only the 'cleaned' group is expanded", async () => {
    // Mixed cleaned+dropped clusters on the same parent stage. Expanding only
    // the cleaned variant must NOT collapse the dropped group: the dropped
    // group node should still appear as a folded summary while the cleaned
    // variant gets a fold-back marker. Regression guard for the post-review
    // hotfixes 88dcf70 + c7bd35e which introduced the synthesized marker.
    render(
      <GraphCanvas
        model={model(mixedVariantGraph())}
        selectedNodeId={null}
        expandedGroups={new Set(["group:variables:stage:cleaned"])}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );

    // Cleaned group is expanded → all 4 cleaned variables visible.
    expect(await screen.findByText("x1 (cleaned)")).toBeInTheDocument();
    expect(screen.getByText("x4 (cleaned)")).toBeInTheDocument();

    // Cleaned cluster shows a fold-back affordance.
    expect(screen.getByText("▼ Variables (expanded)")).toBeInTheDocument();

    // Dropped sibling group stays folded as a summary node.
    expect(screen.getByText("Dropped variables (4)")).toBeInTheDocument();
    // And no individual dropped variable leaked through.
    expect(screen.queryByText("y1 (dropped)")).not.toBeInTheDocument();
  });

  describe("tri-state highlighting (T8.5)", () => {
    // 4-node graph for the DoD test: A → B, plus C and D with no edges.
    // Select B → A & B related; C & D dim (the 2 unrelated). Per plan
    // T8.5 step 1: related = inIds ∪ outIds ∪ {selectedKey}.
    function fourNodeGraph(): GraphResponse {
      const nodes: Record<string, LineageNode> = {
        A: node({
          id: "A",
          kind: "dataset_stage",
          display_label: "A",
          summary: "source",
        }),
        B: node({
          id: "B",
          kind: "dataset_stage",
          display_label: "B",
          summary: "middle",
        }),
        C: node({
          id: "C",
          kind: "dataset_stage",
          display_label: "C",
          summary: "loose",
        }),
        D: node({
          id: "D",
          kind: "dataset_stage",
          display_label: "D",
          summary: "loose",
        }),
      };
      const edges: Record<string, LineageEdge> = {
        "A->B": {
          id: "A->B",
          source_id: "A",
          target_id: "B",
          op: "noop",
          params: {},
          reversible: false,
          inverse_op: null,
        },
      };
      return {
        schema_version: 2,
        run_id: "r1",
        legacy: false,
        stats: {
          node_count: 4,
          edge_count: 1,
          leaf_count: 2,
          has_dp_count: 0,
        },
        nodes,
        edges,
        branches: {},
      };
    }

    it("DoD: select middle node → in/out neighbours related, unrelated dim", () => {
      render(
        <GraphCanvas
          model={model(fourNodeGraph())}
          selectedNodeId={"B"}
          expandedGroups={new Set()}
          onSelect={vi.fn()}
          onExpandGroup={vi.fn()}
        />,
      );

      const ofId = (id: string) =>
        document
          .querySelectorAll<HTMLElement>('[data-testid="graph-node"]')
          [
            // Cannot rely on document.order; use data-attribute on the title text
            Array.from(
              document.querySelectorAll<HTMLElement>(
                '[data-testid="graph-node"]',
              ),
            ).findIndex((el) => el.textContent?.includes(id))
          ];

      const a = ofId("A");
      const b = ofId("B");
      const c = ofId("C");
      const d = ofId("D");

      expect(b).toHaveAttribute("data-state", "selected");
      expect(a).toHaveAttribute("data-state", "related");
      expect(c).toHaveAttribute("data-state", "dim");
      expect(d).toHaveAttribute("data-state", "dim");
    });

    it("no selection → all nodes default to related (full opacity)", () => {
      render(
        <GraphCanvas
          model={model(fourNodeGraph())}
          selectedNodeId={null}
          expandedGroups={new Set()}
          onSelect={vi.fn()}
          onExpandGroup={vi.fn()}
        />,
      );

      const allNodes = document.querySelectorAll<HTMLElement>(
        '[data-testid="graph-node"]',
      );
      expect(allNodes.length).toBe(4);
      for (const el of allNodes) {
        expect(el).toHaveAttribute("data-state", "related");
      }
    });
  });

  it("does not render a fold-back marker for a stale expanded id whose parent is missing", async () => {
    // expandedGroups contains a group id whose `parent_stage_id` is no longer
    // present in graph.nodes (e.g. user navigated, URL state survived). The
    // marker should be suppressed — dagre has nowhere to anchor it.
    render(
      <GraphCanvas
        model={model(graph())}
        selectedNodeId={null}
        expandedGroups={new Set(["group:variables:stage:does_not_exist"])}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );
    expect(screen.queryByText(/expanded/i)).not.toBeInTheDocument();
  });
});
