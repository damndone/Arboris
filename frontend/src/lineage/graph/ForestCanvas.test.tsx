import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { ForestCanvas } from "./ForestCanvas";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";

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

// raw → C → {M1, M2}. C is shared by both runs; M1 only run_a, M2 only run_b.
function forest(): ForestViewModel {
  return {
    schemaVersion: 4,
    legacy: false,
    nodes: [
      node({ id: "raw", stage: "source", title: "Raw", runs: ["run_a", "run_b"] }),
      node({ id: "C", stage: "clean", title: "Cleaned", producingStage: "cleaning",
        runs: ["run_a", "run_b"] }),
      node({ id: "M1", stage: "model", title: "OLS robust", producingStage: "estimation",
        runs: ["run_a"] }),
      node({ id: "M2", stage: "model", title: "OLS unadjusted", producingStage: "estimation",
        runs: ["run_b"] }),
    ],
    edges: [
      { id: "raw->C", source: "raw", target: "C" },
      { id: "C->M1", source: "C", target: "M1" },
      { id: "C->M2", source: "C", target: "M2" },
    ],
    heads: [
      { runId: "run_a", headNodeHash: "M1", fromNode: null, rerunOf: null,
        rerunReason: null, status: "completed", createdAt: "2026-06-23T00:00:00Z" },
      { runId: "run_b", headNodeHash: "M2", fromNode: "model:ols_1", rerunOf: "run_a",
        rerunReason: "manual_override", status: "completed", createdAt: "2026-06-23T01:00:00Z" },
    ],
  };
}

function renderForest(over: Partial<React.ComponentProps<typeof ForestCanvas>> = {}) {
  return render(
    <ForestCanvas
      forest={forest()}
      projectRoot="/p"
      runId="run_b"
      onRerun={vi.fn()}
      {...over}
    />,
  );
}

describe("ForestCanvas", () => {
  it("dedups shared prefix to a single DOM node and branches the siblings", () => {
    renderForest();
    expect(screen.getAllByTestId("forest-node-C")).toHaveLength(1);
    expect(screen.getAllByTestId("forest-node-M1")).toHaveLength(1);
    expect(screen.getAllByTestId("forest-node-M2")).toHaveLength(1);
  });

  it("highlights the active head's lineage and switches on head select (rollback)", () => {
    renderForest({ runId: "run_b" });
    // run_b active: C + M2 active, M1 inactive.
    expect(screen.getByTestId("forest-node-M2").dataset.active).toBe("true");
    expect(screen.getByTestId("forest-node-M1").dataset.active).toBe("false");
    expect(screen.getByTestId("forest-node-C").dataset.active).toBe("true");

    // Switch active head to the ancestor run_a — pure view state (rollback).
    fireEvent.click(screen.getByTestId("forest-head-run_a"));
    expect(screen.getByTestId("forest-node-M1").dataset.active).toBe("true");
    expect(screen.getByTestId("forest-node-M2").dataset.active).toBe("false");
    expect(screen.getByTestId("forest-node-C").dataset.active).toBe("true");
  });

  it("selecting a node shows its upstream trace (root → node)", () => {
    renderForest();
    fireEvent.click(screen.getByTestId("forest-node-M2"));
    const trace = screen.getByTestId("forest-trace");
    expect(within(trace).getAllByTestId(/forest-trace-step-/).map((e) => e.textContent)).toEqual([
      "raw",
      "C",
      "M2",
    ]);
  });
});
