import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HeadSetNode } from "../api/graphViewTypes";
import type { CompareState } from "./CompareContext";
import { CompareNodesSection } from "./CompareNodesSection";

const mockCompare = vi.hoisted(() => ({ current: null as CompareState | null }));
const mockForest = vi.hoisted(() => ({
  current: { forest: { nodes: [], edges: [], heads: [] }, activeRunId: "run1" } as unknown,
}));
const mockResolve = vi.hoisted(() => ({
  current: (() => ({ ok: false })) as (input: unknown) => unknown,
}));

vi.mock("./CompareContext", () => ({
  useCompareOptional: () => mockCompare.current,
}));
vi.mock("../../workbench/ForestContext", () => ({
  useForest: () => mockForest.current,
}));
vi.mock("../api/nodeOperationContext", () => ({
  resolveNodeOperationContext: (input: unknown) => mockResolve.current(input),
}));

function makeCompare(overrides: Partial<CompareState> = {}): CompareState {
  return {
    pickingFromKey: null,
    pair: null,
    startPick: vi.fn(),
    cancelPick: vi.fn(),
    handleCanvasSelect: vi.fn(() => false),
    swap: vi.fn(),
    clear: vi.fn(),
    ...overrides,
  };
}

const node = {
  nodeKey: "key-a",
  title: "ols_robust (primary)",
  runs: ["run1"],
} as unknown as HeadSetNode;

function contextFor(key: string, params: Record<string, unknown>) {
  return {
    ok: true,
    context: {
      context_version: "node-operation-context/v1",
      context_fingerprint: `${key}:fp`,
      selection: {
        forest_node_key: key,
        node_hash: `${key}:hash`,
        display_label: key,
        kind: "model",
        stage: "model",
      },
      ownership: { owner_run_id: "run1" },
      lineage_context: { path_run_id: "run1", upstream_path: [] },
      node_payload: { decisions: [], artifacts: [], editable_schema: null, params },
    },
  };
}

describe("CompareNodesSection", () => {
  beforeEach(() => {
    mockCompare.current = makeCompare();
    mockForest.current = {
      forest: { nodes: [], edges: [], heads: [] },
      activeRunId: "run1",
    } as unknown;
    mockResolve.current = () => ({ ok: false });
  });

  it("renders nothing without the provider", () => {
    mockCompare.current = null;
    const { container } = render(<CompareNodesSection node={node} />);
    expect(container.innerHTML).toBe("");
  });

  it("idle: offers the pick action and starts a pick from this node", () => {
    render(<CompareNodesSection node={node} />);
    const button = screen.getByRole("button", { name: /compare with another node/i });
    fireEvent.click(button);
    expect(mockCompare.current!.startPick).toHaveBeenCalledWith("key-a");
  });

  it("picking from this node: shows the hint with a cancel action", () => {
    mockCompare.current = makeCompare({ pickingFromKey: "key-a" });
    render(<CompareNodesSection node={node} />);
    expect(screen.getByTestId("compare-picking-hint")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(mockCompare.current!.cancelPick).toHaveBeenCalled();
  });

  it("pair including this node: renders the diff with swap/clear", () => {
    mockCompare.current = makeCompare({ pair: { anchorKey: "key-a", targetKey: "key-b" } });
    mockResolve.current = (input) => {
      const key = (input as { selected_forest_node_key: string }).selected_forest_node_key;
      return contextFor(key, key === "key-a" ? { covariance: "HC1" } : { covariance: "clustered" });
    };
    render(<CompareNodesSection node={node} />);
    expect(screen.getByTestId("compare-diff-view")).toBeInTheDocument();
    expect(screen.getByText(/1 difference/)).toBeInTheDocument();
    expect(screen.getByText("HC1")).toBeInTheDocument();
    expect(screen.getByText("clustered")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /swap sides/i }));
    expect(mockCompare.current!.swap).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(mockCompare.current!.clear).toHaveBeenCalled();
  });

  it("resolves a shared target through the active run's nearest ancestor", () => {
    mockCompare.current = makeCompare({
      pair: { anchorKey: "key-a", targetKey: "key-b" },
    });
    mockForest.current = {
      forest: {
        nodes: [
          { nodeKey: "key-a", runs: ["run_child"] },
          { nodeKey: "key-b", runs: ["run_parent", "unrelated_root"] },
        ],
        edges: [],
        heads: [
          { runId: "run_child", rerunOf: "run_parent" },
          { runId: "run_parent", rerunOf: "run_root" },
          { runId: "run_root", rerunOf: null },
          { runId: "unrelated_root", rerunOf: null },
        ],
      },
      activeRunId: "run_child",
    } as unknown;
    const inputs: Array<Record<string, unknown>> = [];
    mockResolve.current = (input) => {
      const typed = input as Record<string, unknown>;
      inputs.push(typed);
      return contextFor(String(typed.selected_forest_node_key), {});
    };

    render(<CompareNodesSection node={node} />);

    expect(inputs.find((input) => input.selected_forest_node_key === "key-b")).toMatchObject({
      selected_run_hint: "run_parent",
      selected_run_hint_source: "manual_candidate_selection",
    });
  });

  it("pair not involving this node: falls back to the idle action", () => {
    mockCompare.current = makeCompare({ pair: { anchorKey: "x", targetKey: "y" } });
    render(<CompareNodesSection node={node} />);
    expect(screen.getByRole("button", { name: /compare with another node/i })).toBeInTheDocument();
  });

  it("unresolvable side: honest error with a clear action", () => {
    mockCompare.current = makeCompare({ pair: { anchorKey: "key-a", targetKey: "gone" } });
    mockResolve.current = (input) => {
      const key = (input as { selected_forest_node_key: string }).selected_forest_node_key;
      return key === "key-a" ? contextFor(key, {}) : { ok: false };
    };
    render(<CompareNodesSection node={node} />);
    expect(screen.getByTestId("compare-unresolvable")).toBeInTheDocument();
  });
});
