// frontend/src/lineage/hooks/useForestData.test.ts
//
// v1.6.8 T11 — project-keyed forest hook: fetches GET /graph?project_root=
// (NOT the per-run headset endpoint) and adapts the body; a zero-run project
// yields an empty (non-legacy) ForestViewModel without crashing.
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useForestData } from "./useForestData";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
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

function emptyForestBody() {
  return {
    nodes: {},
    edges: [],
    heads: [],
    families: [],
    schema_version: 2,
    legacy: false,
  };
}

describe("useForestData (project-keyed, T11)", () => {
  it("fetches the project forest endpoint with project_root", async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyForestBody()));
    const { result } = renderHook(() => useForestData("/tmp/示例"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/graph?project_root=");
    expect(url).toContain(encodeURIComponent("/tmp/示例"));
    // NOT the per-run headset endpoint.
    expect(url).not.toContain("/runs/");
  });

  it("zero-run body adapts to an empty non-legacy forest (no crash)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyForestBody()));
    const { result } = renderHook(() => useForestData("/tmp/p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.forest).toEqual({
      schemaVersion: 2,
      legacy: false,
      nodes: [],
      edges: [],
      heads: [],
      familyCount: 0,
      familyRunCount: 0,
    });
  });

  it("keeps the previous forest mounted during a background refetch", async () => {
    let resolveSecond!: (response: Response) => void;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(emptyForestBody()))
      .mockImplementationOnce(
        () => new Promise<Response>((resolve) => { resolveSecond = resolve; }),
      );

    const { result } = renderHook(() => useForestData("/tmp/p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const previousForest = result.current.forest;

    act(() => result.current.refetch());

    expect(result.current.loading).toBe(false);
    expect(result.current.forest).toBe(previousForest);

    resolveSecond(jsonResponse(emptyForestBody()));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("preserves familyCount so all-legacy projects are not mistaken for zero-run projects", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        ...emptyForestBody(),
        families: [
          { family_root: "legacy_run", members: ["legacy_run", "legacy_child"] },
        ],
      }),
    );
    const { result } = renderHook(() => useForestData("/tmp/legacy-only"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.forest?.heads).toEqual([]);
    expect(result.current.forest?.familyCount).toBe(1);
    expect(result.current.forest?.familyRunCount).toBe(2);
  });

  it("classifies a 404 as not_found (PROJECT_NOT_FOUND path)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: "PROJECT_NOT_FOUND", message: "missing", details: {} } },
        { status: 404 },
      ),
    );
    const { result } = renderHook(() => useForestData("/gone"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error?.kind).toBe("not_found");
    expect(result.current.forest).toBeNull();
  });

  it("classifies a non-fetch TypeError (adapter bug) as adapter_error, not network (REV-3)", async () => {
    // An exception thrown inside adaptHeadSet on malformed data reaches the
    // same .catch as fetch rejections — it must NOT masquerade as network.
    fetchMock.mockRejectedValue(
      new TypeError("Cannot read properties of undefined (reading 'map')"),
    );
    const { result } = renderHook(() => useForestData("/tmp/adapter-bug"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error?.kind).toBe("adapter_error");
    expect(result.current.forest).toBeNull();
  });

  it("keeps a genuine fetch rejection classified as network", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useForestData("/tmp/offline"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error?.kind).toBe("network");
  });
});
