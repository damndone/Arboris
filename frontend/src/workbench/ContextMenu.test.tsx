import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LineageContext } from "../lineage/LineageContext";
import type { GraphViewModel } from "../lineage/api/graphViewTypes";
import { ContextMenu } from "./ContextMenu";
import {
  hideGraphNodeFromView,
  readHiddenGraphNodeIds,
  useWorkbench,
  WorkbenchStateProvider,
} from "./WorkbenchStateProvider";

const model: GraphViewModel = {
  schemaVersion: 3,
  runId: "run_context",
  legacy: false,
  nodes: [
    {
      id: "node_one",
      nodeKey: "node_one",
      raw: null,
      stage: "model",
      kind: "model",
      title: "Model",
      parentStageId: null,
      trust: "ok",
      decisions: [],
    },
  ],
  edges: [],
  stats: { nodeCount: 1, edgeCount: 0, leafCount: 1, hasDpCount: 0 },
};

function MenuTrigger({ nodeKey }: { nodeKey: string | null }) {
  const { dispatch } = useWorkbench();
  return (
    <button
      type="button"
      onClick={() => dispatch.openContextMenu({ nodeKey, x: 10, y: 10 })}
    >
      Open menu
    </button>
  );
}

function renderMenu(nodeKey: string | null) {
  return render(
    <MemoryRouter>
      <WorkbenchStateProvider runId={model.runId}>
        <LineageContext.Provider value={{ model, selectedKey: null, select: () => {} }}>
          <MenuTrigger nodeKey={nodeKey} />
          <ContextMenu />
        </LineageContext.Provider>
      </WorkbenchStateProvider>
    </MemoryRouter>,
  );
}

describe("ContextMenu graph cleanup", () => {
  it("moves Hide from this view into the node context menu", () => {
    sessionStorage.clear();
    renderMenu("node_one");

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.click(screen.getByTestId("context-menu-hide-from-view"));

    expect(readHiddenGraphNodeIds(model.runId)).toEqual(new Set(["node_one"]));
    expect(screen.queryByTestId("workbench-context-menu")).toBeNull();
  });

  it("offers restore from a blank-canvas context menu", () => {
    sessionStorage.clear();
    hideGraphNodeFromView(model.runId, "node_one");
    renderMenu(null);

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.click(screen.getByTestId("context-menu-restore-hidden"));

    expect(readHiddenGraphNodeIds(model.runId)).toEqual(new Set());
  });
});
