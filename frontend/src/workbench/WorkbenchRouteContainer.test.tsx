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
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchHome, WorkbenchRouteContainer } from "./WorkbenchRouteContainer";
import * as api from "../api";
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
      expect(screen.getByText("这个项目还没有数据")).toBeInTheDocument();
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
        screen.getByText(/该项目的 2 个 run 早于血缘索引/),
      ).toBeInTheDocument();
      expect(screen.queryByText("这个项目还没有数据")).toBeNull();
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
  });
});
