// frontend/src/workbench/WorkbenchRouteContainer.test.tsx
//
// V1.5.2 P3 — container + view switcher integration.
//
// The container's data-loading path is already covered by
// `WorkbenchRouteContainer.perRun.test.tsx`. This
// file adds the V1.5.2-specific behaviour:
//   - topbar renders the three view tabs
//   - switching view via topbar updates URL `?view=`
//   - selecting `table` / `pipeline` swaps WorkbenchMain content

import { ThemeProvider } from "../theme";
import type { ReactNode } from "react";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render as renderRaw, screen, waitFor, within } from "@testing-library/react";
const render = (ui: ReactNode) => renderRaw(<ThemeProvider>{ui}</ThemeProvider>);

import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchHome, WorkbenchRouteContainer } from "./WorkbenchRouteContainer";
import * as api from "../api";
import * as notebookApi from "../notebook/notebookApi";
import type { GraphResponse } from "../lineage/types";
import type { HeadSetResponse } from "../lineage/api/graphViewTypes";
import {
  draftFixture,
  draftSummaryFixture,
  modelDraftNodeFixture,
  runCreatedFromFixture,
  tableDraftNodeFixture,
  uploadDraftNodeFixture,
} from "../apiFixtures";
import { forestEdgeFixture, forestHeadFixture, forestNodeFixture } from "../apiFixtures";

// These assertions cover the retained classic route, rails and panels.
beforeEach(() => {
  localStorage.setItem("workbench:workspace", "classic"); // stale preference must not restore the shell
  localStorage.setItem("workbench:layout:/proj", "lineage");
  localStorage.setItem("workbench:agent-mode", "docked");
  sessionStorage.clear();
});

const routerFuture = { v7_startTransition: true, v7_relativeSplatPath: true };

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

