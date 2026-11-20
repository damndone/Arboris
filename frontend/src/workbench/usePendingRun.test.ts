import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
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
  it("preserves the default draft contract when an indexed run is still running", () => {
    const onIndexed = vi.fn();
    renderHook(() => usePendingRun({
      pending: {runId: "r1", draftId: "d1", attempts: 0}, projectRoot: "/p", forest: forestWith(["r1"]),
      refetch: vi.fn(), onIndexed, onFailed: vi.fn(), setPending: vi.fn(),
    }));
    expect(onIndexed).toHaveBeenCalledWith("r1");
    expect(fetchRunDetail).not.toHaveBeenCalled();
  });

  it.each(["failed", "blocked", "cancelled", "interrupted", "partial"])("manual observation never accepts an indexed %s child as success", async status => {
    const detail = {status, errors: {issues: [{code: "WORKFLOW_FAILED", message: "'hac'"}]}};
    vi.mocked(fetchRunDetail).mockResolvedValue(detail as never);
    const onIndexed = vi.fn(), onStatus = vi.fn(), setPending = vi.fn();
    renderHook(() => usePendingRun({
      pending: {runId: "r1", attempts: 0, confirmTerminal: true}, projectRoot: "/p", forest: forestWith(["r1"]),
      refetch: vi.fn(), onIndexed, onStatus, onFailed: vi.fn(), setPending,
    }));
    expect(onIndexed).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(onIndexed).not.toHaveBeenCalled();
    expect(onStatus).toHaveBeenCalledWith(detail);
    expect(setPending.mock.calls[setPending.mock.calls.length - 1][0]({runId: "r1"})).toBeNull();
  });

  it("manual observation waits for completed even when already indexed", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValueOnce({status: "running"} as never)
      .mockResolvedValue({status: "completed"} as never);
    const onIndexed = vi.fn(), onStatus = vi.fn();
    const forest = forestWith(["r1"]);
    renderHook(() => {
      const [pending, setPending] = useState<import("./usePendingRun").PendingRun | null>({runId: "r1", attempts: 0, confirmTerminal: true});
      usePendingRun({pending, projectRoot: "/p", forest, refetch: vi.fn(), onIndexed, onStatus, onFailed: vi.fn(), setPending});
    });
    expect(onIndexed).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(onStatus).toHaveBeenCalledWith({status: "running"});
    expect(onIndexed).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(onIndexed).toHaveBeenCalledOnce();
    expect(onIndexed).toHaveBeenCalledWith("r1");
  });

  it("leaves exhausted manual observation unconfirmed with its last error", () => {
    const onIndexed = vi.fn(), onUnconfirmed = vi.fn();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    renderHook(() => usePendingRun({
      pending: {runId: "r1", attempts: 30, confirmTerminal: true, lastError: "Network unavailable"},
      projectRoot: "/p", forest: forestWith(["r1"]), refetch: vi.fn(), onIndexed,
      onFailed: vi.fn(), onUnconfirmed, setPending: vi.fn(),
    }));
    expect(onIndexed).not.toHaveBeenCalled();
    expect(onUnconfirmed).toHaveBeenCalledWith(expect.stringContaining("Network unavailable"));
  });

  it("reports an unknown manual status as unconfirmed instead of success", async () => {
    vi.mocked(fetchRunDetail).mockResolvedValue({status: "unknown"} as never);
    const onIndexed = vi.fn(), onUnconfirmed = vi.fn();
    renderHook(() => usePendingRun({
      pending: {runId: "r1", attempts: 0, confirmTerminal: true}, projectRoot: "/p", forest: forestWith([]),
      refetch: vi.fn(), onIndexed, onFailed: vi.fn(), onUnconfirmed, setPending: vi.fn(),
    }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(onIndexed).not.toHaveBeenCalled();
    expect(onUnconfirmed).toHaveBeenCalledWith(expect.stringContaining("unknown"));
  });

  it("ignores a manual status response after observation is unmounted", async () => {
    let finish!: (detail: never) => void;
    vi.mocked(fetchRunDetail).mockImplementation(() => new Promise(resolve => {finish = resolve;}));
    const onIndexed = vi.fn(), onStatus = vi.fn(), setPending = vi.fn();
    const {unmount} = renderHook(() => usePendingRun({
      pending: {runId: "r1", attempts: 0, confirmTerminal: true}, projectRoot: "/p", forest: forestWith(["r1"]),
      refetch: vi.fn(), onIndexed, onStatus, onFailed: vi.fn(), setPending,
    }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchRunDetail).toHaveBeenCalledOnce();
    unmount();
    finish({status: "completed"} as never);
    await Promise.resolve();
    expect(onIndexed).not.toHaveBeenCalled();
    expect(onStatus).not.toHaveBeenCalled();
    expect(setPending).not.toHaveBeenCalled();
  });

  it("stops the previous manual observation when switching projects, without a late receipt", async () => {
    let finish!: (detail: never) => void;
    vi.mocked(fetchRunDetail).mockImplementation(() => new Promise(resolve => {finish = resolve;}));
    const onIndexed = vi.fn(), onStatus = vi.fn(), onUnconfirmed = vi.fn(), setPending = vi.fn();
    const props = {pending: {runId: "r1", attempts: 0, confirmTerminal: true} as import("./usePendingRun").PendingRun | null,
      projectRoot: "/p", forest: forestWith(["r1"]), refetch: vi.fn(), onIndexed, onStatus, onUnconfirmed, onFailed: vi.fn(), setPending};
    const {rerender} = renderHook(options => usePendingRun(options), {initialProps: props});
    await vi.advanceTimersByTimeAsync(1000);
    rerender({...props, projectRoot: "/other", pending: null});
    finish({status: "failed"} as never);
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchRunDetail).toHaveBeenCalledOnce();
    expect(onStatus).not.toHaveBeenCalled();
    expect(onIndexed).not.toHaveBeenCalled();
    expect(onUnconfirmed).not.toHaveBeenCalled();
    expect(setPending).not.toHaveBeenCalled();
  });

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
