// frontend/src/lineage/GraphWorkbench.test.tsx
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

  it("renders detail drawer only when selectedKey resolves to a real node (T6.11 swap)", () => {
    const { rerender } = renderWithCtx(makeCtx(rawGraph(), null));
    expect(screen.queryByTestId("detail-drawer")).toBeNull();

    rerender(
      <MemoryRouter>
        <LineageContext.Provider value={makeCtx(rawGraph(), "stage:raw")}>
          <GraphWorkbench />
        </LineageContext.Provider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("detail-drawer")).toBeInTheDocument();
    // Drawer renders the header h2 with the node's title.
    expect(document.getElementById("detail-drawer-title")?.textContent).toBe("Raw");
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

  it("selectedKey not in model → drawer slot is suppressed [REV-3 #3]", () => {
    // Cross-run leak: user navigates /runs/A?node=x → /runs/B; the URL
    // still says node=x but model B has no such node. Workbench must NOT
    // mount an orphan drawer.
    renderWithCtx(makeCtx(rawGraph(), "stage:ghost"));
    expect(screen.queryByTestId("drawer-slot")).toBeNull();
    // Canvas still renders the real model.
    expect(screen.getByText("Raw")).toBeInTheDocument();
  });

  it("⌘J keydown is handled by the wired-in useGraphKeyboard [REV-3 #1]", () => {
    // Regression guard: T5.7 unmounted V1.4.1 LineageTab which carried its
    // own keydown listener. Without re-wiring useGraphKeyboard inside the
    // workbench, ⌘J would silently no-op in production. The hook now lives
    // here, so the keydown does not propagate to the browser default
    // (preventDefault is called for ⌘J inside the hook).
    renderWithCtx(makeCtx(rawGraph(), null));
    const evt = new KeyboardEvent("keydown", {
      key: "j",
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    const prevented = !window.dispatchEvent(evt);
    expect(prevented).toBe(true); // listener called preventDefault
  });

  it("Escape clears the selection via context.select(null) [REV-3 #1 follow-on]", () => {
    const select = vi.fn();
    renderWithCtx(makeCtx(rawGraph(), "stage:raw", select));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(select).toHaveBeenCalledWith(null);
  });

  describe("T6.12 legacy stage hint", () => {
    function v2RawGraph(stages: Array<"source" | undefined>) {
      // v2 disk graphs come through the adapter with stage="unknown" when
      // omitted. Build a fixture that lets us control the unknown ratio.
      const fixture = rawGraph();
      const baseNode = fixture.nodes["stage:raw"];
      fixture.nodes = {} as typeof fixture.nodes;
      stages.forEach((stage, i) => {
        const id = `n${i}`;
        const next = { ...baseNode, id, display_label: id } as typeof baseNode;
        if (stage !== undefined) {
          (next as unknown as { stage?: string }).stage = stage;
        } else {
          delete (next as unknown as { stage?: string }).stage;
        }
        (fixture.nodes as Record<string, typeof baseNode>)[id] = next;
      });
      fixture.schema_version = stages.some((s) => s !== undefined) ? 3 : 2;
      return fixture;
    }

    it("shows hint when ≥50% of nodes have stage='unknown' (DoD: 80% case)", () => {
      // 4 nodes, 4 unknown (no stage field on v2) = 100% > 50%.
      renderWithCtx(makeCtx(v2RawGraph([undefined, undefined, undefined, undefined])));
      expect(screen.getByTestId("legacy-stage-hint")).toBeInTheDocument();
      expect(
        screen.getByText(/run predates stage tagging/i),
      ).toBeInTheDocument();
    });

    it("does NOT show hint when 0% unknown (DoD: 0% case)", () => {
      // 4 nodes, all stage='source' → ratio 0%.
      renderWithCtx(
        makeCtx(v2RawGraph(["source", "source", "source", "source"])),
      );
      expect(screen.queryByTestId("legacy-stage-hint")).toBeNull();
    });

    it("does NOT show hint when exactly 49% unknown (just below threshold)", () => {
      // 100 nodes, 49 unknown.
      const stages: Array<"source" | undefined> = [
        ...Array(49).fill(undefined),
        ...Array(51).fill("source"),
      ];
      renderWithCtx(makeCtx(v2RawGraph(stages)));
      expect(screen.queryByTestId("legacy-stage-hint")).toBeNull();
    });

    it("shows hint at exactly 50% (boundary inclusive)", () => {
      const stages: Array<"source" | undefined> = [
        ...Array(2).fill(undefined),
        ...Array(2).fill("source"),
      ];
      renderWithCtx(makeCtx(v2RawGraph(stages)));
      expect(screen.getByTestId("legacy-stage-hint")).toBeInTheDocument();
    });

    it("Dismiss button hides the banner for the rest of the session", () => {
      renderWithCtx(makeCtx(v2RawGraph([undefined, undefined])));
      expect(screen.getByTestId("legacy-stage-hint")).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: /dismiss legacy stage hint/i }),
      );
      expect(screen.queryByTestId("legacy-stage-hint")).toBeNull();
    });

    it("legacy banner takes priority — model.legacy=true still shows LegacyBanner only", () => {
      renderWithCtx(makeCtx(rawGraph({ legacy: true })));
      expect(screen.getByTestId("legacy-banner")).toBeInTheDocument();
      expect(screen.queryByTestId("legacy-stage-hint")).toBeNull();
    });
  });
});
