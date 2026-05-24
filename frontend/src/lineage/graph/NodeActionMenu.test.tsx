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
import { fireEvent, render, screen } from "@testing-library/react";
import { NodeActionMenu } from "./NodeActionMenu";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";

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
    <NodeActionMenu
      node={node}
      model={makeModel(node)}
      onShowJson={onShowJson}
    />,
  );
}

const writeText = vi.fn();
let _origClipboard: PropertyDescriptor | undefined;
beforeEach(() => {
  writeText.mockReset().mockResolvedValue(undefined);
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

  it("exposes exactly 4 menu items in spec §10.2 order", () => {
    renderMenu(makeNode());
    fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
    const items = screen.getAllByRole("menuitem");
    const labels = items.map(
      (el) => el.textContent?.trim().replace(/⌘.*$/, "").trim(),
    );
    expect(labels).toEqual([
      "Copy node ID",
      "Copy as JSON",
      "View Raw JSON",
      "Copy lineage path",
    ]);
  });

  it.each([
    ["Ask AI"],
    ["Rerun from this node"],
    ["Mark as bad decision"],
    ["Pin to compare"],
    ["Coming soon"],
  ] as const)(
    'reserved label "%s" is NOT in the DOM (spec §10.3)',
    (label) => {
      renderMenu(makeNode());
      fireEvent.click(screen.getByRole("button", { name: /node actions/i }));
      expect(screen.queryByText(new RegExp(label, "i"))).toBeNull();
    },
  );

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
});
