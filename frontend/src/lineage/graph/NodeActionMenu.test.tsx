// frontend/src/lineage/graph/NodeActionMenu.test.tsx
//
// Rewritten for V1.5.0 contract (spec §10.2 / §10.3 + plan T6.9).
// Migration map from V1.4.1 MoreMenu.test.tsx:
//   - "hides menu by default; opens when toggle clicked" → kept (1)
//   - "calls onShowJson on View raw JSON"               → kept (label is now "View Raw JSON")
//   - "copies node id to clipboard on Copy node ID"     → kept (now writes nodeKey)
//   - "copies node JSON to clipboard on Copy as JSON"   → kept (now writes node.raw)
// New in V1.5.0:
//   - "Copy lineage path" item
//   - Reserved items intentionally absent (spec §10.3 lock)
//   - Outside-click closes
//   - Escape closes

import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import * as api from "../../api";
import { NodeActionMenu } from "./NodeActionMenu";
import { ForestContext } from "../../workbench/ForestContext";
import { ProjectRootProvider } from "../../workbench/ProjectRootContext";
import { NodeOperationContextProvider } from "../detail/NodeOperationContextProvider";
import { makeOwnerResolutionSeedFixture } from "../api/nodeOperationContext";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: vi.fn() };
});

function makeNode(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "model:ols_1",
    nodeKey: "model:ols_1",
    raw: { id: "model:ols_1", kind: "model", display_label: "Primary OLS" },
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    parentStageId: "stage:cleaned",
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

function makeModel(node: GraphViewNode): GraphViewModel {
  const upstream: GraphViewNode = makeNode({
    id: "stage:cleaned",
    nodeKey: "stage:cleaned",
    kind: "dataset_stage",
    title: "Cleaned",
    summary: "Cleaned: 10 rows",
    parentStageId: null,
  });
  return {
    schemaVersion: 3,
    runId: "run-1",
    legacy: false,
    nodes: [upstream, node],
    edges: [
      {
        id: "e1",
        source: "stage:cleaned",
        target: node.id,
        op: "fit",
        reversible: false,
        inverseOp: null,
      },
    ],
    stats: { nodeCount: 2, edgeCount: 1, leafCount: 1, hasDpCount: 0 },
  };
}

function renderMenu(
  node: GraphViewNode,
  onShowJson: () => void = vi.fn(),
) {
  return render(
    <MemoryRouter>
      <NodeActionMenu
        node={node}
        model={makeModel(node)}
        onShowJson={onShowJson}
      />
    </MemoryRouter>,
  );
}

const writeText = vi.fn();
let _origClipboard: PropertyDescriptor | undefined;
beforeEach(() => {
  writeText.mockReset().mockResolvedValue(undefined);
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  _origClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
});

afterEach(() => {
  // REV-3 S2: restore clipboard so other test files don't inherit our mock.
  if (_origClipboard) {
    Object.defineProperty(navigator, "clipboard", _origClipboard);
  } else {
    delete (navigator as { clipboard?: unknown }).clipboard;
  }
});

describe("NodeActionMenu", () => {
  it("hides menu by default; opens when toggle clicked", () => {
    renderMenu(makeNode());
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  // V1.5.2 P6: menu is now registry-driven (actionRegistry filtered
  // by surface="drawer-header-menu") plus the drawer-local "View Raw
  // JSON" item. Items appear in registry order; disabled placeholders
  // (Ask AI / Rerun / Mark needs review) render greyed-out with a
  // reason tooltip rather than being hidden.
  it("exposes View Raw JSON plus the drawer-header registry actions", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    const items = screen.getAllByRole("menuitem");
    const labels = items.map(
      (el) => el.textContent?.trim().replace(/⌘.*$/, "").trim(),
    );
    expect(labels).toEqual([
      "View Raw JSON",
      "Pin as tab",
      "Copy node ID",
      "Copy as JSON",
      "Copy lineage path",
      "Ask AI about this node",
      "Rerun from here",
      "Mark needs review",
    ]);
  });

  it.each([
    // v1.6.11 slice A: "Ask AI about this node" went live (opens the drawer).
    ["Mark needs review"],
  ] as const)(
    'disabled placeholder "%s" renders greyed-out with a reason tooltip (plan §11)',
    (label) => {
      renderMenu(makeNode());
      fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
      const item = screen.getByText(label).closest("button");
      expect(item).not.toBeNull();
      expect(item).toBeDisabled();
      // v1.6.6 ③: reasons are honest now — non-empty, and must NOT cite the
      // long-shipped V1.5.3/V2.0 placeholder versions.
      const title = item?.getAttribute("title") ?? "";
      expect(title.length).toBeGreaterThan(0);
      expect(title).not.toMatch(/V1\.5\.3|V2\.0/i);
    },
  );

  // v1.6.1 (2C.3): "Rerun from here" is now live — enabled, no reason tooltip.
  it('"Rerun from here" is live (enabled, no disabled tooltip)', () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    const item = screen.getByText("Rerun from here").closest("button");
    expect(item).not.toBeNull();
    expect(item).not.toBeDisabled();
  });

  it("disables context-bound actions and prompts for owner selection on resolver failure", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const selected = seed.forest.nodes.find(
      (n) => n.nodeKey === seed.sharedNodeKey,
    )!;
    render(
      <MemoryRouter>
        <ForestContext.Provider
          value={{ forest: seed.forest, activeRunId: "run_x", setActiveRunId: vi.fn() }}
        >
          <NodeOperationContextProvider node={selected}>
            <NodeActionMenu
              node={selected}
              model={seed.graphModel}
              onShowJson={vi.fn()}
            />
          </NodeOperationContextProvider>
        </ForestContext.Provider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    expect(screen.getByText("Choose operation owner").closest("button")).toBeDisabled();
    expect(screen.getByText("Ask AI about this node").closest("button")).toBeDisabled();
    expect(screen.getByText("Rerun from here").closest("button")).toBeDisabled();
  });

  it("V1.5.0-era reserved labels are no longer present (Pin to compare / Coming soon)", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    expect(screen.queryByText(/pin to compare/i)).toBeNull();
    expect(screen.queryByText(/coming soon/i)).toBeNull();
  });

  it("Copy node ID writes node.nodeKey (not node.id) — spec §10.2 V2 forward-compat", () => {
    const n = makeNode({ id: "uuid-1", nodeKey: "model:ols_1" });
    renderMenu(n);
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByText("Copy node ID"));
    expect(writeText).toHaveBeenCalledWith("model:ols_1");
  });

  it("Copy as JSON writes pretty-printed node.raw", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByText("Copy as JSON"));
    const written = writeText.mock.calls[0][0] as string;
    expect(written).toContain('"id": "model:ols_1"');
    expect(written).toContain("\n");
  });

  it("View Raw JSON fires onShowJson", () => {
    const onShow = vi.fn();
    renderMenu(makeNode(), onShow);
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByText("View Raw JSON"));
    expect(onShow).toHaveBeenCalledTimes(1);
  });

  it("Copy lineage path writes buildBranchPath result", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByText("Copy lineage path"));
    const written = writeText.mock.calls[0][0] as string;
    expect(written).toContain("Cleaned");
    expect(written).toContain("Primary OLS");
  });

  it("clicking any menuitem closes the menu", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByText("Copy node ID"));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("clicking outside the menu closes it", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("clicking inside the portal-rendered popup does NOT close it (REV-3 F1)", () => {
    // Pre-portal the popup lived inside the wrapper, so wrapper.contains
    // covered both. After F1 the popup is in document.body — the
    // outside-click handler must check the popup ref explicitly or
    // every menuitem mousedown would close the menu before its click
    // fires.
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    const popup = screen.getByTestId("node-action-menu-popup");
    fireEvent.mouseDown(popup);
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("popup is portaled to document.body, not nested in the wrapper (REV-3 F1)", () => {
    // Step 8 mounts NodeActionMenu inside React Flow node containers
    // which have overflow:hidden and their own stacking context. The
    // popup must live outside that subtree to escape clipping.
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    const wrapper = screen.getByTestId("node-action-menu");
    const popup = screen.getByTestId("node-action-menu-popup");
    expect(wrapper.contains(popup)).toBe(false);
    expect(document.body.contains(popup)).toBe(true);
  });

  it("scroll closes the menu", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.scroll(window);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("Escape closes the menu", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("toggle aria-expanded reflects open state", () => {
    renderMenu(makeNode());
    const btn = screen.getByRole("button", { name: /node actions/i });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });

  it("forks a draft in-graph (no navigation) via onForkDraft", async () => {
    const navigate = vi.fn();
    const onForkDraft = vi.fn();
    const seed = makeOwnerResolutionSeedFixture();
    const selected = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
    vi.mocked(useNavigate).mockReturnValue(navigate);
    vi.spyOn(api, "createPipelineDraftFromNode").mockResolvedValue({
      draft: { draft_id: "draft_1" } as any,
      draft_hash: "h1",
    });

    render(
      <MemoryRouter>
        <ForestContext.Provider
          value={{
            forest: seed.forest,
            activeRunId: "run_a",
            setActiveRunId: vi.fn(),
          }}
        >
          <NodeOperationContextProvider node={selected}>
            <NodeActionMenu
              node={selected}
              model={seed.graphModel}
              onShowJson={vi.fn()}
              projectRoot="/tmp/project"
              onForkDraft={onForkDraft}
            />
          </NodeOperationContextProvider>
        </ForestContext.Provider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /fork draft here/i }));

    await waitFor(() =>
      expect(api.createPipelineDraftFromNode).toHaveBeenCalledWith(
        "/tmp/project",
        expect.objectContaining({
          source_forest_node_key: seed.sharedNodeKey,
          source_op_node_id: seed.sharedOpNodeId,
        }),
      ),
    );
    await waitFor(() =>
      expect(onForkDraft).toHaveBeenCalledWith({
        draft: { draft_id: "draft_1" },
        draft_hash: "h1",
      }),
    );
    expect(navigate).not.toHaveBeenCalled();
  });

  it("uses ProjectRootProvider on slug routes when no projectRoot prop or query exists", async () => {
    const seed = makeOwnerResolutionSeedFixture();
    const selected = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;

    render(
      <MemoryRouter initialEntries={["/p/slug/graph"]}>
        <ProjectRootProvider projectRoot="/tmp/from-context">
          <ForestContext.Provider
            value={{
              forest: seed.forest,
              activeRunId: "run_a",
              setActiveRunId: vi.fn(),
            }}
          >
            <NodeOperationContextProvider node={selected}>
              <NodeActionMenu
                node={selected}
                model={seed.graphModel}
                onShowJson={vi.fn()}
              />
            </NodeOperationContextProvider>
          </ForestContext.Provider>
        </ProjectRootProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));

    expect(screen.getByRole("menuitem", { name: /fork draft here/i })).toBeInTheDocument();
  });
});
