// frontend/src/lineage/detail/sections/LineageChainSection.test.tsx
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LineageChainSection } from "./LineageChainSection";
import { LineageContext, type LineageContextValue } from "../../LineageContext";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../../api/graphViewTypes";

function makeNode(
  id: string,
  overrides: Partial<GraphViewNode> = {},
): GraphViewNode {
  return {
    id,
    nodeKey: id,
    raw: null,
    stage: "model",
    kind: "model",
    title: id,
    summary: id,
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

function makeModel(
  nodes: GraphViewNode[],
  edges: Array<{ id: string; source: string; target: string }> = [],
): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "run-1",
    legacy: false,
    nodes,
    edges: edges.map((e) => ({
      ...e,
      reversible: false,
      inverseOp: null,
    })),
    stats: {
      nodeCount: nodes.length,
      edgeCount: edges.length,
      leafCount: 0,
      hasDpCount: 0,
    },
  };
}

function renderSection(model: GraphViewModel, node: GraphViewNode) {
  const ctx: LineageContextValue = { model, selectedKey: node.id, select: vi.fn() };
  return render(
    <LineageContext.Provider value={ctx}>
      <LineageChainSection node={node} />
    </LineageContext.Provider>,
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
  vi.useRealTimers();
});

describe("LineageChainSection", () => {
  it("3-node chain renders all three node identifiers/summaries", () => {
    const raw = makeNode("stage:raw", { kind: "dataset_stage", summary: "Raw" });
    const cleaned = makeNode("stage:cleaned", {
      kind: "dataset_stage",
      summary: "Cleaned",
    });
    const model = makeNode("model:ols_1", { kind: "model", summary: "OLS · n=10" });
    const m = makeModel(
      [raw, cleaned, model],
      [
        { id: "e1", source: "stage:raw", target: "stage:cleaned" },
        { id: "e2", source: "stage:cleaned", target: "model:ols_1" },
      ],
    );

    renderSection(m, model);
    const path = screen.getByTestId("lineage-chain-path").textContent ?? "";
    // pathBuilder joins with arrows; assert each node appears in order.
    expect(path).toContain("Raw");
    expect(path).toContain("Cleaned");
    expect(path).toContain("OLS · n=10");
    expect(path.indexOf("Raw")).toBeLessThan(path.indexOf("Cleaned"));
    expect(path.indexOf("Cleaned")).toBeLessThan(path.indexOf("OLS"));
  });

  it("isolated node (no incoming edges) shows the empty-path placeholder", () => {
    const node = makeNode("model:ols_1");
    const m = makeModel([node]);
    renderSection(m, node);
    expect(screen.getByText("(no upstream nodes)")).toBeInTheDocument();
  });

  it("copy button writes buildBranchPath result to navigator.clipboard", async () => {
    const raw = makeNode("stage:raw", { summary: "Raw" });
    const target = makeNode("model:ols_1", { summary: "OLS" });
    const m = makeModel(
      [raw, target],
      [{ id: "e1", source: "stage:raw", target: "model:ols_1" }],
    );
    renderSection(m, target);

    fireEvent.click(screen.getByRole("button", { name: /copy lineage path/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const written = writeText.mock.calls[0][0] as string;
    expect(written).toContain("Raw");
    expect(written).toContain("OLS");
  });

  it("copy flash text reverts after the timeout", async () => {
    vi.useFakeTimers();
    const raw = makeNode("stage:raw", { summary: "Raw" });
    const target = makeNode("model:ols_1", { summary: "OLS" });
    const m = makeModel(
      [raw, target],
      [{ id: "e1", source: "stage:raw", target: "model:ols_1" }],
    );
    renderSection(m, target);

    fireEvent.click(screen.getByRole("button", { name: /copy lineage path/i }));
    // Wait for the promise + state flip in real-event mode.
    await vi.waitFor(() =>
      expect(screen.getByText(/✓ copied/i)).toBeInTheDocument(),
    );
    vi.advanceTimersByTime(1600);
    await vi.waitFor(() =>
      expect(screen.queryByText(/✓ copied/i)).toBeNull(),
    );
  });

  it("copy button is disabled when path is empty (isolated node)", () => {
    const node = makeNode("model:ols_1");
    const m = makeModel([node]);
    renderSection(m, node);
    expect(
      screen.getByRole("button", { name: /copy lineage path/i }),
    ).toBeDisabled();
  });

  it("clipboard rejection is swallowed (no console errors)", async () => {
    writeText.mockRejectedValueOnce(new Error("permission denied"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const raw = makeNode("stage:raw");
    const target = makeNode("model:ols_1");
    const m = makeModel(
      [raw, target],
      [{ id: "e1", source: "stage:raw", target: "model:ols_1" }],
    );
    renderSection(m, target);

    fireEvent.click(screen.getByRole("button", { name: /copy lineage path/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});
