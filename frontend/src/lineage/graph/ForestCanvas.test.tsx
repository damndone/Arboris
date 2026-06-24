import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ForestCanvas } from "./ForestCanvas";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";

// ReactFlow renders node content (titles) inline in jsdom; node-click → trace/edit
// is interaction-heavy and verified in the browser smoke. Here we assert structure:
// the real node boxes render, the shared prefix is deduped, and head chips drive
// the active head (rollback) as pure view-state.

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

// raw → C → {M1, M2}; C shared by both runs, M1 only run_a, M2 only run_b.
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
  return render(
    <ForestCanvas forest={forest()} projectRoot="/p" runId="run_b" onRerun={vi.fn()} {...over} />,
  );
}

describe("ForestCanvas", () => {
  it("renders every forest node once as a real box (shared prefix deduped)", () => {
    renderForest();
    // Each title appears exactly once — the shared C is a single node.
    expect(screen.getAllByText("Cleaned data")).toHaveLength(1);
    expect(screen.getAllByText("Raw input data")).toHaveLength(1);
    // Both sibling model branches are present.
    expect(screen.getByText("OLS robust")).toBeTruthy();
    expect(screen.getByText("OLS unadjusted")).toBeTruthy();
  });

  it("defaults the active head to the viewed run", () => {
    renderForest({ runId: "run_b" });
    expect(screen.getByTestId("forest-head-run_b").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("forest-head-run_a").getAttribute("aria-pressed")).toBe("false");
  });

  it("switching the active head is pure view-state (rollback)", () => {
    renderForest({ runId: "run_b" });
    fireEvent.click(screen.getByTestId("forest-head-run_a"));
    expect(screen.getByTestId("forest-head-run_a").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("forest-head-run_b").getAttribute("aria-pressed")).toBe("false");
  });
});
