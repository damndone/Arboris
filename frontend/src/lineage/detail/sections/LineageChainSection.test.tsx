// frontend/src/lineage/detail/sections/LineageChainSection.test.tsx
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LineageChainSection } from "./LineageChainSection";
import { ForestContext } from "../../../workbench/ForestContext";
import { NodeOperationContextProvider } from "../NodeOperationContextProvider";
import { LineageContext, type LineageContextValue } from "../../LineageContext";
import type {
  ForestViewModel,
  GraphViewModel,
  GraphViewNode,
  HeadSetNode,
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

function makeHeadNode(
  nodeKey: string,
  runs: string[],
  overrides: Partial<HeadSetNode> = {},
): HeadSetNode {
  return {
    id: nodeKey,
    nodeKey,
    raw: null,
    stage: "model",
    kind: "model",
    title: nodeKey,
    summary: nodeKey,
    parentStageId: null,
    trust: "ok",
    decisions: [],
    opNodeId: `op:${nodeKey}`,
    nodeHash: nodeKey,
    producingStage: "model",
    casRef: null,
    runs,
    ...overrides,
  };
}

function makeOwnerPathFixture(activeRunId: string = "run_c"): {
  forest: ForestViewModel;
  graphModel: GraphViewModel;
  selected: HeadSetNode;
  activeRunId: string;
} {
  const runAOnly = makeHeadNode("raw_a", ["run_a"], {
    title: "Run A raw",
    summary: "Run A raw",
    kind: "dataset_stage",
    stage: "source",
    producingStage: "source",
  });
  const runCOnly = makeHeadNode("raw_c", ["run_c"], {
    title: "Run C raw",
    summary: "Run C raw",
    kind: "dataset_stage",
    stage: "source",
    producingStage: "source",
  });
  const shared = makeHeadNode("shared_model", ["run_a", "run_c"], {
    title: "Shared model",
    summary: "Shared model",
  });
  const edges = [
    { id: "a-to-shared", source: "raw_a", target: "shared_model" },
    { id: "c-to-shared", source: "raw_c", target: "shared_model" },
  ];
  const forest: ForestViewModel = {
    schemaVersion: 2,
    legacy: false,
    nodes: [runAOnly, runCOnly, shared],
    edges,
    heads: [
      {
        runId: "run_a",
        headNodeHash: shared.nodeHash,
        fromNode: null,
        rerunOf: null,
        rerunReason: null,
        status: "completed",
        createdAt: "2026-06-27T00:00:00Z",
      },
      {
        runId: "run_c",
        headNodeHash: shared.nodeHash,
        fromNode: null,
        rerunOf: "run_a",
        rerunReason: "manual_override",
        status: "completed",
        createdAt: "2026-06-27T00:01:00Z",
      },
    ],
  };
  return {
    forest,
    graphModel: {
      schemaVersion: 2,
      runId: "run_c",
      legacy: false,
      nodes: forest.nodes,
      edges: forest.edges,
      stats: {
        nodeCount: forest.nodes.length,
        edgeCount: forest.edges.length,
        leafCount: 1,
        hasDpCount: 0,
      },
    },
    selected: shared,
    activeRunId,
  };
}

function renderSectionWithNodeContext(fixture: ReturnType<typeof makeOwnerPathFixture>) {
  const ctx: LineageContextValue = {
    model: fixture.graphModel,
    selectedKey: fixture.selected.nodeKey,
    select: vi.fn(),
  };
  return render(
    <ForestContext.Provider
      value={{
        forest: fixture.forest,
        activeRunId: fixture.activeRunId,
        setActiveRunId: vi.fn(),
      }}
    >
      <LineageContext.Provider value={ctx}>
        <NodeOperationContextProvider node={fixture.selected}>
          <LineageChainSection node={fixture.selected} />
        </NodeOperationContextProvider>
      </LineageContext.Provider>
    </ForestContext.Provider>,
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
    // V1.5.2 P6: lineage chain is now a clickable chip strip per
    // plan §9 Layer 2. Each ancestor renders as its own chip with
    // data-testid="lineage-chip-<nodeKey>". Order in the DOM matches
    // ancestry order; the target chip carries data-active="true".
    const chips = screen.getByTestId("lineage-chain-chips");
    const rawChip = screen.getByTestId("lineage-chip-stage:raw");
    const cleanedChip = screen.getByTestId("lineage-chip-stage:cleaned");
    const targetChip = screen.getByTestId("lineage-chip-model:ols_1");
    expect(chips).toContainElement(rawChip);
    expect(chips).toContainElement(cleanedChip);
    expect(chips).toContainElement(targetChip);
    expect(targetChip.getAttribute("data-active")).toBe("true");
    // Chip labels show the node title.
    expect(rawChip.textContent).toBe("Raw");
    expect(cleanedChip.textContent).toBe("Cleaned");
    // DOM order encodes ancestry: raw first, target last.
    const ids = Array.from(chips.querySelectorAll("[data-testid^='lineage-chip-']")).map(
      (el) => el.getAttribute("data-testid"),
    );
    expect(ids).toEqual([
      "lineage-chip-stage:raw",
      "lineage-chip-stage:cleaned",
      "lineage-chip-model:ols_1",
    ]);
  });

  it("isolated node (no incoming edges) shows the empty-path placeholder", () => {
    const node = makeNode("model:ols_1");
    const m = makeModel([node]);
    renderSection(m, node);
    expect(screen.getByText("(no upstream nodes)")).toBeInTheDocument();
  });

  // V1.5.2 P6 — chip is interactive per plan §9 Layer 2.
  it("chip click calls useLineage().select with the chip's nodeKey", () => {
    const raw = makeNode("stage:raw", {
      kind: "dataset_stage",
      summary: "Raw",
    });
    const target = makeNode("model:ols_1", {
      kind: "model",
      summary: "OLS",
    });
    const m = makeModel(
      [raw, target],
      [{ id: "e1", source: "stage:raw", target: "model:ols_1" }],
    );
    const select = vi.fn();
    const ctx: LineageContextValue = {
      model: m,
      selectedKey: "model:ols_1",
      select,
    };
    render(
      <LineageContext.Provider value={ctx}>
        <LineageChainSection node={target} />
      </LineageContext.Provider>,
    );

    fireEvent.click(screen.getByTestId("lineage-chip-stage:raw"));
    expect(select).toHaveBeenCalledWith("stage:raw");
  });

  it("clicking the active (target) chip does NOT call select", () => {
    const raw = makeNode("stage:raw", {
      kind: "dataset_stage",
      summary: "Raw",
    });
    const target = makeNode("model:ols_1", {
      kind: "model",
      summary: "OLS",
    });
    const m = makeModel(
      [raw, target],
      [{ id: "e1", source: "stage:raw", target: "model:ols_1" }],
    );
    const select = vi.fn();
    const ctx: LineageContextValue = {
      model: m,
      selectedKey: "model:ols_1",
      select,
    };
    render(
      <LineageContext.Provider value={ctx}>
        <LineageChainSection node={target} />
      </LineageContext.Provider>,
    );

    fireEvent.click(screen.getByTestId("lineage-chip-model:ols_1"));
    expect(select).not.toHaveBeenCalled();
  });

  it("copy button writes buildBranchPath result to navigator.clipboard", async () => {
    const raw = makeNode("stage:raw", { summary: "Raw" });
    const target = makeNode("model:ols_1", { summary: "OLS" });
    const m = makeModel(
      [raw, target],
      [{ id: "e1", source: "stage:raw", target: "model:ols_1" }],
    );
    renderSection(m, target);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy lineage path/i }));
    });
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

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy lineage path/i }));
      await Promise.resolve();
    });
    expect(screen.getByText(/✓ copied/i)).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(1600);
      await Promise.resolve();
    });
    expect(screen.queryByText(/✓ copied/i)).toBeNull();
  });

  it("copy button is disabled when path is empty (isolated node)", () => {
    const node = makeNode("model:ols_1");
    const m = makeModel([node]);
    renderSection(m, node);
    expect(
      screen.getByRole("button", { name: /copy lineage path/i }),
    ).toBeDisabled();
  });

  it("uses the owner-run upstream path from NodeOperationContext when available", () => {
    renderSectionWithNodeContext(makeOwnerPathFixture("run_c"));
    expect(screen.queryByTestId("lineage-chip-raw_a")).toBeNull();
    expect(screen.getByTestId("lineage-chip-raw_c")).toBeInTheDocument();
    expect(screen.getByTestId("lineage-chip-shared_model")).toBeInTheDocument();
  });

  it("does not render an owner-run path when context resolution fails", () => {
    renderSectionWithNodeContext(makeOwnerPathFixture("run_x"));
    expect(screen.queryByTestId("lineage-chain-chips")).toBeNull();
    expect(screen.getByTestId("lineage-chain-empty")).toBeInTheDocument();
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
