/* RunHistoryRail.test.tsx — V1.5.1 T3'.
 *
 * Mounts the rail inside a MemoryRouter so useParams + useSearchParams
 * resolve. The data layer is mocked at the fetchRuns boundary (same
 * pattern as useRunHistory.test.ts) so we test the rail's rendering /
 * navigation contract without a network.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

const { fetchRunsMock } = vi.hoisted(() => ({ fetchRunsMock: vi.fn() }));
vi.mock("../../api", async () => {
  const mod = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...mod, fetchRuns: fetchRunsMock };
});

import { RunHistoryRail } from "./RunHistoryRail";

function LocationSpy({ recordTo }: { recordTo: { url?: string } }) {
  const loc = useLocation();
  recordTo.url = `${loc.pathname}${loc.search}`;
  return null;
}

function harness(initialEntries: string[], record: { url?: string } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route
          path="/runs/:runId"
          element={
            <>
              <RunHistoryRail />
              <LocationSpy recordTo={record} />
            </>
          }
        />
        <Route
          path="/runs"
          element={
            <>
              <LocationSpy recordTo={record} />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  fetchRunsMock.mockReset();
});

afterEach(() => {
  // Make sure pending timers (from the 30s polling) don't bleed across tests.
  vi.useRealTimers();
});

describe("RunHistoryRail", () => {
  it("renders 'Loading…' while the first fetch is pending", () => {
    fetchRunsMock.mockReturnValue(new Promise(() => {})); // never resolves
    harness(["/runs/r-a?project_root=/tmp/p"]);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.getByLabelText("Run history")).toBeInTheDocument();
  });

  it("renders a row per fetched run with short id + status pill", async () => {
    fetchRunsMock.mockResolvedValue({
      runs: [
        {
          run_id: "20260525_210044_142101_055d5cbd",
          status: "completed",
          mode: "auto",
          started_at: new Date(Date.now() - 60_000).toISOString(),
          y: null,
          x: null,
        },
        {
          run_id: "20260525_205959_111111_ffffffff",
          status: "failed",
          mode: "auto",
          started_at: new Date(Date.now() - 120_000).toISOString(),
          y: null,
          x: null,
        },
      ],
    });
    harness(["/runs/20260525_210044_142101_055d5cbd?project_root=/tmp/p"]);
    await waitFor(() =>
      expect(
        screen.getByTestId("run-rail-row-20260525_210044_142101_055d5cbd"),
      ).toBeInTheDocument(),
    );
    // Short id renders as the 8-char tail
    expect(screen.getByText("055d5cbd")).toBeInTheDocument();
    expect(screen.getByText("ffffffff")).toBeInTheDocument();
    // Status pill text
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("marks the URL :runId row as aria-current + data-active", async () => {
    fetchRunsMock.mockResolvedValue({
      runs: [
        { run_id: "r-a", status: "completed", mode: "auto", started_at: null, y: null, x: null },
        { run_id: "r-b", status: "completed", mode: "auto", started_at: null, y: null, x: null },
      ],
    });
    harness(["/runs/r-b?project_root=/tmp/p"]);
    const active = await screen.findByTestId("run-rail-row-r-b");
    const inactive = await screen.findByTestId("run-rail-row-r-a");
    expect(active).toHaveAttribute("aria-current", "true");
    expect(active).toHaveAttribute("data-active", "true");
    expect(inactive).not.toHaveAttribute("aria-current");
  });

  it("clicking a row navigates to /runs/<id>?project_root=…&tab=lineage", async () => {
    fetchRunsMock.mockResolvedValue({
      runs: [
        { run_id: "r-a", status: "completed", mode: "auto", started_at: null, y: null, x: null },
        { run_id: "r-b", status: "completed", mode: "auto", started_at: null, y: null, x: null },
      ],
    });
    const record: { url?: string } = {};
    harness(["/runs/r-a?project_root=/tmp/p"], record);
    const row = await screen.findByTestId("run-rail-row-r-b");
    fireEvent.click(row);
    await waitFor(() =>
      expect(record.url).toContain("/runs/r-b"),
    );
    expect(record.url).toContain("tab=lineage");
    expect(decodeURIComponent(record.url!)).toContain("project_root=/tmp/p");
  });

  it("preserves the current view when switching runs (stays on Table)", async () => {
    fetchRunsMock.mockResolvedValue({
      runs: [
        { run_id: "r-a", status: "completed", mode: "auto", started_at: null, y: null, x: null },
        { run_id: "r-b", status: "completed", mode: "auto", started_at: null, y: null, x: null },
      ],
    });
    const record: { url?: string } = {};
    harness(["/runs/r-a?project_root=/tmp/p&view=table"], record);
    fireEvent.click(await screen.findByTestId("run-rail-row-r-b"));
    await waitFor(() => expect(record.url).toContain("/runs/r-b"));
    expect(record.url).toContain("view=table");
  });

  it("renders 'No runs yet.' when the project has no runs", async () => {
    fetchRunsMock.mockResolvedValue({ runs: [] });
    harness(["/runs/r-x?project_root=/tmp/p"]);
    await waitFor(() => expect(screen.getByText("No runs yet.")).toBeInTheDocument());
  });
});