// Observe the shared refresh context through the migrated Runs table.
const { railTokenProbe, submissionProbe } = vi.hoisted(() => ({
  railTokenProbe: { tokens: [] as number[] },
  submissionProbe: {draft: null as import("../lineage/drafts/DraftActionsContext").DraftActionsValue | null,
    rerun: null as import("../lineage/detail/RerunContext").RerunContextValue | null},
}));
vi.mock("../lineage/drafts/DraftActionsContext", async () => {
  const actual = await vi.importActual<typeof import("../lineage/drafts/DraftActionsContext")>("../lineage/drafts/DraftActionsContext");
  const React = await import("react");
  const {useRerun} = await import("../lineage/detail/RerunContext");
  return {...actual, DraftActionsProvider: (props: Parameters<typeof actual.DraftActionsProvider>[0]) => {
    submissionProbe.draft = props.value;
    submissionProbe.rerun = useRerun();
    return React.createElement(actual.DraftActionsProvider, props);
  }};
});
vi.mock("../workspace/RunsTable", async () => {
  const actual = await vi.importActual<typeof import("../workspace/RunsTable")>("../workspace/RunsTable");
  const React = await import("react");
  const { useRailRefreshToken } = await import("./RailRefreshContext");
  return { RunsTable: (props: Parameters<typeof actual.RunsTable>[0]) => {
    railTokenProbe.tokens.push(useRailRefreshToken());
    return React.createElement(actual.RunsTable, props);
  } };
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
    <MemoryRouter
      initialEntries={[initialPath]}
      future={routerFuture}
    >
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
      hash_source: forestNodeFixture({
        id: "source:upload",
        kind: "dataset_stage",
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
      }),
      [focusKey]: forestNodeFixture({
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
      }),
    },
    edges: [forestEdgeFixture({ source: "hash_source", target: focusKey })],
    heads: [
      forestHeadFixture({
        run_id: "run_a",
        head_node_hash: "hash_model",
        from_node: null,
        rerun_of: null,
        rerun_reason: null,
        status: "completed",
        created_at: "2026-06-27T00:00:00Z",
      }),
      forestHeadFixture({
        run_id: "run_child",
        head_node_hash: "hash_child",
        from_node: "model:ols_1",
        rerun_of: "run_a",
        rerun_reason: "manual_override",
        status: "completed",
        created_at: "2026-06-27T00:01:00Z",
      }),
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
      hash_child: forestNodeFixture({
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
      }),
    },
    edges: [
      forestEdgeFixture({ source: "hash_source", target: "hash_model" }),
      forestEdgeFixture({ source: "hash_source", target: "hash_child" }),
    ],
    heads: [
      forestHeadFixture({
        run_id: "run_child",
        head_node_hash: "hash_child",
        from_node: "model:ols_1",
        rerun_of: "run_a",
        rerun_reason: "manual_override",
        status: "completed",
        created_at: "2026-06-27T00:01:00Z",
      }),
      forestHeadFixture({
        run_id: "run_null_created",
        head_node_hash: "hash_model",
        from_node: null,
        rerun_of: null,
        rerun_reason: null,
        status: "completed",
        created_at: null,
      }),
      forestHeadFixture({
        run_id: "run_a",
        head_node_hash: "hash_model",
        from_node: null,
        rerun_of: null,
        rerun_reason: null,
        status: "completed",
        created_at: "2026-06-27T00:00:00Z",
      }),
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
  vi.spyOn(api, "fetchRunDetail").mockResolvedValue({status: "completed"} as never);
  vi.spyOn(api, "fetchProjectForest")
    .mockResolvedValueOnce(forestResponse("hash_model"))
    .mockResolvedValueOnce(forestResponse("hash_child"));
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
    produced_lineage: null,
    accepted_context: null,
});
  return render(
    <MemoryRouter
      initialEntries={[initialPath]}
      future={routerFuture}
    >
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
  it("activates a persistent Report review panel without removing node tabs", async () => {
    mountForestAt("/?view=graph&tabs=hash_model&active=hash_model");
    await screen.findByTestId("detail-drawer");

    fireEvent.click(screen.getByTestId("workspace-view-report"));

    expect(await screen.findByTestId("report-review-panel")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Report review" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Original OLS" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Timeline" })).toBeInTheDocument();
  });

  it("makes Open Report focus the top report composer even when already on Report", async () => {
    vi.spyOn(api, "fetchRunArtifacts").mockResolvedValue({ groups: [] });
    mountForestAt("/?view=report&tabs=report:review&active=report:review");
    await screen.findByTestId("report-review-empty");

    fireEvent.click(screen.getByRole("button", { name: "Open Report" }));

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Report instruction" })).toHaveFocus(),
    );
  });

  it("keeps floating Report review above the Workbench when the view changes", async () => {
    mountForestAt("/?view=graph&tabs=hash_model&active=hash_model");
    await screen.findByTestId("detail-drawer");
    await screen.findByTestId("detail-drawer");
    fireEvent.click(screen.getByTestId("workspace-view-report"));
    await screen.findByTestId("report-review-panel");

    fireEvent.click(screen.getByRole("button", { name: "Float report review" }));
    expect(screen.getByTestId("report-review-floating")).toHaveAttribute("data-pinned", "false");
    fireEvent.click(screen.getByRole("button", { name: "Pin report review" }));
    expect(screen.getByTestId("report-review-floating")).toHaveAttribute("data-pinned", "true");
    expect(screen.getByRole("button", { name: "Drag report review" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Collapse report review" }));
    expect(screen.getByTestId("report-review-panel")).toHaveAttribute("data-collapsed", "true");
    expect(screen.getByTestId("report-review-floating")).toHaveClass("report-review-floating--collapsed");
    expect(screen.getByRole("button", { name: "Expand report review" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand report review" }));
    fireEvent.click(screen.getByTestId("workspace-view-table"));
    await waitFor(() => expect(screen.queryByTestId("table-view-loading")).not.toBeInTheDocument());

    expect(screen.getByTestId("report-review-floating")).toBeInTheDocument();
    expect(
      screen.queryByTestId("report-review-empty")
      || screen.queryByTestId("report-review-load-error"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dock report review" }));
    expect(screen.queryByTestId("report-review-floating")).not.toBeInTheDocument();
  });

  it("gives node panels the same float, pin, and collapse controls as Report review", async () => {
    sessionStorage.removeItem("workbench:node-panel:/proj");
    mountForestAt("/?view=table&tabs=hash_model&active=hash_model");
    await screen.findByTestId("detail-drawer");
    await screen.findByTestId("detail-drawer");

    expect(screen.getByRole("button", { name: "Float node panel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pin node panel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse node panel" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /node actions/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    expect(screen.getByRole("button", { name: "Close Original OLS tab" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Float node panel" }));
    expect(screen.getByTestId("node-panel-floating")).toHaveAttribute("data-pinned", "false");
    expect(screen.getByRole("button", { name: "Pin node panel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /node actions/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    expect(screen.getByRole("button", { name: "Close Original OLS tab" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pin node panel" }));
    expect(screen.getByTestId("node-panel-floating")).toHaveAttribute("data-pinned", "true");
    fireEvent.click(screen.getByRole("button", { name: "Collapse node panel" }));
    expect(screen.getByTestId("node-panel-floating")).toHaveAttribute("data-collapsed", "true");
    expect(screen.queryByTestId("basic-info-section")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand node panel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /node actions/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Expand node panel" }));
    fireEvent.click(screen.getByTestId("workspace-view-graph"));
    expect(screen.getByTestId("node-panel-floating")).toBeInTheDocument();
    expect(screen.getByTestId("basic-info-section")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dock node panel" }));
    expect(screen.queryByTestId("node-panel-floating")).not.toBeInTheDocument();
    sessionStorage.removeItem("workbench:node-panel:/proj");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });

  it("provides four corner resize handles for a floating node panel", async () => {
    sessionStorage.removeItem("workbench:node-panel:/proj");
    mountForestAt("/?view=table&tabs=hash_model&active=hash_model");
    await screen.findByTestId("detail-drawer");

    fireEvent.click(screen.getByRole("button", { name: "Float node panel" }));
    const floating = await screen.findByTestId("node-panel-floating");
    expect(screen.getByRole("button", { name: "Node actions" })).toHaveClass(
      "node-action-menu__trigger",
    );
    expect(screen.getByRole("button", { name: "Drag node panel" })).toHaveClass(
      "panel-window-drag-handle",
    );

    const corners = ["top-left", "top-right", "bottom-left", "bottom-right"];
    for (const corner of corners) {
      expect(
        within(floating).getByRole("button", {
          name: `Resize node panel from ${corner}`,
        }),
      ).toBeInTheDocument();
    }

    const topLeft = within(floating).getByRole("button", {
      name: "Resize node panel from top-left",
    });
    fireEvent.pointerDown(topLeft, { clientX: 100, clientY: 100, pointerId: 1 });
    expect(floating).toHaveAttribute("data-resizing", "true");
    fireEvent.pointerUp(topLeft, { clientX: 100, clientY: 100, pointerId: 1 });
    expect(floating).toHaveAttribute("data-resizing", "false");
    sessionStorage.removeItem("workbench:node-panel:/proj");
  });

  it("detaches a floating node tab while keeping other docked tabs visible", async () => {
    sessionStorage.removeItem("workbench:node-panel:/proj");
    mountForestAt("/?view=table&tabs=hash_model,report:review&active=hash_model");
    await screen.findByTestId("detail-drawer");

    const dockedTabs = screen.getByTestId("panel-host-tabs");
    expect(within(dockedTabs).getByRole("tab", { name: "Original OLS" })).toBeInTheDocument();
    expect(within(dockedTabs).getByRole("tab", { name: "Report review" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Float node panel" }));

    await waitFor(() => {
      expect(screen.getByTestId("node-panel-floating")).toBeInTheDocument();
      // The review's tab waits here; its panel opens beside the report, not over this document.
      expect(screen.getByTestId("panel-host")).toHaveAttribute("data-active-kind", "none");
    });
    expect(within(screen.getByTestId("node-panel-floating")).getByRole("tab", { name: "Original OLS" })).toBeInTheDocument();
    expect(within(screen.getByTestId("node-panel-floating")).queryByRole("tab", { name: "Report review" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Dock node panel" }));

    await waitFor(() => {
      expect(screen.queryByTestId("node-panel-floating")).not.toBeInTheDocument();
      expect(screen.getByTestId("panel-host")).toHaveAttribute("data-active-kind", "node");
    });
    expect(within(screen.getByTestId("panel-host-tabs")).getByRole("tab", { name: "Original OLS" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(within(screen.getByTestId("panel-host-tabs")).getByRole("tab", { name: "Report review" })).toBeInTheDocument();
    sessionStorage.removeItem("workbench:node-panel:/proj");
  });

  it("keeps project settings out of the inner workbench action bar", async () => {
    mountAt("/?tab=lineage");
    await screen.findByTestId("graph-workbench");

    expect(screen.queryByTestId("workbench-topbar-settings")).toBeNull();
    expect(screen.queryByTestId("topbar-action-generateReport")).toBeNull();
    expect(screen.getByTestId("topbar-action-rerun")).toBeEnabled();
  });

  it("renders the topbar with two view tabs once data loads (Pipeline retired v1.6.7)", async () => {
    mountAt("/?tab=lineage");
    expect(await screen.findByTestId("workspace-topbar")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-view-graph")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-view-table")).toBeInTheDocument();
    // v1.6.7: the Pipeline tab entry is retired (view merges into the graph).
    expect(screen.queryByTestId("workspace-view-pipeline")).toBeNull();
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
    expect(screen.getByRole("tab", { name: "Tables" })).toHaveAttribute("aria-selected", "true");
  });

  it("Pipeline view stays reachable via ?view=pipeline deep link (tab retired v1.6.7)", async () => {
    // The clickable tab is gone, but the "pipeline" ViewMode + PipelineView are
    // kept as a URL deep-link fallback (see WorkbenchTopbar VIEW_TABS comment).
    mountAt("/?tab=lineage&view=pipeline");
    expect(await screen.findByTestId("view-pipeline")).toBeInTheDocument();
    expect(screen.getByTestId("view-pipeline")).toBeVisible();
  });

  it("active tab carries aria-selected=true", async () => {
    mountAt("/?tab=lineage&view=table");
    const tableTab = await screen.findByTestId("workspace-view-table");
    expect(tableTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("workspace-view-graph")).toHaveAttribute(
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

      const [firstNode] = await screen.findAllByTestId("graph-node");
      fireEvent.click(firstNode);

      const drawer = await screen.findByTestId("detail-drawer");
      expect(drawer).toBeInTheDocument();
      expect(screen.getByTestId("workspace-stage")).toContainElement(drawer);
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

  describe("migrated workspace layout", () => {
    it("ignores Classic preferences and keeps one workspace with an independent Agent", async () => {
      mountAt("/?workspace=classic&tab=lineage");
      await screen.findByTestId("workspace-shell");
      expect(screen.queryByTestId("run-rail")).toBeNull();
      expect(screen.getByRole("button", { name: "Analyze" })).toBeInTheDocument();
      expect(screen.getAllByRole("textbox", { name: "Ask Agent" })).toHaveLength(1);
    });
    it("keeps Runs, Logs and Activity reachable when switching to Tables", async () => {
      mountAt("/?tab=lineage&view=table");
      await screen.findByTestId("view-table");
      for (const name of ["Timeline", "Runs", "Logs", "Activity"]) expect(screen.getByRole("tab", { name })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("tab", { name: "Logs" }));
      expect(screen.getByRole("tabpanel")).toBeInTheDocument();
    });
    it("folds the bottom panel while keeping its selected tab", async () => {
      mountAt("/?tab=lineage&panelOpen=0");
      await screen.findByTestId("workspace-shell");
      fireEvent.click(screen.getByRole("tab", { name: "Activity" }));
      fireEvent.click(screen.getByRole("button", { name: "Fold the bottom panel" }));
      expect(screen.queryByRole("tabpanel")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Open the bottom panel" }));
      expect(screen.getByRole("tab", { name: "Activity" })).toHaveAttribute("aria-selected", "true");
    });
    it("keeps a single composer available independently of the bottom panel", async () => {
      mountAt("/?tab=lineage&panel=agent");
      await screen.findByTestId("workspace-shell");
      expect(screen.getAllByRole("textbox", { name: "Ask Agent" })).toHaveLength(1);
      fireEvent.click(screen.getByRole("tab", { name: "Logs" }));
      fireEvent.click(screen.getByRole("button", { name: "Fold the bottom panel" }));
      expect(screen.getByRole("textbox", { name: "Ask Agent" })).toBeEnabled();
    });
    it("resizes the document inspector on Tables", async () => {
      mountAt("/?tab=lineage&view=table&tabs=n1&active=n1");
      await screen.findByTestId("detail-drawer");
      const splitter = screen.getByTestId("panel-host-resizer");
      dispatchHorizontalPointerDrag(splitter, "pointerdown", 1000);
      dispatchHorizontalPointerDrag(splitter, "pointermove", 900);
      dispatchHorizontalPointerDrag(splitter, "pointerup", 900);
      expect(sessionStorage.getItem("workbench:detailDrawerWidth:/proj")).toBe("560");
    });
    it("persists bottom panel height without moving the Agent", async () => {
      mountAt("/?tab=lineage");
      await screen.findByTestId("workspace-shell");
      fireEvent.click(screen.getByRole("tab", { name: "Logs" }));
      const splitter = screen.getByRole("separator", { name: "Bottom panel height" });
      fireEvent.keyDown(splitter, { key: "ArrowUp" });
      expect(sessionStorage.getItem("workbench:bottom:height:/proj")).toBe("264");
      expect(screen.getByRole("textbox", { name: "Ask Agent" })).toBeEnabled();
    });
    it("passes project identity to Runs on slug routes", async () => {
      vi.spyOn(api, "fetchRuns").mockResolvedValue({ runs: [{ run_id: "saved", status: "completed" } as never] });
      mountAt("/p/slug/graph?view=table");
      await screen.findByTestId("view-table");
      fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
      expect(await screen.findByTestId("ws-run-saved")).toBeInTheDocument();
      expect(api.fetchRuns).toHaveBeenCalledWith("/proj");
    });
  });

  it("switches active head and selects focus after context-driven rerun success", async () => {
    mountForestAt("/?tab=lineage&tabs=hash_model&active=hash_model");
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();
    expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
      "Original OLS",
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Covariance" }), { target: { value: "robust" } });
    confirmOperationRerun();

    await waitFor(() =>
      expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
      {timeout: 3000},
    );
    expect(screen.getByTestId("forest-heads")).toHaveClass(
      "wb-run-version-picker",
    );
    expect(screen.getByTestId("forest-head-run_child")).toHaveClass(
      "wb-run-version-picker__button",
    );
    await waitFor(() =>
      expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
        "Child OLS",
      ),
    );
  });

  it("selects the child run node by op node when the response focus key still names the parent", async () => {
    vi.spyOn(api, "fetchRunDetail").mockResolvedValue({status: "completed"} as never);
    vi.spyOn(api, "fetchProjectForest")
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
      produced_lineage: null,
      accepted_context: null,
});
    render(
      <MemoryRouter
        initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}
        future={routerFuture}
      >
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Covariance" }), { target: { value: "robust" } });
    confirmOperationRerun();

    await waitFor(() =>
      expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
      {timeout: 3000},
    );
    await waitFor(() =>
      expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
        "Child OLS",
      ),
    );
  });

  it("keeps polling and selects the child run node when context rerun returns focus null before the child is indexed", async () => {
    vi.spyOn(api, "fetchRunDetail").mockResolvedValue({status: "completed"} as never);
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
      produced_lineage: null,
      accepted_context: null,
});
    render(
      <MemoryRouter
        initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}
        future={routerFuture}
      >
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Covariance" }), { target: { value: "robust" } });
    confirmOperationRerun();

    await waitFor(() => expect(api.fetchProjectForest).toHaveBeenCalledTimes(3), {timeout: 3000});
    await waitFor(() =>
      expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
      {timeout: 3000},
    );
    await waitFor(() =>
      expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
        "Child OLS",
      ),
    );
  });

  it("uses produced lineage pending_index to poll by rerun request id without guessing runs[0]", async () => {
    vi.spyOn(api, "fetchRunDetail").mockResolvedValue({status: "completed"} as never);
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
      accepted_context: null,
});
    render(
      <MemoryRouter
        initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}
        future={routerFuture}
      >
        <Routes>
          <Route
            path="*"
            element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Covariance" }), { target: { value: "robust" } });
    confirmOperationRerun();

    await waitFor(() => expect(api.fetchProjectForest).toHaveBeenCalledTimes(3), {timeout: 3000});
    await waitFor(() =>
      expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
      {timeout: 3000},
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
        future={routerFuture}
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
      <MemoryRouter initialEntries={["/?tab=lineage"]} future={routerFuture}>
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
              uploadDraftNodeFixture({
                upload: { sha256: "sha_abc", filename: "data.xlsx" },
                sheet_names: ["Sheet1"],
              }),
              tableDraftNodeFixture({
                params: { sheet_name: "Sheet1", transpose: false },
                columns: ["y", "x"],
                status: "configured",
              }),
              modelDraftNodeFixture({ params: { y: "y", x: ["x"] }, status: "configured" }),
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
        <MemoryRouter initialEntries={[initialEntry]} future={routerFuture}>
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
      expect(screen.getByText("Start with your data")).toBeInTheDocument();
      expect(screen.getByTestId("genesis-cta")).toHaveTextContent(
        "Import data",
      );
      // The empty canvas replaces the shell entirely.
      expect(screen.queryByTestId("workbench-route")).toBeNull();
    });

    it("waits for persisted genesis-draft hydration before exposing the empty canvas", async () => {
      let resolveSummaries!: (summaries: api.PipelineDraftSummary[]) => void;
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockReturnValue(
        new Promise<api.PipelineDraftSummary[]>((resolve) => {
          resolveSummaries = resolve;
        }),
      );
      vi.spyOn(api, "getPipelineDraft").mockResolvedValue(genesisDraftResponse());
      mountHome();

      await waitFor(() => expect(api.listPipelineDrafts).toHaveBeenCalledWith("/proj"));
      expect(screen.queryByTestId("workspace-project-start")).toBeNull();

      await act(async () => {
        resolveSummaries([
          draftSummaryFixture({ draft_id: "genesis_d1", draft_hash: "h_genesis", model_type: null }),
        ]);
        await Promise.resolve();
      });
      expect(await screen.findByTestId("graph-workbench")).toBeInTheDocument();
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

    it("opens the genesis wizard from the handoff URL when the project already has runs", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(forestResponse());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
      mountHome(undefined, "/p/slug/graph?genesis=1");

      expect(await screen.findByTestId("genesis-wizard-drawer")).toBeInTheDocument();
      expect(screen.getByTestId("genesis-wizard")).toBeInTheDocument();
    });

    it("existing projects expose a visible New analysis action after the drawer closes", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(forestResponse());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
      mountHome(undefined, "/p/slug/graph?open_genesis=1");

      expect(await screen.findByTestId("genesis-wizard-drawer")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await waitFor(() =>
        expect(screen.queryByTestId("genesis-wizard-drawer")).toBeNull(),
      );

      const reopen = screen.getByRole("button", { name: "New analysis" });
      fireEvent.click(reopen);

      expect(screen.getByTestId("genesis-wizard-drawer")).toBeInTheDocument();
    });

    it("consumes ?genesis=1 when the wizard closes so it does not reopen", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
      let currentSearch: string | null = null;
      function LocationProbe() {
        currentSearch = useLocation().search;
        return null;
      }
      render(
        <MemoryRouter
          initialEntries={["/p/slug/graph?genesis=1"]}
          future={routerFuture}
        >
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
      // Keep the handoff param while the drawer is open so route-state writes
      // cannot race the open transition. Closing the drawer consumes it.
      expect(currentSearch).toContain("genesis");

      fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await waitFor(() =>
        expect(screen.queryByTestId("genesis-wizard-drawer")).toBeNull(),
      );
      await waitFor(() => expect(currentSearch).not.toContain("genesis"));
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
      expect(screen.queryByTestId("workspace-project-start")).toBeNull();
    });

    it("renders a guardrail-blocked run as blocked rather than legacy", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(allLegacyProjectBody());
      vi.spyOn(api, "fetchRunDetail").mockResolvedValue({
        run_id: "run_blocked",
        status: "blocked",
        errors: { issues: [{ code: "MIN_MODEL_N" }] },
      } as never);

      mountHome("run_blocked");

      expect(await screen.findByTestId("blocked-run-notice")).toHaveTextContent(
        "This analysis was blocked before lineage was recorded.",
      );
      expect(screen.queryByTestId("legacy-banner")).toBeNull();
      expect(api.getRunGraph).not.toHaveBeenCalledWith("/proj", "run_blocked");
    });

    it("all-legacy projects show an honest legacy empty state while keeping the genesis CTA", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(allLegacyProjectBody());
      mountHome();

      expect(await screen.findByTestId("genesis-cta")).toBeInTheDocument();
      expect(
        screen.getByText(/2 earlier runs predate lineage indexing/),
      ).toBeInTheDocument();
      expect(screen.queryByText("This project has no data yet.")).toBeNull();
    });

    it("zero-run projects with a genesis draft render the draft island on the canvas instead of the empty canvas", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([
        draftSummaryFixture({ draft_id: "genesis_d1", draft_hash: "h_genesis", model_type: null }),
      ]);
      vi.spyOn(api, "getPipelineDraft").mockResolvedValue(genesisDraftResponse());
      mountHome();

      expect(await screen.findByTestId("graph-workbench")).toBeInTheDocument();
      expect(screen.queryByTestId("workspace-project-start")).toBeNull();
      expect(api.getPipelineDraft).toHaveBeenCalledWith("/proj", "genesis_d1");
    });

    it("draft-only genesis reload exposes a topbar resume entry back into the wizard", async () => {
      vi.spyOn(api, "fetchProjectForest").mockResolvedValue(emptyForestBody());
      vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([
        draftSummaryFixture({ draft_id: "genesis_d1", draft_hash: "h_genesis", model_type: null }),
      ]);
      vi.spyOn(api, "getPipelineDraft").mockResolvedValue(genesisDraftResponse());
      mountHome();

      expect(await screen.findByTestId("graph-workbench")).toBeInTheDocument();
      const resume = await screen.findByRole("button", { name: "Resume new analysis" });
      expect(resume).toBeEnabled();
      fireEvent.click(resume);

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
describe("manual rerun — terminal observation", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function flush(ms = 0) {
    await act(async () => {await vi.advanceTimersByTimeAsync(ms);});
  }

  async function submitManualChild(status: () => string, projectHome = false, deferredPost?: Promise<api.RerunResponseV1>) {
    let submitted = false;
    const source = forestResponse("hash_model");
    source.heads = source.heads.filter(head => head.run_id === "run_a");
    vi.spyOn(api, "fetchProjectForest").mockImplementation(async () => submitted ? forkedForestResponse() : source);
    vi.spyOn(api, "fetchRunDetail").mockImplementation(async (_root, runId) => ({
      status: runId === "run_child" ? status() : "completed",
      errors: {issues: runId === "run_child" && status() === "failed"
        ? [{severity: "BLOCKER", code: "WORKFLOW_FAILED", message: "'hac'"}] : []},
    }) as never);
    const submit = vi.spyOn(api, "rerunFromNode").mockImplementation(async () => {
      submitted = true;
      if (deferredPost) return deferredPost;
      return {run_id: "run_child", new_run_id: "run_child", new_active_head_id: "run_child", focus: null,
        rerun_from: {owner_run_id: "run_a", op_node_id: "model:ols_1", node_hash: "hash_model", forest_node_key: "hash_model"},
        produced_lineage: null, accepted_context: null} as api.RerunResponseV1;
    });
    const mounted = render(<MemoryRouter initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]} future={routerFuture}>
      <Routes><Route path="*" element={projectHome ? <WorkbenchHome projectRoot="/proj"/> : <WorkbenchRouteContainer projectRoot="/proj" runId="run_a"/>}/></Routes>
    </MemoryRouter>);
    await flush();
    fireEvent.change(screen.getByRole("combobox", {name: "Covariance"}), {target: {value: "robust"}});
    confirmOperationRerun();
    await flush();
    return {submit, ...mounted};
  }

  it.each([false, true])("does not let a draft POST replace the manual run owner (POST pending %s)", async deferred => {
    vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([draftSummaryFixture({draft_id: "d1", source_node_hash: "hash_model", source_op_node_id: "model:ols_1"})]);
    const execute = vi.spyOn(api, "executePipelineDraft").mockResolvedValue({
      run_id: "draft_child", focus: {run_id: "draft_child", poll: {rerun_from_op_node_id: "model:ols_1"}}, produced_lineage: {},
    } as never);
    let finish!: (response: api.RerunResponseV1) => void;
    const waiting = deferred ? new Promise<api.RerunResponseV1>(resolve => {finish = resolve;}) : undefined;
    const {submit} = await submitManualChild(() => "running", false, waiting);
    await act(async () => {submissionProbe.draft!.onExecute("d1");});
    await flush();
    expect(execute).not.toHaveBeenCalled();
    expect(submissionProbe.draft!.busy).toBe(true);
    if (deferred) await act(async () => {finish({run_id: "run_child", rerun_from: {op_node_id: "model:ols_1"}} as api.RerunResponseV1);});
    await flush(1000);
    expect(screen.getByTestId("operation-rerun-receipt")).toHaveTextContent("running");
    expect(submit).toHaveBeenCalledOnce();
  });

  it.each([false, true])("retains the source tab/edit and reports the actual failed child instead of completion (project home %s)", async projectHome => {
    const {submit} = await submitManualChild(() => "failed", projectHome);
    expect(document.getElementById("detail-drawer-title")).toHaveTextContent("Original OLS");
    expect(screen.queryByText(/Rerun completed/)).toBeNull();
    await flush(1000);
    expect(document.getElementById("detail-drawer-title")).toHaveTextContent("Original OLS");
    expect(screen.getByRole("combobox", {name: "Covariance"})).toHaveValue("robust");
    const receipt = screen.getByTestId("operation-rerun-receipt");
    expect(receipt).toHaveAttribute("role", "alert");
    expect(receipt).toHaveTextContent("run_child");
    expect(receipt).toHaveTextContent("failed");
    expect(receipt).toHaveTextContent("WORKFLOW_FAILED: 'hac'");
    expect(within(receipt).getByRole("link", {name: "Open child run"})).toHaveAttribute("href", "/runs/run_child?project_root=%2Fproj&tab=overview");
    await flush(5000);
    expect(submit).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("operation-rerun-done")).toBeNull();
  });

  it("keeps a child with unconfirmed status visible and openable after the shared retry budget", async () => {
    const {submit} = await submitManualChild(() => "running");
    vi.mocked(api.fetchRunDetail).mockRejectedValue(new Error("Status unavailable"));
    for (let index = 0; index < 30; index++) await flush(1000);
    const receipt = screen.getByTestId("operation-rerun-receipt");
    expect(receipt).toHaveAttribute("role", "alert");
    expect(receipt).toHaveTextContent("unconfirmed");
    expect(receipt).toHaveTextContent("Status unavailable");
    expect(within(receipt).getByRole("link", {name: "Open child run"})).toBeInTheDocument();
    expect(screen.getByRole("combobox", {name: "Covariance"})).toHaveValue("robust");
    const polls = vi.mocked(api.fetchRunDetail).mock.calls.length;
    await flush(5000);
    expect(api.fetchRunDetail).toHaveBeenCalledTimes(polls);
    expect(submit).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("operation-rerun-done")).toBeNull();
  });

  it("focuses the child only after its successful terminal status is confirmed", async () => {
    let status = "running";
    const {submit} = await submitManualChild(() => status);
    expect(document.getElementById("detail-drawer-title")).toHaveTextContent("Original OLS");
    await flush(1000);
    expect(document.getElementById("detail-drawer-title")).toHaveTextContent("Original OLS");
    expect(screen.getByTestId("operation-rerun-receipt")).toHaveTextContent("running");
    expect(screen.getByTestId("operation-rerun-submit")).toBeDisabled();
    status = "completed";
    await flush(1000);
    expect(document.getElementById("detail-drawer-title")).toHaveTextContent("Child OLS");
    expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute("aria-pressed", "true");
    expect(submit).toHaveBeenCalledOnce();
  });
});

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
        hash_source: forestNodeFixture({
          id: "source:upload",
          kind: "dataset_stage",
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
        }),
        hash_model: forestNodeFixture({
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
        }),
      },
      edges: [forestEdgeFixture({ source: "hash_source", target: "hash_model" })],
      heads: [
        forestHeadFixture({
          run_id: "run_a",
          head_node_hash: "hash_model",
          from_node: null,
          rerun_of: null,
          rerun_reason: null,
          status: "completed",
          created_at: "2026-06-27T00:00:00Z",
        }),
      ],
    };
  }

  function draftSummary(): api.PipelineDraftSummary {
    return draftSummaryFixture({
      draft_id: "d1",
      draft_hash: "h1",
      source_run_id: "run_a",
      source_model_node_id: "model:ols_1",
      source_op_node_id: "model:ols_1",
      source_node_hash: "hash_model",
      model_type: "ols",
    });
  }

  function draftGet(withNotebook = false): api.PipelineDraftResponse {
    const response: api.PipelineDraftResponse = {
      draft_hash: "h1",
      draft: draftFixture({
        draft_id: "d1",
        created_at: "t",
        updated_at: "t",
        created_from: runCreatedFromFixture({
          source_run_id: "run_a",
          source_node_hash: "hash_model",
          source_op_node_id: "model:ols_1",
        }),
        graph: {
          nodes: [modelDraftNodeFixture({ params: { y: "y", x: ["x"] }, status: "configured" })],
          edges: [],
        },
        default_execution_mode: "rerun_child",
      }),
    };
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
        future={routerFuture}
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

  it("does not let a manual POST replace a pending draft owner", async () => {
    const {executeSpy} = await mountAndExecute({forestBody: soloForest, runDetail: () => ({status: "running"})});
    const manual = vi.spyOn(api, "rerunFromNode").mockResolvedValue({run_id: "manual_child", rerun_from: {op_node_id: "model:ols_1"}} as api.RerunResponseV1);
    await act(async () => {
      await expect(submissionProbe.rerun!.submitRerun({context: {
        operation_target: {owner_run_id: "run_a", op_node_id: "model:ols_1", node_hash: "hash_model"},
        selection: {}, ownership: {},
      } as never, opOverrides: {covariance: "robust"}})).rejects.toThrow(/another run/i);
    });
    expect(manual).not.toHaveBeenCalled();
    expect(executeSpy).toHaveBeenCalledOnce();
    await flush(1000);
    expect(screen.getByTestId("graph-node-lifecycle")).toHaveAttribute("data-lifecycle", "pending");
  });

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
    fireEvent.click(screen.getByRole("tab", { name: "Runs" }));
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
