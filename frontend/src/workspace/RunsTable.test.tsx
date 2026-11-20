import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { RunsTable } from "./RunsTable";
import { RailRefreshContext } from "../workbench/RailRefreshContext";
import { fetchRuns } from "../api";
import { runDetailFixture } from "../apiFixtures";

vi.mock("../api", async (original) => ({ ...await original<typeof import("../api")>(), fetchRuns: vi.fn() }));
vi.mock("../workbench/ForestContext", () => ({ useForest: () => ({ activeRunId: "new" }) }));

function Probe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
function mount(token = 0) {
  return render(<MemoryRouter initialEntries={["/p/x/graph?view=table"]}>
    <RailRefreshContext.Provider value={token}><RunsTable projectRoot="/proj" /></RailRefreshContext.Provider>
    <Probe />
  </MemoryRouter>);
}
beforeEach(() => {
  vi.mocked(fetchRuns).mockReset();
  vi.mocked(fetchRuns).mockResolvedValue({ runs: [
    runDetailFixture({ run_id: "old", y: "wage", x: ["educ", "age"], started_at: "2026-10-19T01:00:00Z", status: "completed" }),
    runDetailFixture({ run_id: "new", started_at: "2026-10-21T01:00:00Z", status: "completed" }),
    runDetailFixture({ run_id: "" }),
  ] });
});
test("shows the complete history and count without a link that returns to the same map", async () => {
  mount();
  const rows = await screen.findAllByTestId(/^ws-run-/);
  expect(rows.map(row => row.dataset.testid)).toEqual(["ws-run-new", "ws-run-old"]);
  expect(rows[0]).toHaveAttribute("aria-current", "true");
  expect(rows[0]).toHaveTextContent("completed");
  expect(rows[1]).toHaveTextContent("wage on educ, age");
  expect(screen.getByText("new", { exact: true })).not.toBeVisible();
  expect(screen.getByText("All 2 runs")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "View all runs" })).not.toBeInTheDocument();
});
test("switching runs preserves the view and project without a model call", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Show on map" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/runs/old?project_root=%2Fproj&tab=lineage&view=table");
});
test("surfaces loading, empty history and fetch failures", async () => {
  vi.mocked(fetchRuns).mockResolvedValue({ runs: [] });
  mount();
  expect(screen.getByText("Loading runs…")).toBeInTheDocument();
  expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
});
test("keeps fetch failures visible", async () => {
  vi.mocked(fetchRuns).mockRejectedValue(new Error("history unavailable"));
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("history unavailable");
});
test("refreshes immediately after a newly indexed run without waiting for polling", async () => {
  const renderTree = (token: number) => <MemoryRouter><RailRefreshContext.Provider value={token}>
    <RunsTable projectRoot="/proj" />
  </RailRefreshContext.Provider></MemoryRouter>;
  const { rerender } = render(renderTree(0));
  await screen.findByTestId("ws-run-new");
  expect(fetchRuns).toHaveBeenCalledTimes(1);
  vi.mocked(fetchRuns).mockResolvedValue({ runs: [runDetailFixture({ run_id: "indexed" })] });
  rerender(renderTree(1));
  await waitFor(() => expect(fetchRuns).toHaveBeenCalledTimes(2));
  expect(await screen.findByTestId("ws-run-indexed")).toBeInTheDocument();
});
