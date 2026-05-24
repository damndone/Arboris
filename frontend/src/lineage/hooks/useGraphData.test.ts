// frontend/src/lineage/hooks/useGraphData.test.ts
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useGraphData } from "./useGraphData";

// ────────────────────────────────────────────────────────────────────
// Fetch mock infra (same shape as src/runResult.invalidPreview.test.tsx)
// ────────────────────────────────────────────────────────────────────

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

// ────────────────────────────────────────────────────────────────────
// Fixture: a minimal v3 GraphResponse the adapter accepts
// ────────────────────────────────────────────────────────────────────

function v3Graph(overrides: Partial<{ schema_version: unknown }> = {}) {
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
    ...overrides,
  };
}

// ────────────────────────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────────────────────────

describe("useGraphData", () => {
  it("happy path: returns adapted GraphViewModel once fetch resolves", async () => {
    fetchMock.mockResolvedValue(jsonResponse(v3Graph()));
    const { result } = renderHook(() => useGraphData("/proj", "r1"));

    expect(result.current.loading).toBe(true);
    expect(result.current.model).toBeNull();
    expect(result.current.error).toBeNull();

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.model).not.toBeNull();
    expect(result.current.model?.runId).toBe("r1");
    expect(result.current.model?.schemaVersion).toBe(3);
    expect(result.current.model?.nodes).toHaveLength(1);
    expect(result.current.model?.nodes[0].stage).toBe("source");
  });

  it("404 → error kind: not_found", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Run not found" }, { status: 404 }),
    );
    const { result } = renderHook(() => useGraphData("/proj", "missing"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error?.kind).toBe("not_found");
    expect(result.current.model).toBeNull();
  });

  it("422 → error kind: corrupt", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Graph payload malformed" }, { status: 422 }),
    );
    const { result } = renderHook(() => useGraphData("/proj", "r2"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error?.kind).toBe("corrupt");
  });

  it("network rejection (fetch throws) → error kind: network", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useGraphData("/proj", "r3"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error?.kind).toBe("network");
    expect(result.current.error?.detail).toContain("Failed to fetch");
  });

  it("non-404/422 HTTP status → error kind: network (catch-all)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "boom" }, { status: 500 }),
    );
    const { result } = renderHook(() => useGraphData("/proj", "r4"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error?.kind).toBe("network");
  });

  it("unsupported schema_version → error kind: unsupported_schema with version", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(v3Graph({ schema_version: 99 })),
    );
    const { result } = renderHook(() => useGraphData("/proj", "r5"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toEqual({
      kind: "unsupported_schema",
      schemaVersion: 99,
    });
    expect(result.current.model).toBeNull();
  });

  it("refetch resets state and fires fetch again", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "down" }, { status: 503 }),
    );
    const { result } = renderHook(() => useGraphData("/proj", "r6"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error?.kind).toBe("network");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValueOnce(jsonResponse(v3Graph()));
    act(() => result.current.refetch());

    await waitFor(() => expect(result.current.model).not.toBeNull());
    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
