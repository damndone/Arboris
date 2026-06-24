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
      { runId: "a", headNodeHash: "M1", fromNode: null, rerunOf: null,
        rerunReason: null, status: "completed", createdAt: null },
      { runId: "b", headNodeHash: "M2", fromNode: "model:ols_1", rerunOf: "a",
        rerunReason: "manual_override", status: "completed", createdAt: null },
    ],
  };
}

describe("forest rollback (non-mutating active-head selection)", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response),
    );
    // NB: only stub fetch — do NOT unstubAllGlobals in teardown, that would also
    // wipe the ResizeObserver/DOMRect mocks vitest.setup.ts installs for ReactFlow.
    vi.stubGlobal("fetch", fetchSpy);
  });

  it("switching to an ancestor head performs NO backend call and does not mutate the forest", () => {
    const data = forest();
    const snapshot = JSON.parse(JSON.stringify(data));
    const onRerun = vi.fn();
    render(<ForestCanvas forest={data} projectRoot="/p" runId="b" onRerun={onRerun} />);

    // Roll back to ancestor head `a` — active head flips.
    fireEvent.click(screen.getByTestId("forest-head-a"));
    expect(screen.getByTestId("forest-head-a").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("forest-head-b").getAttribute("aria-pressed")).toBe("false");

    // Rollback is pure view state: NO mutation.
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(onRerun).not.toHaveBeenCalled();
    // Immutable runs intact: the forest data object is untouched.
    expect(data).toEqual(snapshot);
  });

  it("rollback is reversible — re-selecting the head restores its active state", () => {
    render(<ForestCanvas forest={forest()} projectRoot="/p" runId="b" />);
    fireEvent.click(screen.getByTestId("forest-head-a"));
    fireEvent.click(screen.getByTestId("forest-head-b"));
    expect(screen.getByTestId("forest-head-b").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("forest-head-a").getAttribute("aria-pressed")).toBe("false");
  });
});
