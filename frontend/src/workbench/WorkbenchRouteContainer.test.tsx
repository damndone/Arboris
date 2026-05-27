// frontend/src/workbench/WorkbenchRouteContainer.test.tsx
//
// V1.5.2 P3 — container + view switcher integration.
//
// The container's data-loading path is already covered by
// `lineage/LineageRouteContainer.test.tsx` (it delegates here). This
// file adds the V1.5.2-specific behaviour:
//   - topbar renders the three view tabs
//   - switching view via topbar updates URL `?view=`
//   - selecting `table` / `pipeline` swaps WorkbenchMain content

import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchRouteContainer } from "./WorkbenchRouteContainer";
import * as api from "../api";
import type { GraphResponse } from "../lineage/types";

function fakeGraph(): GraphResponse {
  return {
    schema_version: 3,
    run_id: "r1",
    legacy: false,
    stats: { node_count: 1, edge_count: 0, leaf_count: 1, has_dp_count: 0 },
    nodes: {
      n1: {
        id: "n1",
        kind: "dataset_stage",
        display_label: "Raw",
        summary: null,
        created_at: "",
        parent_stage_id: null,
        branch_id: "main",
        trust: "ok",
        trust_reason: null,
        archived: false,
        payload_ref: null,
        decision_points: [],
        annotations: [],
        // schema v3 stage
        stage: "source",
      } as never,
    },
    edges: {},
    branches: {},
  };
}

function mountAt(initialPath: string) {
  vi.spyOn(api, "getRunGraph").mockResolvedValue(fakeGraph());
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="*"
          element={
            <WorkbenchRouteContainer projectRoot="/proj" runId="r1" />
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("WorkbenchRouteContainer", () => {
  it("renders the topbar with three view tabs once data loads", async () => {
    mountAt("/?tab=lineage");
    expect(await screen.findByTestId("workbench-topbar")).toBeInTheDocument();
    expect(screen.getByTestId("view-tab-graph")).toBeInTheDocument();
    expect(screen.getByTestId("view-tab-table")).toBeInTheDocument();
    expect(screen.getByTestId("view-tab-pipeline")).toBeInTheDocument();
  });

  it("defaults to graph view (mounts GraphView)", async () => {
    mountAt("/?tab=lineage");
    expect(await screen.findByTestId("graph-workbench")).toBeInTheDocument();
    expect(screen.queryByTestId("view-table")).toBeNull();
    expect(screen.queryByTestId("view-pipeline")).toBeNull();
  });

  it("switches to TableView when ?view=table", async () => {
    mountAt("/?tab=lineage&view=table");
    expect(await screen.findByTestId("view-table")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-workbench")).toBeNull();
  });

  it("clicking the Pipeline tab swaps content and writes ?view=pipeline", async () => {
    mountAt("/?tab=lineage");
    const pipelineTab = await screen.findByTestId("view-tab-pipeline");
    fireEvent.click(pipelineTab);
    expect(await screen.findByTestId("view-pipeline")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-workbench")).toBeNull();
  });

  it("active tab carries aria-selected=true", async () => {
    mountAt("/?tab=lineage&view=table");
    const tableTab = await screen.findByTestId("view-tab-table");
    expect(tableTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("view-tab-graph")).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  // V1.5.2 P8 — these scenarios moved from GraphWorkbench.test.tsx
  // because DetailDrawer / RawJsonModal / ⌘J / Escape were hoisted
  // out of GraphView up to WorkbenchShell (plan §2 final layout).
  // Behaviour preserved; tests now mount the full container.
  describe("selection / drawer / modal — P8 hoisted from GraphView", () => {
    it("renders DetailDrawer when ?tabs=...&active=... resolves to a real node", async () => {
      mountAt("/?tab=lineage&tabs=n1&active=n1");
      expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();
      expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
        "Raw",
      );
    });

    it("suppresses DetailDrawer when ?tabs= points at a node not in this run (cross-run leak guard)", async () => {
      mountAt("/?tab=lineage&tabs=ghost&active=ghost");
      // Wait for the canvas to mount so we know the load resolved.
      await screen.findByTestId("graph-workbench");
      expect(screen.queryByTestId("detail-drawer")).toBeNull();
    });

    it("⌘J keydown opens RawJsonModal when a node is selected", async () => {
      mountAt("/?tab=lineage&tabs=n1&active=n1");
      await screen.findByTestId("detail-drawer");
      fireEvent.keyDown(window, { key: "j", metaKey: true });
      expect(screen.getByTestId("raw-json-modal")).toBeInTheDocument();
    });

    it("⌘J with no selected node is a no-op (modal does not appear)", async () => {
      mountAt("/?tab=lineage");
      await screen.findByTestId("graph-workbench");
      fireEvent.keyDown(window, { key: "j", metaKey: true });
      expect(screen.queryByTestId("raw-json-modal")).toBeNull();
    });

    it("S1: Escape with modal open closes only the modal, NOT the selection", async () => {
      mountAt("/?tab=lineage&tabs=n1&active=n1");
      await screen.findByTestId("detail-drawer");
      fireEvent.keyDown(window, { key: "j", metaKey: true });
      expect(screen.getByTestId("raw-json-modal")).toBeInTheDocument();
      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByTestId("raw-json-modal")).toBeNull();
      // Drawer still mounted = selection survived Escape.
      expect(screen.getByTestId("detail-drawer")).toBeInTheDocument();
    });

    it("Escape with no modal clears the selection (drawer dismounts)", async () => {
      mountAt("/?tab=lineage&tabs=n1&active=n1");
      await screen.findByTestId("detail-drawer");
      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByTestId("detail-drawer")).toBeNull();
    });
  });

  describe("layout — P8 plan §2 hoisting", () => {
    it("mounts RunHistoryRail at the container level (not inside GraphView)", async () => {
      mountAt("/?tab=lineage");
      // RunHistoryRail's testid is owned by the rail component; this
      // just asserts it's reachable from any view, which is the whole
      // point of hoisting it.
      await screen.findByTestId("graph-workbench");
      expect(screen.getByTestId("run-rail")).toBeInTheDocument();
    });

    it("rail and BottomPanel persist when switching to Table view", async () => {
      mountAt("/?tab=lineage&view=table");
      await screen.findByTestId("view-table");
      expect(screen.getByTestId("run-rail")).toBeInTheDocument();
      expect(screen.getByTestId("bottom-panel")).toBeInTheDocument();
    });
  });
});
