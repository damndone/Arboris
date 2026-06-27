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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchRouteContainer } from "./WorkbenchRouteContainer";
import * as api from "../api";
import type { GraphResponse } from "../lineage/types";
import type { HeadSetResponse } from "../lineage/api/graphViewTypes";

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
  // The graph view always tries the cross-run forest first; a legacy head-set makes it
  // fall back to the per-run graph (these tests exercise the shell, not the forest).
  vi.spyOn(api, "getRunGraphHeadSet").mockResolvedValue({ legacy: true } as never);
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

function forestResponse(focusKey = "hash_model"): HeadSetResponse {
  return {
    schema_version: 2,
    legacy: false,
    nodes: {
      hash_source: {
        id: "source:upload",
        kind: "dataset",
        display_label: "Source",
        stage: "source",
        summary: null,
        trust: "ok",
        trust_reason: null,
        parent_stage_id: null,
        decision_points: [],
        node_hash: "hash_source",
        producing_stage: "source",
        cas_ref: null,
        runs: ["run_a", "run_child"],
      },
      [focusKey]: {
        id: "model:ols_1",
        kind: "model",
        display_label: focusKey === "hash_child" ? "Child OLS" : "Original OLS",
        stage: "model",
        summary: null,
        trust: "ok",
        trust_reason: null,
        parent_stage_id: null,
        decision_points: [],
        node_hash: focusKey,
        producing_stage: "model",
        cas_ref: null,
        runs: focusKey === "hash_child" ? ["run_child"] : ["run_a"],
        editable: true,
        op_type: "ols",
        schema_id: "ols@v1",
        editable_schema_source: "run_inputs",
        editable_schema: [
          {
            kind: "select",
            key: "covariance",
            label: "Covariance",
            options: ["clustered", "robust"],
            value: "clustered",
          },
        ],
      },
    },
    edges: [{ source: "hash_source", target: focusKey }],
    heads: [
      {
        run_id: "run_a",
        head_node_hash: "hash_model",
        from_node: null,
        rerun_of: null,
        rerun_reason: null,
        status: "completed",
        created_at: "2026-06-27T00:00:00Z",
      },
      {
        run_id: "run_child",
        head_node_hash: "hash_child",
        from_node: "model:ols_1",
        rerun_of: "run_a",
        rerun_reason: "manual_override",
        status: "completed",
        created_at: "2026-06-27T00:01:00Z",
      },
    ],
  };
}

function mountForestAt(initialPath: string) {
  vi.spyOn(api, "getRunGraphHeadSet")
    .mockResolvedValueOnce(forestResponse("hash_model"))
    .mockResolvedValueOnce(forestResponse("hash_child"));
  vi.spyOn(api, "rerunFromNode").mockResolvedValue({
    run_id: "run_child",
    new_run_id: "run_child",
    new_active_head_id: "run_child",
    focus: {
      forest_node_key: "hash_child",
      op_node_id: "model:ols_1",
      node_hash: "hash_child",
    },
    rerun_from: {
      owner_run_id: "run_a",
      op_node_id: "model:ols_1",
      node_hash: "hash_model",
      forest_node_key: "hash_model",
    },
  });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="*"
          element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
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

  it("switches active head and selects focus after context-driven rerun success", async () => {
    mountForestAt("/?tab=lineage&tabs=hash_model&active=hash_model");
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();
    expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
      "Original OLS",
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    await waitFor(() =>
      expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
        "Child OLS",
      ),
    );
  });
});
