import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetVariable } from "./dataViewApi";

const api = {
  listDatasets: vi.fn(),
  fetchDatasetPage: vi.fn(),
  fetchDatasetVariables: vi.fn(),
  saveMetadata: vi.fn(),
};

const fetchRunDetail = vi.fn();

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  fetchRunDetail: (...args: unknown[]) => fetchRunDetail(...args),
}));

vi.mock("./dataViewApi", () => ({
  listDatasets: (...args: unknown[]) => api.listDatasets(...args),
  fetchDatasetPage: (...args: unknown[]) => api.fetchDatasetPage(...args),
  fetchDatasetVariables: (...args: unknown[]) => api.fetchDatasetVariables(...args),
  saveMetadata: (...args: unknown[]) => api.saveMetadata(...args),
}));

import { DataView } from "./DataView";
import { buildMetadataPatch } from "./VariableView";
import { ForestContext } from "../workbench/ForestContext";

const variables: DatasetVariable[] = [
  {
    position: 1, name: "educ", type: "numeric", dtype: "float64", missing: 0,
    declared_missing_matches: 1, unique: 5, variable_label: "受教育年限", value_labels: {},
    measurement_level: null, user_missing_values: [-99], min: 9, max: 16, mean: 12,
  },
  {
    position: 2, name: "region", type: "numeric", dtype: "float64", missing: 0,
    declared_missing_matches: 0, unique: 3, variable_label: null,
    value_labels: { "1": "北方", "2": "南方" }, measurement_level: "nominal", user_missing_values: [],
  },
];

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  fetchRunDetail.mockReset();
  fetchRunDetail.mockResolvedValue({ status: "completed" });
  api.listDatasets.mockResolvedValue([
    { node_id: "stage:raw", label: "Raw input data", stage: "source", parent_stage_id: null },
    { node_id: "stage:cleaned", label: "Cleaned data", stage: "clean", parent_stage_id: null },
  ]);
  api.fetchDatasetVariables.mockResolvedValue({ run_id: "r1", node_id: "stage:raw", artifact_id: "a", total_rows: 2, variables });
  api.fetchDatasetPage.mockResolvedValue({
    run_id: "r1", node_id: "stage:raw", artifact_id: "a", columns: ["educ", "region"], total_rows: 2,
    offset: 0, row_numbers: [1, 2], rows: [{ educ: -99, region: 2 }, { educ: 12, region: 1 }],
  });
});

function renderView(setActiveRunId = vi.fn()) {
  render(
    <ForestContext.Provider
      value={{ forest: { heads: [] } as never, activeRunId: "r1", setActiveRunId, refetch: vi.fn() }}
    >
      <DataView projectRoot="/p" />
    </ForestContext.Provider>,
  );
  return setActiveRunId;
}

describe("DataView", () => {
  it("shows stored values, marks declared missing codes and toggles value labels", async () => {
    renderView();
    const grid = await screen.findByTestId("data-grid");
    const cells = within(grid).getAllByRole("cell");
    const coded = cells.find((cell) => cell.textContent === "-99");
    expect(coded).toHaveAttribute("data-declared-missing", "true");
    expect(within(grid).queryByText("南方")).toBeNull();
    fireEvent.click(screen.getByLabelText("Show value labels"));
    expect(within(grid).getByText("南方")).toBeTruthy();
  });

  it("sorts for viewing through the server", async () => {
    renderView();
    await screen.findByTestId("data-grid");
    fireEvent.click(screen.getByRole("button", { name: "educ" }));
    await waitFor(() =>
      expect(api.fetchDatasetPage).toHaveBeenLastCalledWith("/p", "r1", "stage:raw", {
        offset: 0, limit: 100, sortBy: "educ", descending: false,
      }),
    );
  });

  it("reviews metadata edits, saves them as a new run and switches to it", async () => {
    api.saveMetadata.mockResolvedValue({ source_run_id: "r1", run_id: "r2", status: "running" });
    const setActiveRunId = renderView();
    await screen.findByTestId("data-grid");
    fireEvent.click(screen.getByRole("tab", { name: "Variable View" }));
    fireEvent.change(await screen.findByLabelText("Label of region"), { target: { value: "地区" } });
    fireEvent.change(screen.getByLabelText("Missing codes of educ"), { target: { value: "-99, 900..999" } });
    fireEvent.click(screen.getByRole("button", { name: "Review changes (2)" }));
    expect(screen.getByTestId("variable-view-review").textContent).toContain("region · Label: — → 地区");
    fireEvent.click(screen.getByRole("button", { name: "Save as new run" }));
    await waitFor(() => expect(setActiveRunId).toHaveBeenCalledWith("r2"));
    expect(api.saveMetadata).toHaveBeenCalledWith("/p", "r1", {
      variable_labels: { region: "地区" },
      user_missing_values: { educ: [-99, { low: 900, high: 999 }] },
    });
  });

  it("blocks saving malformed input", async () => {
    renderView();
    await screen.findByTestId("data-grid");
    fireEvent.click(screen.getByRole("tab", { name: "Variable View" }));
    fireEvent.change(await screen.findByLabelText("Value labels of region"), { target: { value: "1 North" } });
    expect(screen.getByRole("alert").textContent).toContain("value = label");
    expect(screen.getByRole("button", { name: /Review changes/ })).toBeDisabled();
  });
});

describe("buildMetadataPatch", () => {
  it("emits null to remove a declaration and ignores untouched variables", () => {
    const { patch, changes } = buildMetadataPatch(variables, {
      educ: { label: "受教育年限", values: "", level: "", missing: "" },
      region: { label: "", values: "1 = 北方; 2 = 南方", level: "ordinal", missing: "" },
    });
    expect(patch).toEqual({
      user_missing_values: { educ: null },
      measurement_level: { region: "ordinal" },
    });
    expect(changes).toHaveLength(2);
  });
});

describe("DataView on a run that is still running", () => {
  it("waits for the run to finish before loading its datasets", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchRunDetail.mockReset();
    fetchRunDetail
      .mockResolvedValueOnce({ status: "running" })
      .mockResolvedValueOnce({ status: "completed" });
    renderView();
    expect(await screen.findByTestId("data-view-running")).toBeTruthy();
    expect(api.listDatasets).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1600);
    expect(await screen.findByTestId("data-grid")).toBeTruthy();
    expect(api.listDatasets).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});

describe("DataView switching to a new, running run", () => {
  it("does not request the new run's data before it finishes", async () => {
    api.saveMetadata.mockResolvedValue({ source_run_id: "r1", run_id: "r2", status: "running" });
    fetchRunDetail.mockImplementation(async (_root: string, runId: string) => ({
      status: runId === "r1" ? "completed" : "running",
    }));
    function Harness() {
      const [active, setActive] = useState("r1");
      return (
        <ForestContext.Provider
          value={{ forest: { heads: [] } as never, activeRunId: active, setActiveRunId: setActive, refetch: vi.fn() }}
        >
          <DataView projectRoot="/p" />
        </ForestContext.Provider>
      );
    }
    render(<Harness />);
    await screen.findByTestId("data-grid");
    fireEvent.click(screen.getByRole("tab", { name: "Variable View" }));
    fireEvent.change(await screen.findByLabelText("Label of region"), { target: { value: "地区" } });
    fireEvent.click(screen.getByRole("button", { name: "Review changes (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "Save as new run" }));
    expect(await screen.findByTestId("data-view-running")).toBeTruthy();
    const requestedRuns = [...api.listDatasets.mock.calls, ...api.fetchDatasetVariables.mock.calls].map((call) => call[1]);
    expect(requestedRuns).not.toContain("r2");
  });
});
