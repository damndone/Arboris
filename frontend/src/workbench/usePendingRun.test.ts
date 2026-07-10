import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { usePendingRun } from "./usePendingRun";

vi.mock("../api", () => ({
  fetchRunDetail: vi.fn(),
}));
import { fetchRunDetail } from "../api";

const forestWith = (runIds: string[]) =>
  ({
    heads: runIds.map((runId) => ({ runId, createdAt: "" })),
  }) as never;

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("usePendingRun", () => {
  it("does not burn attempts while the run is still running", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "running",
    });
    const refetch = vi.fn();
    const onIndexed = vi.fn();
    const onFailed = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch,
        onIndexed,
        onFailed,
        setPending: vi.fn(),
      }),
    );
    for (let i = 0; i < 50; i++) await vi.advanceTimersByTimeAsync(1000);
    expect(onFailed).not.toHaveBeenCalled();
    expect(onIndexed).not.toHaveBeenCalled();
    expect(refetch).toHaveBeenCalled();
  });

  it("calls onFailed when the run reaches a terminal failure", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "failed",
    });
    const onFailed = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed,
        setPending: vi.fn(),
      }),
    );
    await vi.advanceTimersByTimeAsync(1000);
    expect(onFailed).toHaveBeenCalledWith("d1");
  });

  it("calls onFailed when the run reaches a terminal blocked state", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "blocked",
    });
    const onFailed = vi.fn();
    const setPending = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed,
        setPending,
      }),
    );
    await vi.advanceTimersByTimeAsync(1000);
    expect(onFailed).toHaveBeenCalledWith("d1");
    // Terminal failure clears the pending state.
    expect(setPending).toHaveBeenCalledWith(expect.any(Function));
    const clearer = setPending.mock.calls[setPending.mock.calls.length - 1][0] as (
      c: unknown,
    ) => unknown;
    expect(clearer({ runId: "r1", draftId: "d1", attempts: 0 })).toBeNull();
  });

  it("calls onIndexed once the run appears in the forest", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
    });
    const onIndexed = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith(["r1"]),
        refetch: vi.fn(),
        onIndexed,
        onFailed: vi.fn(),
        setPending: vi.fn(),
      }),
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(onIndexed).toHaveBeenCalledWith("r1");
  });

  it("burns an attempt on a completed (non-running, unindexed) poll", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
    });
    const setPending = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed: vi.fn(),
        setPending,
      }),
    );
    await vi.advanceTimersByTimeAsync(1000);
    const updater = setPending.mock.calls[setPending.mock.calls.length - 1][0] as (
      c: { runId: string; draftId: string; attempts: number } | null,
    ) => { attempts: number } | null;
    expect(updater({ runId: "r1", draftId: "d1", attempts: 0 })).toEqual({
      runId: "r1",
      draftId: "d1",
      attempts: 1,
    });
  });

  it("does NOT burn an attempt while still running", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "running",
    });
    const setPending = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 3 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed: vi.fn(),
        setPending,
      }),
    );
    await vi.advanceTimersByTimeAsync(1000);
    const updater = setPending.mock.calls[setPending.mock.calls.length - 1][0] as (
      c: { runId: string; draftId: string; attempts: number } | null,
    ) => { attempts: number } | null;
    expect(updater({ runId: "r1", draftId: "d1", attempts: 3 })).toEqual({
      runId: "r1",
      draftId: "d1",
      attempts: 3,
    });
  });

  it("burns an attempt on a transient fetch failure", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("network"),
    );
    const setPending = vi.fn();
    const onFailed = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed,
        setPending,
      }),
    );
    await vi.advanceTimersByTimeAsync(1000);
    expect(onFailed).not.toHaveBeenCalled();
    const updater = setPending.mock.calls[setPending.mock.calls.length - 1][0] as (
      c: { runId: string; draftId: string; attempts: number } | null,
    ) => { attempts: number } | null;
    expect(updater({ runId: "r1", draftId: "d1", attempts: 0 })).toEqual({
      runId: "r1",
      draftId: "d1",
      attempts: 1,
    });
  });

  it("gives up (clears pending, warns) once the retry budget is exhausted", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "completed",
    });
    const setPending = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 30 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed: vi.fn(),
        setPending,
      }),
    );
    // No timer needed — the budget check fires synchronously in the effect.
    expect(warn).toHaveBeenCalled();
    expect(setPending).toHaveBeenCalledWith(expect.any(Function));
    const clearer = setPending.mock.calls[setPending.mock.calls.length - 1][0] as (
      c: unknown,
    ) => unknown;
    expect(clearer({ runId: "r1", draftId: "d1", attempts: 30 })).toBeNull();
    warn.mockRestore();
  });

  it("does nothing when there is no pending run", async () => {
    const refetch = vi.fn();
    renderHook(() =>
      usePendingRun({
        pending: null,
        projectRoot: "/p",
        forest: forestWith([]),
        refetch,
        onIndexed: vi.fn(),
        onFailed: vi.fn(),
        setPending: vi.fn(),
      }),
    );
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchRunDetail).not.toHaveBeenCalled();
    expect(refetch).not.toHaveBeenCalled();
  });

  it("poll timer survives re-renders with fresh callback instances", async () => {
    // Regression pin: the container passes onIndexed/onFailed/refetch as fresh
    // inline arrows each render. If those sat in the effect deps, every
    // re-render would tear down and restart the 1000ms timer — renders faster
    // than 1s would starve the poll forever and strand the draft silently.
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "running",
    });
    const forest = forestWith([]);
    const pending = { runId: "r1", draftId: "d1", attempts: 0 };
    const makeProps = () => ({
      pending,
      projectRoot: "/p",
      forest,
      refetch: vi.fn(),
      onIndexed: vi.fn(),
      onFailed: vi.fn(),
      setPending: vi.fn(),
    });
    const { rerender } = renderHook(
      (props: ReturnType<typeof makeProps>) => usePendingRun(props),
      { initialProps: makeProps() },
    );
    // Re-render every 200ms with NEW callback instances for >2s total.
    for (let i = 0; i < 12; i++) {
      await vi.advanceTimersByTimeAsync(200);
      rerender(makeProps());
    }
    expect(fetchRunDetail).toHaveBeenCalled();
  });

  it("cancels the timer on unmount (no poll fires)", async () => {
    (fetchRunDetail as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "running",
    });
    const { unmount } = renderHook(() =>
      usePendingRun({
        pending: { runId: "r1", draftId: "d1", attempts: 0 },
        projectRoot: "/p",
        forest: forestWith([]),
        refetch: vi.fn(),
        onIndexed: vi.fn(),
        onFailed: vi.fn(),
        setPending: vi.fn(),
      }),
    );
    unmount();
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchRunDetail).not.toHaveBeenCalled();
  });
});
