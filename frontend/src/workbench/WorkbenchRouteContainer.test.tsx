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
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchHome, WorkbenchRouteContainer } from "./WorkbenchRouteContainer";
import * as api from "../api";
import * as notebookApi from "../notebook/notebookApi";
import type { GraphResponse } from "../lineage/types";
import type { HeadSetResponse } from "../lineage/api/graphViewTypes";

vi.mock("../capabilities/useCapabilities", () => ({
  useCapabilities: () => ({
    data: {
      schema_version: 1,
      model_types: [{ key: "auto", label: "Auto", group: "auto" }],
      imputation_methods: [],
    },
  }),
}));

vi.mock("../llm/LlmProviderManager", () => ({
  LlmProviderManager: () => (
    <div data-testid="llm-provider-manager">
      <div data-testid="llm-provider-editor">Add provider</div>
    </div>
  ),
}));

// v1.6.9 B1-4 — wrap the REAL RunHistoryRail with a probe that records the
// RailRefreshContext token it receives. All existing tests keep seeing the real
// rail (same testids/rows); the index-wait test reads railTokenProbe to assert
// the container bumps the token when a pending run indexes.
const { railTokenProbe } = vi.hoisted(() => ({
  railTokenProbe: { tokens: [] as number[] },
}));
vi.mock("../lineage/runRail/RunHistoryRail", async () => {
  const actual = await vi.importActual<
    typeof import("../lineage/runRail/RunHistoryRail")
  >("../lineage/runRail/RunHistoryRail");
  const React = await import("react");
  const { useRailRefreshToken } = await import("./RailRefreshContext");
  return {
    ...actual,
    RunHistoryRail: (props: Record<string, unknown>) => {
      railTokenProbe.tokens.push(useRailRefreshToken());
      return React.createElement(actual.RunHistoryRail, props);
    },
  };
});

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
  vi.spyOn(api, "fetchProjectForest").mockResolvedValue({ legacy: true } as never);
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

function dispatchPointerDrag(
  target: Element,
  type: "pointerdown" | "pointermove" | "pointerup",
  clientY: number,
) {
  const event = new MouseEvent(type, { bubbles: true, clientY });
  Object.defineProperty(event, "pointerId", { value: 1 });
  fireEvent(target, event);
}

function dispatchHorizontalPointerDrag(
  target: Element,
  type: "pointerdown" | "pointermove" | "pointerup",
  clientX: number,
) {
  const event = new MouseEvent(type, { bubbles: true, clientX });
  Object.defineProperty(event, "pointerId", { value: 1 });
  fireEvent(target, event);
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

function forkedForestResponse(): HeadSetResponse {
  const response: HeadSetResponse = {
    ...forestResponse("hash_model"),
    nodes: {
      ...forestResponse("hash_model").nodes,
      hash_model: {
        ...forestResponse("hash_model").nodes.hash_model,
        runs: ["run_a", "run_null_created"],
      },
      hash_child: {
        id: "model:ols_1",
        kind: "model",
        display_label: "Child OLS",
        stage: "model",
        summary: null,
        trust: "ok",
        trust_reason: null,
        parent_stage_id: null,
        decision_points: [],
        node_hash: "hash_child",
        producing_stage: "model",
        cas_ref: null,
        runs: ["run_child"],
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
            value: "robust",
          },
        ],
      },
    },
    edges: [
      { source: "hash_source", target: "hash_model" },
      { source: "hash_source", target: "hash_child" },
    ],
    heads: [
      {
        run_id: "run_child",
        head_node_hash: "hash_child",
        from_node: "model:ols_1",
        rerun_of: "run_a",
        rerun_reason: "manual_override",
        status: "completed",
        created_at: "2026-06-27T00:01:00Z",
      },
      {
        run_id: "run_null_created",
        head_node_hash: "hash_model",
        from_node: null,
        rerun_of: null,
        rerun_reason: null,
        status: "completed",
        created_at: null,
      },
      {
        run_id: "run_a",
        head_node_hash: "hash_model",
        from_node: null,
        rerun_of: null,
        rerun_reason: null,
        status: "completed",
        created_at: "2026-06-27T00:00:00Z",
      },
    ],
  };
  return response;
}

function forkedForestResponseWithProducedOp(): HeadSetResponse {
  const response = forkedForestResponse();
  return {
    ...response,
    nodes: {
      ...response.nodes,
      hash_child: {
        ...response.nodes.hash_child,
        id: "model:ols_child",
      },
    },
  };
}

