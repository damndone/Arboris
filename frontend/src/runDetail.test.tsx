// frontend/src/runDetail.test.tsx
//
// Integration smoke for the T5.7 swap: confirms that the lineage tab on
// /runs/:runId now mounts LineageRouteContainer (which exposes
// data-testid="graph-workbench" via the V1.5.0 GraphWorkbench).
//
// Wraps RunDetailRoute in a MemoryRouter with a stub Outlet context so we
// don't need the full App bootstrap. The App-level routing is verified
// implicitly by App.tsx's <Route path="runs/:runId" element={<RunDetailRoute />} />
// and by every other App.test scenario continuing to pass.

import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { RunDetailRoute } from "./runDetail";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  fetchMock.mockReset();
});

function v3GraphResponse() {
  return {
    schema_version: 3,
    run_id: "run-1",
    legacy: false,
    stats: { node_count: 1, edge_count: 0, leaf_count: 1, has_dp_count: 0 },
    nodes: {
      "stage:raw": {
        id: "stage:raw",
        kind: "dataset_stage",
        display_label: "Raw",
        summary: "Raw: 10 rows × 2 cols",
        created_at: "2026-05-19T00:00:00Z",
        parent_stage_id: null,
        branch_id: "main",
        trust: "ok",
        trust_reason: null,
        archived: false,
        payload_ref: null,
        decision_points: [],
        annotations: [],
        stage: "source",
      },
    },
    edges: {},
    branches: {},
  };
}

function ParentLayout() {
  // Mirrors App.tsx's Outlet context shape (projectRoot + setError).
  return <Outlet context={{ projectRoot: "/tmp/demo", setError: () => {} }} />;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<ParentLayout />}>
          <Route path="runs/:runId" element={<RunDetailRoute />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("RunDetailRoute — T5.7 swap smoke", () => {
  it("?tab=lineage mounts LineageRouteContainer (data-testid graph-workbench)", async () => {
    // First fetch: run detail (consumed by RunResultView — but it's hidden
    // when tab=lineage, so this fetch never actually fires). Mock it
    // anyway in case the implementation re-orders.
    // Lineage graph fetch:
    fetchMock.mockResolvedValue(jsonResponse(v3GraphResponse()));

    renderAt("/runs/run-1?tab=lineage");

    await waitFor(() =>
      expect(screen.getByTestId("graph-workbench")).toBeInTheDocument(),
    );
    // Regression: V1.4.1 LineageTab had no such testid, so its presence
    // proves the T5.7 route swap shipped.
  });

  it("?tab=overview keeps RunResultView (no graph-workbench)", async () => {
    // Sanity check that the swap only affects the lineage tab — the
    // overview path is untouched.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        run_id: "run-1",
        status: "completed",
        mode: "auto",
        started_at: "2026-05-01T00:00:00+00:00",
        y: "y",
        x: ["x"],
        lineage: [],
        artifact_counts: { report: 1 },
        errors: { issues: [] },
      }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ groups: [] }));

    renderAt("/runs/run-1?tab=overview");

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /run detail/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("graph-workbench")).toBeNull();
  });
});
