import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";
import { RunsTable } from "./RunsTable";

vi.mock("../lineage/runRail/useRunHistory", () => ({
  useRunHistory: () => ({
    runs: [
      { run_id: "20261007_100000_000000_aaaaaaaa", started_at: "2026-10-07T10:00:00Z", status: "completed", y: "wage", x: ["educ", "age"], mode: null },
      { run_id: "20261008_100000_000000_bbbbbbbb", started_at: "2026-10-08T10:00:00Z", status: "failed", y: null, x: null, mode: "statistical" },
    ],
    loading: false,
    error: null,
    refresh: () => undefined,
  }),
}));
vi.mock("../workbench/ForestContext", () => ({ useForest: () => ({ activeRunId: "20261007_100000_000000_aaaaaaaa" }) }));

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

describe("RunsTable", () => {
  test("lists runs newest first with what they contain and their status; the shown run is marked", () => {
    render(
      <MemoryRouter initialEntries={["/p/x/graph"]}>
        <RunsTable projectRoot="/proj" />
      </MemoryRouter>,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Analysis 2");
    expect(screen.getByText("20261008_100000_000000_bbbbbbbb")).not.toBeVisible();
    expect(rows[0]).toHaveTextContent("failed");
    expect(rows[1]).toHaveTextContent("wage on educ, age");
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: "View all runs" })).toHaveAttribute("href", "/runs?project_root=%2Fproj");
  });

  test("Show on map opens the run the way the rail did", () => {
    render(
      <MemoryRouter initialEntries={["/p/x/graph?view=graph"]}>
        <Routes>
          <Route path="*" element={<><RunsTable projectRoot="/proj" /><Where /></>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show on map" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/runs/20261008_100000_000000_bbbbbbbb?project_root=%2Fproj&tab=lineage&view=graph");
  });
});
