// frontend/src/lineage/GraphWorkbench.test.tsx
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { GraphWorkbench } from "./GraphWorkbench";
import { LineageContext, type LineageContextValue } from "./LineageContext";
import { adaptRunGraph } from "./api/graphAdapter";
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

function rawGraph(overrides: Partial<GraphResponse> = {}): GraphResponse {
  return {
    schema_version: 2,
    run_id: "r1",
    legacy: false,
    stats: { node_count: 1, edge_count: 0, leaf_count: 1, has_dp_count: 0 },
    nodes: {
      "stage:raw": node({
        id: "stage:raw",
        kind: "dataset_stage",
        display_label: "Raw",
        summary: "Raw: 10 rows × 2 cols",
      }),
    },
    edges: {},
    branches: {},
    ...overrides,
  };
}

function makeCtx(
  raw: GraphResponse,
  selectedKey: string | null = null,
  select: (k: string | null) => void = vi.fn(),
): LineageContextValue {
  return { model: adaptRunGraph(raw), selectedKey, select };
}

function renderWithCtx(value: LineageContextValue) {
  return render(
    <MemoryRouter>
      <LineageContext.Provider value={value}>
        <GraphWorkbench />
      </LineageContext.Provider>
    </MemoryRouter>,
  );
}

describe("GraphWorkbench", () => {
  it("mounts the canvas when context has a non-legacy model", () => {
    renderWithCtx(makeCtx(rawGraph()));
    expect(screen.getByTestId("graph-workbench")).toBeInTheDocument();
    // Canvas's lineage-root mounts and dagre lays out at least one node.
    expect(screen.getByText("Raw")).toBeInTheDocument();
  });

  it("legacy model → shows legacy banner, NOT the workbench layout", () => {
    renderWithCtx(makeCtx(rawGraph({ legacy: true })));
    expect(screen.getByTestId("legacy-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-workbench")).toBeNull();
    expect(
      screen.getByText(/no lineage data for this run/i),
    ).toBeInTheDocument();
  });

  it("renders drawer slot only when selectedKey is non-null", () => {
    const { rerender } = renderWithCtx(makeCtx(rawGraph(), null));
    expect(screen.queryByTestId("drawer-slot")).toBeNull();

    rerender(
      <MemoryRouter>
        <LineageContext.Provider value={makeCtx(rawGraph(), "stage:raw")}>
          <GraphWorkbench />
        </LineageContext.Provider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("drawer-slot")).toBeInTheDocument();
    expect(screen.getByText(/detail drawer for stage:raw/i)).toBeInTheDocument();
  });

  it("clicking a node calls select(nodeId) from context", () => {
    const select = vi.fn();
    renderWithCtx(makeCtx(rawGraph(), null, select));
    fireEvent.click(screen.getByText("Raw"));
    expect(select).toHaveBeenCalledWith("stage:raw");
  });

  it("throws if mounted outside LineageContext provider", () => {
    // useLineage() throws — assert the consumer's error surfaces. React
    // logs the error to console.error, which we silence so test output
    // stays clean.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<GraphWorkbench />)).toThrow(/useLineage/);
    errSpy.mockRestore();
  });

  // Reference unused import to satisfy linter while keeping a forward-compat
  // hook for future tests that need to assert URL state changes.
  void useNavigate;
  void Route;
  void Routes;
});
