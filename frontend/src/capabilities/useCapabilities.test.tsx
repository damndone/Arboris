import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCapabilities } from "./useCapabilities";
import sample from "../../../tests/contracts/capabilities.sample.json";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

describe("useCapabilities", () => {
  it("fetches /capabilities and returns the payload", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(sample));

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(fetchMock).toHaveBeenCalledWith("/api/capabilities");
    expect(result.current.data?.model_types.find((entry) => entry.key === "probit")).toBeDefined();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("exposes an error when /capabilities fails", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "nope" }, false, 500),
    );

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });
});
