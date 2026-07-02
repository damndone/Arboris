import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LineageContext } from "../../lineage/LineageContext";
import type { LineageContextValue } from "../../lineage/LineageContext";
import type { GraphViewModel } from "../../lineage/api/graphViewTypes";
import type { RunDetail } from "../../api";
import { TableView } from "./TableView";

const mockFetch = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    fetchRunDetail: () => Promise.resolve(mockFetch.current as RunDetail),
  };
});

function model(runId = "run-1"): GraphViewModel {
  return {
    schemaVersion: 1,
    runId,
    legacy: false,
    nodes: [],
    edges: [],
    stats: {} as GraphViewModel["stats"],
  };
}

function renderTable(m: GraphViewModel = model()) {
  const ctx: LineageContextValue = {
    model: m,
    selectedKey: null,
    select: () => {},
  };
  return render(
    <MemoryRouter initialEntries={["/runs/run-1?project_root=/tmp/demo"]}>
      <LineageContext.Provider value={ctx}>
        <TableView />
      </LineageContext.Provider>
    </MemoryRouter>,
  );
}

describe("TableView", () => {
  beforeEach(() => {
    mockFetch.current = null;
  });

  it("renders a coefficient table from model_results", async () => {
    mockFetch.current = {
      model_results: [
        {
          model_id: "m1",
          model_type: "ols",
          r_squared: 0.42,
          nobs: 100,
          coefficients: {
            education: { estimate: 0.08, std_error: 0.01, p_value: 0.001, p_value_display: "<0.001" },
            age: { estimate: 0.02, std_error: 0.005, p_value: 0.04, p_value_display: "0.04" },
          },
        },
      ],
      artifact_counts: {},
    } as unknown as RunDetail;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-coefficients")).toBeTruthy());
    expect(screen.getByText("education")).toBeTruthy();
    expect(screen.getByText("age")).toBeTruthy();
    // estimate rendered
    expect(screen.getByText("0.08")).toBeTruthy();
  });

  it("renders an artifact summary from artifact_counts", async () => {
    mockFetch.current = {
      model_results: [],
      artifact_counts: { figure: 3, table: 2 },
    } as unknown as RunDetail;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-artifacts")).toBeTruthy());
    expect(screen.getByText(/figure/)).toBeTruthy();
    expect(screen.getByText(/3/)).toBeTruthy();
  });

  it("shows an empty state when the run has no results or artifacts", async () => {
    mockFetch.current = {
      model_results: [],
      artifact_counts: {},
    } as unknown as RunDetail;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-empty")).toBeTruthy());
  });

  it("keeps the view=table switcher contract (data-view)", async () => {
    mockFetch.current = { model_results: [], artifact_counts: {} } as unknown as RunDetail;
    renderTable();
    expect(screen.getByTestId("view-table").getAttribute("data-view")).toBe("table");
    // settle the async fetch so no act() warning leaks into later tests
    await waitFor(() => expect(screen.getByTestId("table-view-empty")).toBeTruthy());
  });
});
