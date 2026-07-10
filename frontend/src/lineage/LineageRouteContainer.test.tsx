// frontend/src/lineage/LineageRouteContainer.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LineageRouteContainer } from "./LineageRouteContainer";

// ────────────────────────────────────────────────────────────────────
// Fetch mock infra (same shape as useGraphData.test.ts)
// ────────────────────────────────────────────────────────────────────

type FetchInit = { status?: number };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
const originalFetch = globalThis.fetch;

beforeEach(() => {
  fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  // Restore only fetch — vi.unstubAllGlobals() would also wipe the
  // ResizeObserver stub installed once in vitest.setup.ts (needed by React Flow).
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

function v3Graph() {
  return {
    schema_version: 3,
    run_id: "r1",
    legacy: false,
    stats: { node_count: 1, edge_count: 0, leaf_count: 0, has_dp_count: 0 },
    nodes: {
      n1: {
        id: "n1",
        kind: "dataset_stage",
        display_label: "Raw",
        summary: null,
        created_at: "2026-05-22T00:00:00Z",
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

function renderContainer(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LineageRouteContainer projectRoot="/proj" runId="r1" />
    </MemoryRouter>,
  );
}

// ────────────────────────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────────────────────────

describe("LineageRouteContainer", () => {
  it("loading branch: shows 'Loading lineage…' before fetch resolves", () => {
    fetchMock.mockImplementation(() => new Promise(() => {})); // never resolves
    renderContainer();
    expect(screen.getByText(/loading lineage/i)).toBeTruthy();
  });

  it("error branch (404 not_found): shows title, no retry button", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "missing" }, { status: 404 }),
    );
    renderContainer();
    await waitFor(() =>
      expect(screen.getByText(/run not found/i)).toBeTruthy(),
    );
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("error branch (422 corrupt): shows 'Lineage data is corrupt' with Try again button", async () => {
    // Subsumes V1.4.1 LineageTab.test.tsx "shows 422 error state with Try again
    // button" — confirms the corrupt error kind renders its specific copy and
    // retry affordance (not just classification, which useGraphData covers).
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "graph payload malformed" }, { status: 422 }),
    );
    renderContainer();
    await waitFor(() =>
      expect(screen.getByText(/lineage data is corrupt/i)).toBeTruthy(),
    );
    const retry = screen.getByRole("button", { name: /try again/i });
    expect(retry).toBeTruthy();

    // Retry: the graph view first tries the cross-run head-set (which, lacking `heads`,
    // is treated as legacy) then the per-run graph — both served the same v3 payload.
    fetchMock.mockResolvedValue(jsonResponse(v3Graph()));
    fireEvent.click(retry);
    await waitFor(() =>
      expect(screen.getByTestId("graph-workbench")).toBeTruthy(),
    );
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("error branch (network): shows title with Try again button that refetches", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "down" }, { status: 503 }),
    );
    renderContainer();
    await waitFor(() =>
      expect(screen.getByText(/could not load lineage/i)).toBeTruthy(),
    );
    const retry = screen.getByRole("button", { name: /try again/i });
    expect(retry).toBeTruthy();

    fetchMock.mockResolvedValue(jsonResponse(v3Graph()));
    fireEvent.click(retry);
    await waitFor(() =>
      expect(screen.getByTestId("graph-workbench")).toBeTruthy(),
    );
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("error branch (unsupported_schema): mentions the offending version", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ ...v3Graph(), schema_version: 99 }),
    );
    renderContainer();
    await waitFor(() =>
      expect(screen.getByText(/unsupported graph schema/i)).toBeTruthy(),
    );
    expect(screen.getByText(/schema_version=99/)).toBeTruthy();
  });

  it("success branch: mounts WorkbenchSlot inside provider", async () => {
    fetchMock.mockResolvedValue(jsonResponse(v3Graph()));
    renderContainer();
    await waitFor(() =>
      expect(screen.getByTestId("graph-workbench")).toBeTruthy(),
    );
    expect(screen.queryByText(/loading lineage/i)).toBeNull();
  });
});
