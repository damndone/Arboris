import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GraphCanvas, waitingReviewsCount } from "./GraphCanvas";
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

  describe("canvas chrome (T8.6a)", () => {
    function renderCanvas() {
      return render(
        <GraphCanvas
          model={model(graph())}
          selectedNodeId={null}
          expandedGroups={new Set()}
          onSelect={vi.fn()}
          onExpandGroup={vi.fn()}
        />,
      );
    }

    it("renders the toolbar with Free/Horizontal/Vertical/Fit/Fullscreen", () => {
      renderCanvas();
      const toolbar = screen.getByTestId("canvas-toolbar");
      expect(toolbar).toBeInTheDocument();
      // V1.5.1 T4': segmented layout control replaces the disabled
      // Auto-layout indicator. Free is the default per user spec.
      expect(screen.getByTestId("toolbar-layout-free")).toBeEnabled();
      expect(screen.getByTestId("toolbar-layout-lr")).toBeEnabled();
      expect(screen.getByTestId("toolbar-layout-tb")).toBeEnabled();
      expect(screen.getByTestId("toolbar-fit")).toBeEnabled();
      expect(screen.getByTestId("toolbar-fullscreen")).toBeEnabled();
    });

    it("defaults to Free layout (Free button aria-pressed=true)", () => {
      renderCanvas();
      expect(screen.getByTestId("toolbar-layout-free")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByTestId("toolbar-layout-lr")).toHaveAttribute(
        "aria-pressed",
        "false",
      );
      expect(screen.getByTestId("toolbar-layout-tb")).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });

    it("clicking Horizontal flips aria-pressed to LR", () => {
      renderCanvas();
      fireEvent.click(screen.getByTestId("toolbar-layout-lr"));
      expect(screen.getByTestId("toolbar-layout-lr")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByTestId("toolbar-layout-free")).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });

    it("clicking Vertical flips aria-pressed to TB", () => {
      renderCanvas();
      fireEvent.click(screen.getByTestId("toolbar-layout-tb"));
      expect(screen.getByTestId("toolbar-layout-tb")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    it("Fullscreen button no-ops gracefully when API unsupported", () => {
      // jsdom doesn't implement Fullscreen API. Asserting the click
      // doesn't throw is the contract: graceful degradation per
      // T8.6a guidance.
      renderCanvas();
      expect(() =>
        fireEvent.click(screen.getByTestId("toolbar-fullscreen")),
      ).not.toThrow();
    });

    it("edge handles are horizontal (left/right) in Free/LR layouts", () => {
      // React Flow's <Handle> renders a div with class
      // .react-flow__handle-{left|right|top|bottom}. Default mode is Free,
      // which maps to horizontal axis → left for target, right for source.
      renderCanvas();
      // Wait synchronously: jsdom renders the handles inline.
      expect(
        document.querySelectorAll(".react-flow__handle-left").length,
      ).toBeGreaterThan(0);
      expect(
        document.querySelectorAll(".react-flow__handle-right").length,
      ).toBeGreaterThan(0);
      // No vertical handles in the default state.
      expect(
        document.querySelectorAll(".react-flow__handle-top").length,
      ).toBe(0);
      expect(
        document.querySelectorAll(".react-flow__handle-bottom").length,
      ).toBe(0);
    });

    it("clicking Vertical flips handles to top/bottom", () => {
      renderCanvas();
      fireEvent.click(screen.getByTestId("toolbar-layout-tb"));
      expect(
        document.querySelectorAll(".react-flow__handle-top").length,
      ).toBeGreaterThan(0);
      expect(
        document.querySelectorAll(".react-flow__handle-bottom").length,
      ).toBeGreaterThan(0);
      expect(
        document.querySelectorAll(".react-flow__handle-left").length,
      ).toBe(0);
    });

    it("Fullscreen handler silently swallows a rejected requestFullscreen", async () => {
      // Simulate a browser that exposes the API but rejects (e.g. no
      // user gesture, security policy). The click must not surface
      // an unhandled rejection.
      const origEnabled = Object.getOwnPropertyDescriptor(
        document,
        "fullscreenEnabled",
      );
      Object.defineProperty(document, "fullscreenEnabled", {
        configurable: true,
        get: () => true,
      });
      const elProto = HTMLElement.prototype as unknown as {
        requestFullscreen?: () => Promise<void>;
      };
      const origReq = elProto.requestFullscreen;
      elProto.requestFullscreen = () =>
        Promise.reject(new Error("user gesture required"));

      try {
        renderCanvas();
        fireEvent.click(screen.getByTestId("toolbar-fullscreen"));
        // Flush microtasks so the rejected promise resolves inside the
        // try/catch in the handler.
        await Promise.resolve();
      } finally {
        if (origReq) elProto.requestFullscreen = origReq;
        else delete elProto.requestFullscreen;
        if (origEnabled)
          Object.defineProperty(document, "fullscreenEnabled", origEnabled);
      }
    });

    it("renders the status badge with run id and 0 waiting (clean graph)", () => {
      renderCanvas();
      const status = screen.getByTestId("canvas-status");
      expect(status).toHaveTextContent("run_r1");
      const count = screen.getByTestId("canvas-status-count");
      expect(count).toHaveTextContent("waiting 0 reviews");
      // No warn styling at zero.
      expect(count.className).not.toContain("--warn");
    });

    it("counts decisions with reviewStatus ∈ {needed, failed} across all nodes", () => {
      // Build a graph with mixed review states; verify the badge text +
      // warn class. waitingReviewsCount itself is the pure unit.
      const g: GraphResponse = {
        schema_version: 2,
        run_id: "r-mix",
        legacy: false,
        stats: {
          node_count: 2,
          edge_count: 0,
          leaf_count: 2,
          has_dp_count: 0,
        },
        nodes: {
          N1: node({
            id: "N1",
            kind: "model",
            display_label: "N1",
            decision_points: [
              {
                decision_id: "d1",
                decision_id_alias: [],
                selected: null,
                candidates: [],
                source: "system_default",
                contestability: {
                  is_contestable: true,
                  assumption_checks_needed: [],
                  warnings: [],
                  review_status: "needed",
                },
                reason: null,
              },
              {
                decision_id: "d2",
                decision_id_alias: [],
                selected: null,
                candidates: [],
                source: "system_default",
                contestability: {
                  is_contestable: true,
                  assumption_checks_needed: [],
                  warnings: [],
                  review_status: "passed",
                },
                reason: null,
              },
            ],
          }),
          N2: node({
            id: "N2",
            kind: "model",
            display_label: "N2",
            decision_points: [
              {
                decision_id: "d3",
                decision_id_alias: [],
                selected: null,
                candidates: [],
                source: "system_default",
                contestability: {
                  is_contestable: true,
                  assumption_checks_needed: [],
                  warnings: [],
                  review_status: "failed",
                },
                reason: null,
              },
            ],
          }),
        },
        edges: {},
        branches: {},
      };
      const vm = model(g);
      // Pure-function spot check: 1 needed (N1.d1) + 1 failed (N2.d3) = 2.
      expect(waitingReviewsCount(vm)).toBe(2);

      render(
        <GraphCanvas
          model={vm}
          selectedNodeId={null}
          expandedGroups={new Set()}
          onSelect={vi.fn()}
          onExpandGroup={vi.fn()}
        />,
      );
      const count = screen.getByTestId("canvas-status-count");
      expect(count).toHaveTextContent("waiting 2 reviews");
      expect(count.className).toContain("--warn");
    });

    // REV-2: explicitly verify non-triggering decision statuses do
    // NOT contribute to the waiting count. Without this, we could
    // accidentally count waived/passed/not_needed/unknown and the
    // happy-path tests above wouldn't notice.
    it("waitingReviewsCount=0 when all decisions are non-triggering [REV-2]", () => {
      const benignStatuses = [
        "passed",
        "not_needed",
        "waived",
        "unknown",
      ] as const;
      const g: GraphResponse = {
        schema_version: 2,
        run_id: "r-benign",
        legacy: false,
        stats: {
          node_count: 1,
          edge_count: 0,
          leaf_count: 1,
          has_dp_count: 0,
        },
        nodes: {
          N: node({
            id: "N",
            display_label: "N",
            decision_points: benignStatuses.map((status, i) => ({
              decision_id: `d${i}`,
              decision_id_alias: [],
              selected: null,
              candidates: [],
              source: "system_default",
              contestability: {
                is_contestable: true,
                assumption_checks_needed: [],
                warnings: [],
                review_status: status,
              },
              reason: null,
            })),
          }),
        },
        edges: {},
        branches: {},
      };
      const vm = model(g);
      expect(waitingReviewsCount(vm)).toBe(0);
    });

    it("waitingReviewsCount uses singular form for N=1", () => {
      const g: GraphResponse = {
        schema_version: 2,
        run_id: "r-single",
        legacy: false,
        stats: {
          node_count: 1,
          edge_count: 0,
          leaf_count: 1,
          has_dp_count: 0,
        },
        nodes: {
          N: node({
            id: "N",
            display_label: "N",
            decision_points: [
              {
                decision_id: "d",
                decision_id_alias: [],
                selected: null,
                candidates: [],
                source: "system_default",
                contestability: {
                  is_contestable: true,
                  assumption_checks_needed: [],
                  warnings: [],
                  review_status: "needed",
                },
                reason: null,
              },
            ],
          }),
        },
        edges: {},
        branches: {},
      };
      render(
        <GraphCanvas
          model={model(g)}
          selectedNodeId={null}
          expandedGroups={new Set()}
          onSelect={vi.fn()}
          onExpandGroup={vi.fn()}
        />,
      );
      expect(screen.getByTestId("canvas-status-count")).toHaveTextContent(
        "waiting 1 review",
      );
    });

    it("renders all 8 stage swatches in the legend (collapsed by default)", () => {
      renderCanvas();
      const legend = screen.getByTestId("canvas-legend");
      expect(legend).toBeInTheDocument();
      // 8 swatches always rendered; expanded toggles their visibility
      // via CSS (display:none on the wrapping list).
      for (const s of [
        "source",
        "eda",
        "clean",
        "transform",
        "model",
        "diag",
        "viz",
        "report",
      ]) {
        expect(screen.getByTestId(`legend-swatch-${s}`)).toBeInTheDocument();
      }
      expect(legend.className).not.toContain("--expanded");
    });

    // REV-2: confirm the Chinese label text from uiux/panels.jsx
    // stageLabel actually renders. Drift in our STAGE_LABEL constant
    // (typo, missing entry) breaks user-visible copy silently.
    it("renders the Chinese stage labels from uiux/panels.jsx [REV-2]", () => {
      renderCanvas();
      // Mapping per uiux/panels.jsx::stageLabel (L301-304).
      const expected: Record<string, string> = {
        source: "原始",
        eda: "探索",
        clean: "清洗",
        transform: "变换",
        model: "模型",
        diag: "诊断",
        viz: "可视化",
        report: "报告",
      };
      for (const [, label] of Object.entries(expected)) {
        expect(screen.getByText(label)).toBeInTheDocument();
      }
    });

    // REV-2: the synthetic "unknown" stage (used for group + marker
    // pseudo-nodes) must NOT appear in the user-facing legend.
    it("does not render the synthetic 'unknown' stage in the legend [REV-2]", () => {
      renderCanvas();
      expect(
        screen.queryByTestId("legend-swatch-unknown"),
      ).toBeNull();
    });

    it("legend expands on mouse enter, collapses on leave", () => {
      renderCanvas();
      const legend = screen.getByTestId("canvas-legend");
      fireEvent.mouseEnter(legend);
      expect(legend.className).toContain("ln-canvas-legend--expanded");
      fireEvent.mouseLeave(legend);
      expect(legend.className).not.toContain("ln-canvas-legend--expanded");
    });

    // T8.6b: structural guard for the scoped CSS override of React
    // Flow's <Controls>. We do NOT assert computed CSS (jsdom doesn't
    // resolve stylesheets meaningfully) — that needs browser smoke.
    // What this test pins is the class-name contract: if RF ever
    // renames .react-flow__controls / .react-flow__controls-button
    // the override silently breaks visually but this test fails
    // immediately, flagging the regression.
    it("React Flow Controls render with the expected class hooks [T8.6b]", () => {
      renderCanvas();
      const controls = document.querySelector(".react-flow__controls");
      expect(controls).not.toBeNull();
      const buttons = document.querySelectorAll(
        ".react-flow__controls-button",
      );
      // Default Controls renders zoom-in, zoom-out, fit-view (3
      // buttons — interactive is suppressed by showInteractive=false).
      expect(buttons.length).toBe(3);
      expect(
        document.querySelector(".react-flow__controls-zoomin"),
      ).not.toBeNull();
      expect(
        document.querySelector(".react-flow__controls-zoomout"),
      ).not.toBeNull();
      expect(
        document.querySelector(".react-flow__controls-fitview"),
      ).not.toBeNull();
    });

    // REV-3 [T8.6b]: the CSS override is scoped under .lineage-root.
    // If a future refactor mounts <Controls> outside the lineage-root
    // wrapper, the scoped CSS silently stops applying and the
    // controls revert to RF's default (#fefefe / #eee). Verify the
    // wrapper invariant holds.
    it("Controls live inside .lineage-root so the scoped CSS applies [T8.6b]", () => {
      renderCanvas();
      const root = document.querySelector(".lineage-root");
      const controls = document.querySelector(".react-flow__controls");
      expect(root).not.toBeNull();
      expect(controls).not.toBeNull();
      expect(root!.contains(controls)).toBe(true);
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

  // V1.5.0.1 HF5: the V1.5.0 implementation re-ran layoutDagre on
  // every selectedNodeId change, which would have snapped any user-
  // dragged position back to the dagre seed (functionally killing
  // drag). HF5 splits seed layout from selection decoration so user
  // drags survive. This test verifies the seed positions don't churn
  // across a selection-only change — the underlying contract for
  // drag-persistence in the real browser.
  it("preserves RF node positions across a selection change [HF5]", async () => {
    const m = model(graph());
    const { rerender } = render(
      <GraphCanvas
        model={m}
        selectedNodeId={null}
        expandedGroups={new Set()}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );

    const stageNode = await screen.findByText("Cleaned data");
    const stageRfWrapper = stageNode.closest(".react-flow__node") as HTMLElement;
    expect(stageRfWrapper).not.toBeNull();
    const initialTransform = stageRfWrapper.style.transform;
    expect(initialTransform).toBeTruthy();

    // Re-render with a different selectedNodeId. The seed layout
    // must NOT re-run, so the transform on stage:cleaned stays the
    // same byte-for-byte.
    rerender(
      <GraphCanvas
        model={m}
        selectedNodeId="stage:cleaned"
        expandedGroups={new Set()}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );
    const afterSelection = stageNode.closest(".react-flow__node") as HTMLElement;
    expect(afterSelection.style.transform).toBe(initialTransform);
  });
});

describe("GraphCanvas — v1.6.5 variable roles", () => {
  function roleGraph(): GraphResponse {
    const nodes: Record<string, LineageNode> = {
      "stage:cleaned": node({
        id: "stage:cleaned",
        kind: "dataset_stage",
        display_label: "Cleaned data",
        summary: "Cleaned: 40 rows",
      }),
      "model:ols_1": node({
        id: "model:ols_1",
        kind: "model",
        display_label: "ols_robust (primary)",
        summary: "OLS",
      }),
      "var:wage:cleaned": node({
        id: "var:wage:cleaned",
        display_label: "wage (cleaned)",
        parent_stage_id: "stage:cleaned",
      }),
      "var:firm:cleaned": node({
        id: "var:firm:cleaned",
        display_label: "firm (cleaned)",
        parent_stage_id: "stage:cleaned",
      }),
    };
    const mkEdge = (id: string, s: string, t: string, op: string): LineageEdge => ({
      id,
      source_id: s,
      target_id: t,
      op,
      params: {},
      reversible: false,
      inverse_op: null,
    });
    const edges: Record<string, LineageEdge> = {
      fit: mkEdge("fit", "stage:cleaned", "model:ols_1", "ols_robust.fit"),
      out: mkEdge("out", "var:wage:cleaned", "model:ols_1", "enters_as_outcome"),
      clu: mkEdge("clu", "var:firm:cleaned", "model:ols_1", "configures_cluster"),
    };
    return {
      schema_version: 2,
      run_id: "r1",
      legacy: false,
      stats: { node_count: 4, edge_count: 3, leaf_count: 1, has_dp_count: 0 },
      nodes,
      edges,
      branches: {},
    };
  }

  it("stamps role badges on variable nodes from their role edges", () => {
    render(
      <GraphCanvas
        model={model(roleGraph())}
        selectedNodeId={null}
        expandedGroups={new Set()}
        onSelect={vi.fn()}
        onExpandGroup={vi.fn()}
      />,
    );
    const badges = Array.from(
      document.querySelectorAll('[data-testid="node-role-badge"]'),
    );
    const byRole = new Map(
      badges.map((b) => [b.getAttribute("data-role"), b.textContent]),
    );
    expect(byRole.get("outcome")).toBe("Y");
    expect(byRole.get("cluster")).toBe("C");
  });
});
