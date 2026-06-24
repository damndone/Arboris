import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ForestCanvas } from "./ForestCanvas";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";

// ReactFlow renders node content (titles) inline in jsdom; node-click selection is
// lifted to the shell and verified in the browser smoke. Here we assert structure:
// the real node boxes render, the shared prefix is deduped, and head chips drive the
// active head (rollback) as pure view-state via the onActiveHead callback.

function node(over: Partial<HeadSetNode> & { id: string }): HeadSetNode {
  return {
    nodeKey: over.id,
    opNodeId: over.id,
    raw: {},
    stage: "clean",
    kind: "dataset_stage",
    title: over.id,
    parentStageId: null,
    trust: "ok",
    decisions: [],
    nodeHash: over.id,
    producingStage: null,
    casRef: null,
    runs: [],
    ...over,
  };
}

function forest(): ForestViewModel {
  return {
    schemaVersion: 4,
    legacy: false,
    nodes: [
      node({ id: "raw", stage: "source", title: "Raw input data", runs: ["run_a", "run_b"] }),
      node({ id: "C", stage: "clean", title: "Cleaned data", producingStage: "cleaning", runs: ["run_a", "run_b"] }),
      node({ id: "M1", stage: "model", title: "OLS robust", producingStage: "estimation", runs: ["run_a"] }),
      node({ id: "M2", stage: "model", title: "OLS unadjusted", producingStage: "estimation", runs: ["run_b"] }),
    ],
    edges: [
      { id: "raw->C", source: "raw", target: "C" },
      { id: "C->M1", source: "C", target: "M1" },
      { id: "C->M2", source: "C", target: "M2" },
    ],
    heads: [
      { runId: "run_a", headNodeHash: "M1", fromNode: null, rerunOf: null, rerunReason: null, status: "completed", createdAt: null },
      { runId: "run_b", headNodeHash: "M2", fromNode: "model:ols_1", rerunOf: "run_a", rerunReason: "manual_override", status: "completed", createdAt: null },
    ],
  };
}

function renderForest(over: Partial<React.ComponentProps<typeof ForestCanvas>> = {}) {
  const onSelect = vi.fn();
  const onActiveHead = vi.fn();
  render(
    <ForestCanvas
      forest={forest()}
      selectedNodeId={null}
      onSelect={onSelect}
      activeRunId="run_b"
      onActiveHead={onActiveHead}
      {...over}
    />,
  );
  return { onSelect, onActiveHead };
}

describe("ForestCanvas", () => {
  it("renders every forest node once as a real box (shared prefix deduped)", () => {
    renderForest();
    expect(screen.getAllByText("Cleaned data")).toHaveLength(1);
    expect(screen.getAllByText("Raw input data")).toHaveLength(1);
    expect(screen.getByText("OLS robust")).toBeTruthy();
    expect(screen.getByText("OLS unadjusted")).toBeTruthy();
  });

  it("marks the active head and exposes the other as a rollback target", () => {
    renderForest({ activeRunId: "run_b" });
    expect(screen.getByTestId("forest-head-run_b").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("forest-head-run_a").getAttribute("aria-pressed")).toBe("false");
  });

  it("clicking a head fires onActiveHead (rollback is owned by the shell)", () => {
    const { onActiveHead } = renderForest({ activeRunId: "run_b" });
    fireEvent.click(screen.getByTestId("forest-head-run_a"));
    expect(onActiveHead).toHaveBeenCalledWith("run_a");
  });
});
