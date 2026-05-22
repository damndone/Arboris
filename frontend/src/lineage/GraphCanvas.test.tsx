import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GraphCanvas } from "./GraphCanvas";
import type { GraphResponse, LineageNode } from "./types";

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
        graph={graph()}
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
        graph={mixedVariantGraph()}
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

  it("does not render a fold-back marker for a stale expanded id whose parent is missing", async () => {
    // expandedGroups contains a group id whose `parent_stage_id` is no longer
    // present in graph.nodes (e.g. user navigated, URL state survived). The
    // marker should be suppressed — dagre has nowhere to anchor it.
    render(
      <GraphCanvas
        graph={graph()}
        selectedNodeId={null}
        expandedGroups={new Set(["group:variables:stage:does_not_exist"])}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );
    expect(screen.queryByText(/expanded/i)).not.toBeInTheDocument();
  });
});