function mountForestAt(initialPath: string) {
  vi.spyOn(api, "fetchProjectForest")
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

function confirmOperationRerun() {
  fireEvent.click(screen.getByTestId("operation-rerun-submit"));
  expect(screen.getByTestId("manual-patch-preview")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("operation-rerun-submit"));
}

describe("WorkbenchRouteContainer", () => {
  it("leaving settings through any view tab restores the selected workbench view", async () => {
    mountAt("/?tab=lineage");
    await screen.findByTestId("graph-workbench");

    fireEvent.click(screen.getByTestId("workbench-topbar-settings"));
    expect(screen.getByTestId("llm-provider-manager")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("view-tab-graph"));
    expect(screen.queryByTestId("llm-provider-manager")).toBeNull();
    expect(screen.getByTestId("workbench-main")).toHaveAttribute(
      "data-view",
      "graph",
    );
  });

  it("renders the topbar with two view tabs once data loads (Pipeline retired v1.6.7)", async () => {
    mountAt("/?tab=lineage");
    expect(await screen.findByTestId("workbench-topbar")).toBeInTheDocument();
    expect(screen.getByTestId("view-tab-graph")).toBeInTheDocument();
    expect(screen.getByTestId("view-tab-table")).toBeInTheDocument();
    // v1.6.7: the Pipeline tab entry is retired (view merges into the graph).
    expect(screen.queryByTestId("view-tab-pipeline")).toBeNull();
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

  it("Pipeline view stays reachable via ?view=pipeline deep link (tab retired v1.6.7)", async () => {
    // The clickable tab is gone, but the "pipeline" ViewMode + PipelineView are
    // kept as a URL deep-link fallback (see WorkbenchTopbar VIEW_TABS comment).
    mountAt("/?tab=lineage&view=pipeline");
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

    it("opens the right drawer from a node click while Agent is active", async () => {
      mountAt("/?tab=lineage&panel=agent");
      await screen.findByTestId("graph-workbench");

      fireEvent.click(screen.getAllByTestId("graph-node")[0]);

      const drawer = await screen.findByTestId("detail-drawer");
      expect(drawer).toBeInTheDocument();
      expect(drawer).toHaveStyle({ flex: "0 0 460px" });
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

    it("scopes BottomPanel to the center workbench column instead of spanning the side panels", async () => {
      mountAt("/?tab=lineage&tabs=n1&active=n1");
      await screen.findByTestId("detail-drawer");

      const centerColumn = screen.getByTestId("workbench-center-column");
      expect(centerColumn).toContainElement(screen.getByTestId("workbench-main"));
      expect(centerColumn).toContainElement(screen.getByTestId("bottom-panel"));
      expect(centerColumn).not.toContainElement(screen.getByTestId("run-rail"));
      expect(centerColumn).not.toContainElement(screen.getByTestId("detail-drawer"));
    });

    it("ignores legacy panelOpen and keeps the BottomPanel expanded", async () => {
      mountAt("/?tab=lineage&panel=logs&panelOpen=0");
      await screen.findByTestId("graph-workbench");
      expect(screen.getByTestId("bottom-panel")).toHaveAttribute("data-open", "true");
      expect(screen.getByTestId("bottom-panel-body")).toBeInTheDocument();

      fireEvent.click(screen.getByTestId("panel-tab-logs"));

      expect(screen.getByTestId("bottom-panel")).toHaveAttribute("data-open", "true");
      expect(screen.getByTestId("bottom-panel-body")).toBeInTheDocument();
    });

    it("collapses and reopens the BottomPanel without losing its active tab", async () => {
      sessionStorage.removeItem("workbench:bottomPanelOpen:r1");
      mountAt("/?tab=lineage&panel=logs");
      await screen.findByTestId("graph-workbench");

      fireEvent.click(screen.getByRole("button", { name: "Close bottom panel" }));
      expect(screen.getByTestId("bottom-panel")).toHaveAttribute("data-open", "false");
      expect(screen.queryByTestId("bottom-panel-body")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Open bottom panel" }));
      expect(screen.getByTestId("bottom-panel")).toHaveAttribute("data-open", "true");
      expect(screen.getByTestId("panel-tab-logs")).toHaveAttribute("aria-selected", "true");
      expect(screen.getByTestId("bottom-panel-body")).toBeInTheDocument();
    });

    it("keeps the bottom panel freely resizable instead of forcing Focus mode", async () => {
      mountAt("/?tab=lineage&panel=agent");
      await screen.findByTestId("graph-workbench");

      expect(screen.getByTestId("bottom-panel")).toHaveStyle({
        height: "240px",
        minHeight: "160px",
      });
      expect(screen.queryByTestId("bottom-panel-focus")).not.toBeInTheDocument();
    });

    it("hosts the single Agent composer inside the Agent bottom panel", async () => {
      mountAt("/?tab=lineage&panel=agent");
      await screen.findByTestId("graph-workbench");

      const composer = screen.getByTestId("agent-composer");
      expect(screen.getByTestId("bottom-panel")).toContainElement(composer);
      expect(screen.getAllByTestId("agent-composer")).toHaveLength(1);
    });

    it("resizes the left run rail with a horizontal splitter", async () => {
      sessionStorage.removeItem("workbench:runRailWidth:/proj");
      mountAt("/?tab=lineage");
      await screen.findByTestId("graph-workbench");

      const rail = screen.getByTestId("run-rail");
      const splitter = screen.getByTestId("run-rail-resizer");
      expect(rail).toHaveStyle({ width: "240px" });

      dispatchHorizontalPointerDrag(splitter, "pointerdown", 240);
      dispatchHorizontalPointerDrag(splitter, "pointermove", 320);
      dispatchHorizontalPointerDrag(splitter, "pointerup", 320);

      expect(rail).toHaveStyle({ width: "320px" });
      expect(sessionStorage.getItem("workbench:runRailWidth:/proj")).toBe("320");
    });

    it("resizes the right detail drawer with a horizontal splitter", async () => {
      sessionStorage.removeItem("workbench:detailDrawerWidth:/proj");
      mountAt("/?tab=lineage&tabs=n1&active=n1");
      const drawer = await screen.findByTestId("detail-drawer");
      const splitter = screen.getByTestId("detail-drawer-resizer");
      expect(drawer).toHaveStyle({ width: "460px" });

      dispatchHorizontalPointerDrag(splitter, "pointerdown", 1000);
      dispatchHorizontalPointerDrag(splitter, "pointermove", 900);
      dispatchHorizontalPointerDrag(splitter, "pointerup", 900);

      expect(drawer).toHaveStyle({ width: "560px" });
      expect(sessionStorage.getItem("workbench:detailDrawerWidth:/proj")).toBe("560");
    });

    it("does not render a focus-only control for the active Agent panel", async () => {
      mountAt("/?tab=lineage&panel=agent");
      await screen.findByTestId("graph-workbench");
      expect(screen.queryByTestId("bottom-panel-focus")).not.toBeInTheDocument();
    });

    it("persists BottomPanel height when pointer-dragging the top splitter", async () => {
      mountAt("/?tab=lineage");
      await screen.findByTestId("graph-workbench");
      const panel = screen.getByTestId("bottom-panel");
      const splitter = screen.getByTestId("bottom-panel-resizer");

      dispatchPointerDrag(splitter, "pointerdown", 500);
      dispatchPointerDrag(splitter, "pointermove", 420);
      dispatchPointerDrag(splitter, "pointerup", 420);

      expect(panel).toHaveStyle({ height: "320px" });
      expect(sessionStorage.getItem("workbench:bottomPanelHeight:r1")).toBe("320");
    });

    it("passes the project root into RunHistoryRail on slug routes without project_root query", async () => {
      vi.spyOn(api, "fetchRuns").mockResolvedValue({
        runs: [
          {
            run_id: "20260705_095444_558248_221f751e",
            status: "completed",
            started_at: "2026-07-05T09:54:44Z",
            finished_at: "2026-07-05T09:55:10Z",
            model_type: "ols_robust",
          } as never,
        ],
      });
      mountAt("/p/slug/graph?view=table");

      expect(await screen.findByTestId("run-rail-row-20260705_095444_558248_221f751e")).toBeInTheDocument();
      expect(api.fetchRuns).toHaveBeenCalledWith("/proj");
      expect(screen.queryByText("No runs yet.")).toBeNull();
    });
  });

  it("switches active head and selects focus after context-driven rerun success", async () => {
    mountForestAt("/?tab=lineage&tabs=hash_model&active=hash_model");
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();
    expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
      "Original OLS",
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    confirmOperationRerun();

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

  it("selects the child run node by op node when the response focus key still names the parent", async () => {
    vi.spyOn(api, "fetchProjectForest")
      .mockResolvedValueOnce(forestResponse("hash_model"))
      .mockResolvedValueOnce(forkedForestResponse());
    vi.spyOn(api, "rerunFromNode").mockResolvedValue({
      run_id: "run_child",
      new_run_id: "run_child",
      new_active_head_id: "run_child",
      focus: {
        forest_node_key: "hash_model",
        op_node_id: "model:ols_1",
        node_hash: "hash_model",
      },
      rerun_from: {
        owner_run_id: "run_a",
        op_node_id: "model:ols_1",
        node_hash: "hash_model",
        forest_node_key: "hash_model",
      },
    });
    render(
      <MemoryRouter initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}>
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    confirmOperationRerun();

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

  it("keeps polling and selects the child run node when context rerun returns focus null before the child is indexed", async () => {
    vi.spyOn(api, "fetchProjectForest")
      .mockResolvedValueOnce(forestResponse("hash_model"))
      .mockResolvedValueOnce(forestResponse("hash_model"))
      .mockResolvedValueOnce(forkedForestResponse());
    vi.spyOn(api, "rerunFromNode").mockResolvedValue({
      run_id: "run_child",
      new_run_id: "run_child",
      new_active_head_id: "run_child",
      focus: null,
      rerun_from: {
        owner_run_id: "run_a",
        op_node_id: "model:ols_1",
        node_hash: "hash_model",
        forest_node_key: "hash_model",
      },
    });
    render(
      <MemoryRouter initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}>
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    confirmOperationRerun();

    await waitFor(() => expect(api.fetchProjectForest).toHaveBeenCalledTimes(3));
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

  it("uses produced lineage pending_index to poll by rerun request id without guessing runs[0]", async () => {
    vi.spyOn(api, "fetchProjectForest")
      .mockResolvedValueOnce(forestResponse("hash_model"))
      .mockResolvedValueOnce(forestResponse("hash_model"))
      .mockResolvedValueOnce(forkedForestResponseWithProducedOp());
    vi.spyOn(api, "rerunFromNode").mockResolvedValue({
      run_id: "run_child",
      new_run_id: "run_child",
      new_active_head_id: "run_child",
      focus: null,
      rerun_from: {
        owner_run_id: "run_source",
        op_node_id: "model:source_ols",
        node_hash: "hash_source",
        forest_node_key: "hash_source::model:source_ols",
      },
      produced_lineage: {
        produced_owner_run_id: "run_child",
        produced_op_node_id: "model:ols_child",
        produced_node_hash: "hash_child",
        rerun_request_id: "req_focus",
        status: "pending_index",
        rerun_from: {
          owner_run_id: "run_source",
          op_node_id: "model:source_ols",
          node_hash: "hash_source",
          context_fingerprint: "nocv1:source",
          rerun_request_id: "req_focus",
        },
      },
    });
    render(
      <MemoryRouter initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}>
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    confirmOperationRerun();

    await waitFor(() => expect(api.fetchProjectForest).toHaveBeenCalledTimes(3));
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

  it("uses draft pending query params to poll and select the child run node", async () => {
    vi.spyOn(api, "fetchProjectForest")
      .mockResolvedValueOnce(forestResponse("hash_model"))
      .mockResolvedValueOnce(forkedForestResponse());
    render(
      <MemoryRouter
        initialEntries={[
          "/?tab=lineage&pending_source_run_id=run_a&pending_source_model_node_id=model:ols_1&pending_source_op_node_id=model:ols_1",
        ]}
      >
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_child" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(api.fetchProjectForest).toHaveBeenCalledTimes(2));
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

  it("fetches persisted drafts on mount to hydrate the forest", async () => {
    vi.spyOn(api, "fetchProjectForest").mockResolvedValue(
      forestResponse("hash_model"),
    );
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/?tab=lineage"]}>
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(api.listPipelineDrafts).toHaveBeenCalledWith(expect.any(String)),
    );
  });

  // ── v1.6.8 T11 — project-keyed WorkbenchHome ──
  describe("WorkbenchHome (project-keyed, T11)", () => {
    function emptyForestBody(): HeadSetResponse {
      return {
        schema_version: 2,
        legacy: false,
        nodes: {},
        edges: [],
        heads: [],
      };
    }

    function allLegacyProjectBody(): HeadSetResponse {
      return {
        ...emptyForestBody(),
        families: [
          { family_root: "legacy_run", members: ["legacy_run", "legacy_child"] },
        ],
      };
    }

    function legacyGraph(runId = "legacy_run"): GraphResponse {
      return {
        ...fakeGraph(),
        run_id: runId,
        legacy: true,
        nodes: {},
        edges: {},
        stats: { node_count: 0, edge_count: 0, leaf_count: 0, has_dp_count: 0 },
      };
    }

    function genesisDraftResponse(): api.PipelineDraftResponse {
      return {
        draft_hash: "h_genesis",
        draft: {
          draft_id: "genesis_d1",
          schema_version: "pipeline_draft.v1",
          created_at: "t",
          updated_at: "t",
          status: "draft",
          created_from: {
            source_type: "genesis",
            source_input_fingerprint: "sha_abc",
          },
          graph: {
            nodes: [
              {
                node_id: "source_1",
                node_type: "input.upload",
                upload: { sha256: "sha_abc", filename: "data.xlsx" },
                sheet_names: ["Sheet1"],
                columns: ["y", "x"],
                status: "bound",
              },
              {
                node_id: "table_1",
                node_type: "table",
                params: { sheet_name: "Sheet1", transpose: false },
                columns: ["y", "x"],
                status: "configured",
              },
              {
                node_id: "model_1",
                node_type: "model",
                model_type: "ols",
                params: { y: "y", x: ["x"] },
                status: "configured",
              },
            ],
            edges: [
              { from: "source_1", to: "table_1" },
              { from: "table_1", to: "model_1" },
            ],
          },
          default_execution_mode: "genesis",
        },
      };
    }

    function mountHome(focusRunId?: string, initialEntry = "/") {
      return render(
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route
              path="*"
              element={
                <WorkbenchHome projectRoot="/proj" focusRunId={focusRunId} />
              }
            />
          </Routes>
        </MemoryRouter>,
      );
    }

    it("zero-run project renders the empty canvas with the genesis CTA", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      mountHome();

      expect(await screen.findByTestId("genesis-cta")).toBeInTheDocument();
      expect(screen.getByText("This project has no data yet.")).toBeInTheDocument();
      // The empty canvas replaces the shell entirely.
      expect(screen.queryByTestId("workbench-route")).toBeNull();
    });

    it("clicking the genesis CTA opens the genesis wizard drawer", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
      mountHome();

      fireEvent.click(await screen.findByTestId("genesis-cta"));
      expect(screen.getByTestId("genesis-wizard-drawer")).toBeInTheDocument();
      expect(screen.getByTestId("genesis-wizard")).toBeInTheDocument();
    });

    it("opens the genesis wizard automatically for newly created project handoff URLs", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
      mountHome(undefined, "/p/slug/graph?genesis=1");

      expect(await screen.findByTestId("genesis-wizard-drawer")).toBeInTheDocument();
      expect(screen.getByTestId("genesis-wizard")).toBeInTheDocument();
    });

    it("consumes ?genesis=1 after opening so a closed wizard does not reopen", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
      let currentSearch: string | null = null;
      function LocationProbe() {
        currentSearch = useLocation().search;
        return null;
      }
      render(
        <MemoryRouter initialEntries={["/p/slug/graph?genesis=1"]}>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  <LocationProbe />
                  <WorkbenchHome projectRoot="/proj" />
                </>
              }
            />
          </Routes>
        </MemoryRouter>,
      );

      expect(await screen.findByTestId("genesis-wizard-drawer")).toBeInTheDocument();
      // The handoff param is one-shot: it must leave the URL once consumed, so
      // reload-style remounts and unrelated query updates cannot reopen a
      // wizard the user closed.
      await waitFor(() => expect(currentSearch).not.toContain("genesis"));

      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await waitFor(() =>
        expect(screen.queryByTestId("genesis-wizard-drawer")).toBeNull(),
      );
    });

    it("legacy deep links fall back to the legacy per-run workbench when the project forest omits the run", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(allLegacyProjectBody());
      vi.spyOn(api, "getRunGraphHeadSet").mockResolvedValue({
        legacy: true,
        schema_version: 3,
        nodes: {},
        edges: {},
      } as never);
      vi.spyOn(api, "getRunGraph").mockResolvedValue(legacyGraph());
      mountHome("legacy_run");

      expect(await screen.findByTestId("legacy-banner")).toBeInTheDocument();
      expect(api.getRunGraphHeadSet).toHaveBeenCalledWith("/proj", "legacy_run");
      expect(api.getRunGraph).toHaveBeenCalledWith("/proj", "legacy_run");
      expect(screen.queryByTestId("workbench-empty-canvas")).toBeNull();
    });

    it("all-legacy projects show an honest legacy empty state while keeping the genesis CTA", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(allLegacyProjectBody());
      mountHome();

      expect(await screen.findByTestId("genesis-cta")).toBeInTheDocument();
      expect(
        screen.getByText(/This project has 2 runs from before lineage indexing/),
      ).toBeInTheDocument();
      expect(screen.queryByText("This project has no data yet.")).toBeNull();
    });

    it("zero-run projects with a genesis draft render the draft island on the canvas instead of the empty canvas", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([
        {
          draft_id: "genesis_d1",
          status: "draft",
          draft_hash: "h_genesis",
        },
      ]);
      vi.spyOn(api, "getPipelineDraft").mockResolvedValue(genesisDraftResponse());
      mountHome();

      expect(await screen.findByTestId("graph-workbench")).toBeInTheDocument();
      expect(screen.queryByTestId("workbench-empty-canvas")).toBeNull();
      expect(api.getPipelineDraft).toHaveBeenCalledWith("/proj", "genesis_d1");
    });

    it("draft-only genesis reload exposes a topbar resume entry back into the wizard", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([
        {
          draft_id: "genesis_d1",
          status: "draft",
          draft_hash: "h_genesis",
        },
      ]);
      vi.spyOn(api, "getPipelineDraft").mockResolvedValue(genesisDraftResponse());
      mountHome();

      expect(await screen.findByTestId("graph-workbench")).toBeInTheDocument();
      fireEvent.click(await screen.findByTestId("genesis-resume-cta"));

      expect(screen.getByTestId("genesis-wizard-drawer")).toBeInTheDocument();
      expect(await screen.findByTestId("genesis-resume")).toBeInTheDocument();
    });

    it("with runs and NO focusRunId, the newest head (by created_at) is active", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(
        forkedForestResponse(),
      );
      mountHome();

      // run_child (created 00:01) is newer, even though it is not the last
      // head and another head has created_at=null.
      await waitFor(() =>
        expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
          "aria-pressed",
          "true",
        ),
      );
    });

    it("an explicit focusRunId is honored over the newest head", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(
        forkedForestResponse(),
      );
      mountHome("run_a");

      await waitFor(() =>
        expect(screen.getByTestId("forest-head-run_a")).toHaveAttribute(
          "aria-pressed",
          "true",
        ),
      );
      expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });

    it("polls the project forest until a just-completed focused run is indexed", async () => {
      const initial = forestResponse();
      initial.heads = [initial.heads[0]];
      initial.nodes.hash_model = {
        ...initial.nodes.hash_model,
        runs: ["run_a"],
      };
      const indexed: HeadSetResponse = {
        ...initial,
        nodes: {
          ...initial.nodes,
          hash_model: {
            ...initial.nodes.hash_model,
            runs: ["run_a", "run_target"],
          },
        },
        heads: [
          ...initial.heads,
          {
            ...initial.heads[0],
            run_id: "run_target",
            created_at: "2026-06-27T00:02:00Z",
          },
        ],
      };
      vi.spyOn(api, "fetchProjectForest")
        .mockResolvedValueOnce(initial)
        .mockResolvedValue(indexed);
      vi.spyOn(api, "getRunGraphHeadSet").mockResolvedValue({
        legacy: false,
        heads: [],
      } as never);
      mountHome("run_target");

      await waitFor(
        () => {
          expect(api.fetchProjectForest).toHaveBeenCalledTimes(2);
          expect(screen.getByTestId("forest-head-run_target")).toHaveAttribute(
            "aria-pressed",
            "true",
          );
        },
        { timeout: 3000 },
      );
    });
  });
});

// ── v1.6.9 B1 — draft-execute rides the index-wait layer ──
//
// The bug: handleExecuteDraft used to remove the draft node + give up focus
// within a 4s budget the moment the execute POST returned. But the produced
// run is a background async job — a long run (honest-DID ~157s) is nowhere in
// the forest for minutes, so the draft vanished instantly and the user saw
// "nothing happened". The fix routes draft-execute through usePendingRun: the
// draft node STAYS on the canvas in "executing" state until the run actually
// indexes (then remove + focus + delete) or terminally fails (then mark
// failed). These tests drive the real drawer → Validate → Execute flow and
// then poll under fake timers, exactly as a long run behaves.
describe("draft execute — index-wait (v1.6.9 B1)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // A forest with ONE completed head (run_a) and NO child run — the produced
  // run is not yet indexed. Fresh object each call so a refetch changes the
  // forest reference (mirrors the live refetch loop).
  function soloForest(): HeadSetResponse {
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
          runs: ["run_a"],
        },
        hash_model: {
          id: "model:ols_1",
          kind: "model",
          display_label: "Original OLS",
          stage: "model",
          summary: null,
          trust: "ok",
          trust_reason: null,
          parent_stage_id: null,
          decision_points: [],
          node_hash: "hash_model",
          producing_stage: "model",
          cas_ref: null,
          runs: ["run_a"],
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
      edges: [{ source: "hash_source", target: "hash_model" }],
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
      ],
    };
  }

  function draftSummary(): api.PipelineDraftSummary {
    return {
      draft_id: "d1",
      status: "draft",
      draft_hash: "h1",
      source_run_id: "run_a",
      source_model_node_id: "model:ols_1",
      source_op_node_id: "model:ols_1",
      source_node_hash: "hash_model",
      model_type: "ols",
    };
  }

  function draftGet(withNotebook = false): api.PipelineDraftResponse {
    const response = {
      draft_hash: "h1",
      draft: {
        draft_id: "d1",
        schema_version: "pipeline_draft.v1",
        created_at: "t",
        updated_at: "t",
        status: "draft",
        created_from: {
          source_type: "node",
          source_node_hash: "hash_model",
          source_op_node_id: "model:ols_1",
        },
        graph: {
          nodes: [
            {
              node_id: "model_1",
              node_type: "model",
              model_type: "ols",
              params: { y: "y", x: ["x"] },
              status: "configured",
            },
          ],
          edges: [],
        },
        default_execution_mode: "rerun_child",
      },
    } as api.PipelineDraftResponse;
    if (withNotebook) {
      response.draft.notebook_provenance = {
        notebook_id: "nb_1",
        option_id: "opt_1",
        option_revision: "1",
      };
    }
    return response;
  }

  function validResult(): api.DraftValidationResult {
    return {
      ok: true,
      status: "valid",
      executable: true,
      checks: [],
      resolved_execution: { execution_mode: "rerun_child" },
      validated_execution_mode: "rerun_child",
      validated_draft_hash: "h1v",
      validated_at: "t",
    };
  }

  function execResult(): api.DraftExecutionResult {
    return {
      ok: true,
      run_id: "run_child",
      draft_id: "d1",
      executed_draft_hash: "h1v",
      execution_mode: "rerun_child",
      produced_lineage: {
        execution_mode: "rerun_child",
        rerun_from_op_node_id: "model:ols_1",
      },
      focus: {
        status: "pending_index",
        run_id: "run_child",
        poll: { rerun_from_op_node_id: "model:ols_1" },
      },
    };
  }

  async function flush(ms = 0) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  // Mount with the draft node pre-selected (its drawer open) and drive the real
  // drawer Validate → Execute buttons. Returns the api spies the tests assert on.
  async function mountAndExecute(opts: {
    forestBody: () => HeadSetResponse;
    runDetail: () => { status: string };
    notebookProvenance?: boolean;
  }) {
    const forestSpy = vi
      .spyOn(api, "fetchProjectForest")
      .mockImplementation(async () => opts.forestBody());
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([draftSummary()]);
    vi.spyOn(api, "getPipelineDraft").mockResolvedValue(
      draftGet(opts.notebookProvenance),
    );
    vi.spyOn(api, "validatePipelineDraft").mockResolvedValue(validResult());
    const executeSpy = vi
      .spyOn(api, "executePipelineDraft")
      .mockResolvedValue(execResult());
    const deleteSpy = vi
      .spyOn(api, "deletePipelineDraft")
      .mockResolvedValue({ ok: true } as never);
    vi.spyOn(api, "fetchRunDetail").mockImplementation(
      async () => opts.runDetail() as never,
    );

    render(
      <MemoryRouter
        initialEntries={["/?tab=lineage&tabs=draft:d1&active=draft:d1"]}
      >
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    // Flush the forest load + draft hydrate so the draft node mounts and its
    // drawer (pre-selected via the URL tab) renders.
    await flush();
    await flush();

    const draftNode = screen.getByTestId("graph-node-lifecycle");
    expect(draftNode).toBeInTheDocument();

    // Validate → Execute (Execute is gated on the draft being valid).
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Execute" }));
    await flush();

    return { forestSpy, executeSpy, deleteSpy };
  }

  it("keeps the draft node visible while the executed run is still running", async () => {
    const { deleteSpy } = await mountAndExecute({
      forestBody: soloForest, // never contains run_child
      runDetail: () => ({ status: "running" }),
    });

    // Poll well past the OLD 4s / 20×200ms focus budget.
    for (let i = 0; i < 6; i++) await flush(1000);

    const draftNode = screen.getByTestId("graph-node-lifecycle");
    expect(draftNode).toBeInTheDocument();
    // Executing, NOT removed and NOT failed.
    expect(draftNode).toHaveAttribute("data-lifecycle", "pending");
    expect(deleteSpy).not.toHaveBeenCalled();
    // The run never indexed → no child head became active.
    expect(screen.queryByTestId("forest-head-run_child")).toBeNull();
  });

  it("reconciles a Notebook option when the Graph draft editor executes it", async () => {
    vi.spyOn(api, "waitForRunTerminal").mockResolvedValue({
      status: "completed",
    } as never);
    const completeSpy = vi
      .spyOn(notebookApi, "completeNotebookOptionExecution")
      .mockResolvedValue({} as never);

    await mountAndExecute({
      forestBody: soloForest,
      runDetail: () => ({ status: "completed" }),
      notebookProvenance: true,
    });

    await flush();
    expect(completeSpy).toHaveBeenCalledWith(
      "/proj",
      "nb_1",
      "opt_1",
      {
        execution_status: "succeeded",
        run_id: "run_child",
      },
    );
  });

  it("removes the draft and focuses once the run indexes", async () => {
    let forestBody: () => HeadSetResponse = soloForest;
    let status = "running";
    const { deleteSpy } = await mountAndExecute({
      forestBody: () => forestBody(),
      runDetail: () => ({ status }),
    });

    // A couple of running polls: the draft is still there.
    await flush(1000);
    expect(screen.getByTestId("graph-node-lifecycle")).toBeInTheDocument();

    // The run finishes and the forest index catches up.
    forestBody = forkedForestResponse; // now includes run_child / "Child OLS"
    status = "completed";
    await flush(1000); // poll → refetch → forest now has run_child → onIndexed
    // Extra flushes: onIndexed removes the draft + sets the pending focus, then
    // the WorkbenchShell pending-focus effect resolves + selects the produced
    // node. (waitFor is unusable here — fake timers never advance its poller.)
    await flush(200);
    await flush(200);

    // Draft node gone, produced run focused, best-effort cleanup fired.
    expect(screen.queryByTestId("graph-node-lifecycle")).toBeNull();
    expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
      "Child OLS",
    );
    expect(deleteSpy).toHaveBeenCalledWith("/proj", "d1");
  });

  it("bumps the rail-refresh token so the RUNS rail re-fetches when the executed run indexes", async () => {
    // v1.6.9 B1-4 — the container must signal the RUNS rail to refresh the moment
    // a pending run indexes (else the rail lags up to its 30s poll). A fetch-count
    // assertion is unusable here: useForestData.refetch() flips loading→true on
    // every poll, so the container flashes <Loading/> and remounts the whole shell
    // (rail included), meaning the rail already re-fetches /runs on every poll
    // regardless of this wiring. So we assert the container's own responsibility
    // directly — the RailRefreshContext token it hands the rail must increment on
    // index. RunHistoryRail is mocked (top of file) to the real component plus a
    // token probe; without the wiring the token stays 0 and this fails.
    railTokenProbe.tokens.length = 0;
    let forestBody: () => HeadSetResponse = soloForest;
    let status = "running";
    await mountAndExecute({
      forestBody: () => forestBody(),
      runDetail: () => ({ status }),
    });

    await flush();
    const tokenBeforeIndex = Math.max(0, ...railTokenProbe.tokens);
    expect(tokenBeforeIndex).toBe(0);

    // The run finishes and the forest index catches up → onIndexed → token bump.
    forestBody = forkedForestResponse;
    status = "completed";
    await flush(1000); // poll → refetch → forest now has run_child → onIndexed
    await flush(200);
    await flush(200);

    const tokenAfterIndex = Math.max(0, ...railTokenProbe.tokens);
    expect(tokenAfterIndex).toBeGreaterThan(tokenBeforeIndex);
  });

  it("marks the draft failed when the run terminally fails", async () => {
    const { deleteSpy } = await mountAndExecute({
      forestBody: soloForest,
      runDetail: () => ({ status: "failed" }),
    });

    await flush(1000); // poll → fetchRunDetail failed → onFailed

    const draftNode = screen.getByTestId("graph-node-lifecycle");
    // Marked failed on the canvas — NOT silently removed.
    expect(draftNode).toBeInTheDocument();
    expect(draftNode).toHaveAttribute("data-lifecycle", "failed");
    expect(deleteSpy).not.toHaveBeenCalled();
  });
});
