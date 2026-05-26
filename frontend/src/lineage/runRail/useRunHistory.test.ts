/* useRunHistory.test.ts — V1.5.1 T3'.
 *
 * Mocks the fetchRuns helper rather than fetch() so we exercise the
 * hook's loading/error/refresh contract independent of the network
 * adapter. Timer-based polling is exercised via vi.useFakeTimers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

const { fetchRunsMock } = vi.hoisted(() => ({ fetchRunsMock: vi.fn() }));
vi.mock("../../api", async () => {
  const mod = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...mod, fetchRuns: fetchRunsMock };
});

import { useRunHistory } from "./useRunHistory";

beforeEach(() => {
  fetchRunsMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useRunHistory", () => {
  it("fetches on mount and exposes runs once resolved", async () => {
    fetchRunsMock.mockResolvedValue({
      runs: [
        { run_id: "r-a", status: "completed", mode: "auto", started_at: null, y: null, x: null },
      ],
    });
    const { result } = renderHook(() => useRunHistory("/tmp/p"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.runs).toHaveLength(1);
    expect(result.current.runs[0]!.run_id).toBe("r-a");
    expect(result.current.error).toBeNull();
  });

  it("returns empty list when projectRoot is null", () => {
    const { result } = renderHook(() => useRunHistory(null));
    expect(result.current.runs).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(fetchRunsMock).not.toHaveBeenCalled();
  });

  it("polls every 30s while mounted", async () => {
    vi.useFakeTimers();
    fetchRunsMock.mockResolvedValue({ runs: [] });
    const { unmount } = renderHook(() => useRunHistory("/tmp/p"));
    // initial fetch
    expect(fetchRunsMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(fetchRunsMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(fetchRunsMock).toHaveBeenCalledTimes(3);
    unmount();
    vi.advanceTimersByTime(30_000);
    expect(fetchRunsMock).toHaveBeenCalledTimes(3); // no further fetches after unmount
  });

  it("preserves previous runs on fetch error (no blank rail)", async () => {
    fetchRunsMock.mockResolvedValueOnce({
      runs: [
        { run_id: "r-a", status: "completed", mode: "auto", started_at: null, y: null, x: null },
      ],
    });
    fetchRunsMock.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useRunHistory("/tmp/p"));
    await waitFor(() => expect(result.current.runs).toHaveLength(1));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    // Runs preserved even though the second fetch failed.
    expect(result.current.runs).toHaveLength(1);
  });

  it("refresh() triggers a manual re-fetch outside the timer", async () => {
    fetchRunsMock.mockResolvedValue({ runs: [] });
    const { result } = renderHook(() => useRunHistory("/tmp/p"));
    await waitFor(() => expect(fetchRunsMock).toHaveBeenCalledTimes(1));
    act(() => result.current.refresh());
    await waitFor(() => expect(fetchRunsMock).toHaveBeenCalledTimes(2));
  });
});
