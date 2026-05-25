// frontend/src/lineage/GraphWorkbench.test.tsx
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
    beforeEach(() => {
      // REV-3 P2: dismissal now persists in sessionStorage keyed by runId.
      // Clear between tests so prior dismissals don't leak across cases.
      sessionStorage.clear();
    });


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

    it("Dismissal persists across remount within the same session [REV-3 P2]", () => {
      // Spec §19.4 "dismissible per session" — leaving the Lineage tab and
      // returning must not resurrect the banner. We model the tab-leave as
      // an unmount/remount of the workbench with the same runId.
      const fixture = v2RawGraph([undefined, undefined]);
      const { unmount } = renderWithCtx(makeCtx(fixture));
      fireEvent.click(
        screen.getByRole("button", { name: /dismiss legacy stage hint/i }),
      );
      unmount();
      renderWithCtx(makeCtx(fixture));
      expect(screen.queryByTestId("legacy-stage-hint")).toBeNull();
    });

    it("Dismissal is scoped per runId — other runs still show the banner [REV-3 P2]", () => {
      const fixtureA = v2RawGraph([undefined, undefined]);
      fixtureA.run_id = "run-A";
      const fixtureB = v2RawGraph([undefined, undefined]);
      fixtureB.run_id = "run-B";

      const { unmount } = renderWithCtx(makeCtx(fixtureA));
      fireEvent.click(
        screen.getByRole("button", { name: /dismiss legacy stage hint/i }),
      );
      unmount();

      // Different runId → banner re-appears, dismissal did not leak.
      renderWithCtx(makeCtx(fixtureB));
      expect(screen.getByTestId("legacy-stage-hint")).toBeInTheDocument();
    });

    it("legacy banner takes priority — model.legacy=true still shows LegacyBanner only", () => {
      renderWithCtx(makeCtx(rawGraph({ legacy: true })));
      expect(screen.getByTestId("legacy-banner")).toBeInTheDocument();
      expect(screen.queryByTestId("legacy-stage-hint")).toBeNull();
    });
  });

  describe("REV-3 follow-ups (Step 6)", () => {
    it("H1: opening RawJsonModal then externally clearing selection closes the modal", () => {
      // Mount with a selected node, ⌘J to open the modal, then re-render
      // with selectedKey=null. The modal must close so subsequent ⌘J
      // doesn't toggle invisibly.
      const { rerender } = renderWithCtx(makeCtx(rawGraph(), "stage:raw"));
      fireEvent.keyDown(window, { key: "j", metaKey: true });
      expect(screen.getByTestId("raw-json-modal")).toBeInTheDocument();

      // External selection clear: re-render with selectedKey=null
      rerender(
        <MemoryRouter>
          <LineageContext.Provider value={makeCtx(rawGraph(), null)}>
            <GraphWorkbench />
          </LineageContext.Provider>
        </MemoryRouter>,
      );
      expect(screen.queryByTestId("raw-json-modal")).toBeNull();
    });

    it("S1: Escape with RawJsonModal open closes only the modal, not the selection", () => {
      const select = vi.fn();
      renderWithCtx(makeCtx(rawGraph(), "stage:raw", select));
      // Open the modal
      fireEvent.keyDown(window, { key: "j", metaKey: true });
      expect(screen.getByTestId("raw-json-modal")).toBeInTheDocument();
      // Escape: closes the modal but must NOT call select(null)
      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByTestId("raw-json-modal")).toBeNull();
      expect(select).not.toHaveBeenCalled();
    });

    it("⌘J with no selected node is a no-op (modal does not appear)", () => {
      renderWithCtx(makeCtx(rawGraph(), null));
      fireEvent.keyDown(window, { key: "j", metaKey: true });
      expect(screen.queryByTestId("raw-json-modal")).toBeNull();
    });
  });
});
