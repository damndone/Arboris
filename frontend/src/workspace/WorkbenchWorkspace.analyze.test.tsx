import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ForestContextValue } from "../workbench/ForestContext";
import type { WorkspaceShellProps } from "./WorkspaceShell";
import * as dataApi from "../dataView/dataViewApi";
import * as manualApi from "../manual/manualApi";
import { WorkbenchWorkspace } from "./WorkbenchWorkspace";

const context = vi.hoisted(() => ({
  selectedKey: null as string | null,
  forest: null as ForestContextValue | null,
}));

vi.mock("../workbench/WorkbenchStateProvider", () => ({
  useWorkbench: () => ({ state: { view: "graph", selectedKey: context.selectedKey },
    dispatch: { setView: vi.fn(), selectByCanvasClick: vi.fn() } }),
}));
vi.mock("../workbench/ForestContext", () => ({ useForest: () => context.forest }));
vi.mock("../lineage/LineageContext", () => ({
  useLineage: () => ({ model: { nodes: [], edges: [], legacy: false, runId: "merged-forest-hash" } }),
}));
vi.mock("../workbench/useTopbarActions", () => ({ useTopbarActions: () => ({ actions: [], actionCtx: null }) }));
vi.mock("./WorkspaceTopbar", () => ({ WorkspaceTopbar: ({ actions }: { actions: ReactNode }) => <header>{actions}</header> }));
vi.mock("./WorkspaceShell", () => ({ WorkspaceShell: ({ topbar, stage }: WorkspaceShellProps) => <>{topbar(undefined as never)}{stage}</> }));
vi.mock("./TimelinePanel", () => ({
  useTimeline: () => ({ value: null, error: null, refresh: vi.fn() }),
  timelineSummary: () => "", TimelinePanel: () => null,
}));
vi.mock("../manual/manualApi", async (original) => ({
  ...await original<typeof manualApi>(), catalog: vi.fn(), execute: vi.fn(),
}));
vi.mock("../dataView/dataViewApi", () => ({ listDatasets: vi.fn(), fetchDatasetPage: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  context.selectedKey = "eight-row-hash::stage:cleaned";
  context.forest = {
    activeRunId: "six-row-head", setActiveRunId: vi.fn(),
    forest: {
      nodes: [
        { nodeKey: "eight-row-hash::stage:cleaned", opNodeId: "stage:cleaned", kind: "dataset_stage", runs: ["eight-row-source"] },
        { nodeKey: "six-row-hash::stage:cleaned", opNodeId: "stage:cleaned", kind: "dataset_stage", runs: ["six-row-head"] },
      ],
      heads: [{ runId: "six-row-head" }, { runId: "eight-row-source" }], edges: [],
    },
  } as unknown as ForestContextValue;
  vi.mocked(dataApi.listDatasets).mockResolvedValue([
    { node_id: "stage:raw", label: "Raw input data" },
    { node_id: "stage:cleaned", label: "Cleaned data" },
  ] as never);
  vi.mocked(dataApi.fetchDatasetPage).mockImplementation(async (_root, run, node) => ({
    artifact_id: `${run}/${node === "stage:raw" ? "raw.csv" : "cleaned.parquet"}`, columns: ["x"],
  }) as never);
  vi.mocked(manualApi.catalog).mockResolvedValue({ catalog_version: "workbench.operations/v1", operations: [], total: 0 });
});
afterEach(cleanup);

function workspace() {
  return <MemoryRouter><WorkbenchWorkspace runId="six-row-head" projectRoot="/test"
    stageTabs={null} stagePanel={null} stagePanelKind={null} reportFocusRequest={0}
    onOpenSettings={vi.fn()} overlays={null} /></MemoryRouter>;
}

it("opens global Analyze on the selected dataset's owner and logical node, not the active head or forest hash", async () => {
  render(workspace());
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() => expect(dataApi.listDatasets).toHaveBeenCalledWith("/test", "eight-row-source"));
  await waitFor(() => expect(screen.getByLabelText("Analysis target")).toHaveValue("1"));
  expect(manualApi.catalog).toHaveBeenLastCalledWith("/test", {
    kind: "dataset_node", run_id: "eight-row-source", node_id: "stage:cleaned", artifact_id: "eight-row-source/cleaned.parquet",
  });
  expect(dataApi.listDatasets).not.toHaveBeenCalledWith("/test", "six-row-head");
  expect(manualApi.execute).not.toHaveBeenCalled();
});

it("preserves the head's normal default when no node is selected", async () => {
  context.selectedKey = null;
  render(workspace());
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() => expect(screen.getByLabelText("Analysis target")).toHaveValue("0"));
  expect(manualApi.catalog).toHaveBeenLastCalledWith("/test", {
    kind: "dataset_node", run_id: "six-row-head", node_id: "stage:raw", artifact_id: "six-row-head/raw.csv",
  });
});

it("does not substitute head data when the explicit graph selection no longer exists", async () => {
  context.selectedKey = "removed-node-hash";
  render(workspace());
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/selected.*unavailable/i);
  expect(dataApi.listDatasets).not.toHaveBeenCalled();
  expect(manualApi.execute).not.toHaveBeenCalled();
});

it("keeps the selected dataset unbound when the owner no longer exposes that node", async () => {
  vi.mocked(dataApi.listDatasets).mockResolvedValue([{ node_id: "stage:raw", label: "Raw input data" }] as never);
  render(workspace());
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/selected.*unavailable/i);
  expect(screen.getByLabelText("Analysis target")).toHaveValue("");
  expect(manualApi.catalog).not.toHaveBeenCalledWith("/test", expect.objectContaining({ node_id: "stage:raw" }));
  expect(manualApi.execute).not.toHaveBeenCalled();
});

it("captures the current selection each time Analyze is reopened", async () => {
  const view = render(workspace());
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() => expect(screen.getByLabelText("Analysis target")).toHaveValue("1"));
  fireEvent.click(screen.getByRole("button", { name: "Close Analyze" }));
  context.selectedKey = "six-row-hash::stage:cleaned";
  view.rerender(workspace());
  fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
  await waitFor(() => expect(manualApi.catalog).toHaveBeenLastCalledWith("/test", {
    kind: "dataset_node", run_id: "six-row-head", node_id: "stage:cleaned", artifact_id: "six-row-head/cleaned.parquet",
  }));
});
