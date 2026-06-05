import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCapabilities } from "./useCapabilities";
import sample from "../../../tests/contracts/capabilities.sample.json";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(sample));

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/capabilities");
    expect(result.current.data?.model_types.find((entry) => entry.key === "probit")).toBeDefined();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("exposes an error when /capabilities fails", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ detail: "nope" }, false, 500),
    );

    const { result } = renderHook(() => useCapabilities());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });
});
