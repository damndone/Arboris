import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ForestCanvas } from "./ForestCanvas";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";

function node(id: string, runs: string[]): HeadSetNode {
  return {
    id, nodeKey: id, opNodeId: id, raw: {}, stage: "clean", kind: "k", title: id,
    parentStageId: null, trust: "ok", decisions: [], nodeHash: id,
    producingStage: null, casRef: null, runs,
  };
}

function forest(): ForestViewModel {
  return {
    schemaVersion: 4,
    legacy: false,
    nodes: [node("C", ["a", "b"]), node("M1", ["a"]), node("M2", ["b"])],
    edges: [
      { id: "C->M1", source: "C", target: "M1" },
      { id: "C->M2", source: "C", target: "M2" },
    ],
    heads: [
      { runId: "a", headNodeHash: "M1", fromNode: null, rerunOf: null, rerunReason: null, status: "completed", createdAt: null },
      { runId: "b", headNodeHash: "M2", fromNode: "model:ols_1", rerunOf: "a", rerunReason: "manual_override", status: "completed", createdAt: null },
    ],
  };
}

describe("forest rollback (non-mutating active-head selection)", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchSpy = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response),
    );
    // Only stub fetch — do NOT unstubAllGlobals (that wipes the setup's
    // ResizeObserver/DOMRect mocks ReactFlow needs).
    vi.stubGlobal("fetch", fetchSpy);
  });

  it("selecting a head emits onActiveHead and performs NO backend call (rollback = view-state)", () => {
    const data = forest();
    const snapshot = JSON.parse(JSON.stringify(data));
    const onActiveHead = vi.fn();
    render(
      <ForestCanvas
        forest={data}
        selectedNodeId={null}
        onSelect={vi.fn()}
        activeRunId="b"
        onActiveHead={onActiveHead}
      />,
    );
    fireEvent.click(screen.getByTestId("forest-head-a"));
    expect(onActiveHead).toHaveBeenCalledWith("a");
    expect(fetchSpy).not.toHaveBeenCalled();
    // The forest data object is never mutated by a rollback.
    expect(data).toEqual(snapshot);
  });

  it("the active head prop drives which version is marked active", () => {
    const { rerender } = render(
      <ForestCanvas forest={forest()} selectedNodeId={null} onSelect={vi.fn()} activeRunId="a" onActiveHead={vi.fn()} />,
    );
    expect(screen.getByTestId("forest-head-a").getAttribute("aria-pressed")).toBe("true");
    rerender(
      <ForestCanvas forest={forest()} selectedNodeId={null} onSelect={vi.fn()} activeRunId="b" onActiveHead={vi.fn()} />,
    );
    expect(screen.getByTestId("forest-head-b").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("forest-head-a").getAttribute("aria-pressed")).toBe("false");
  });
});
