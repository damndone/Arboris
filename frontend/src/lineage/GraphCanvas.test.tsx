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
});
