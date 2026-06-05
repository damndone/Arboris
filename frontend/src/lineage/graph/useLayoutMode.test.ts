/* useLayoutMode.test.ts — V1.5.1 T4' phase 2.
 *
 * Verifies the per-runId sessionStorage contract: default = "free",
 * setLayout persists, runId change re-reads, invalid values rejected.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useLayoutMode } from "./useLayoutMode";
import type { LayoutMode } from "./GraphCanvas";

const KEY = (id: string) => `workbench:layout:${id}`;

beforeEach(() => {
  window.sessionStorage.clear();
});

describe("useLayoutMode", () => {
  it("defaults to 'free' when no stored value exists", () => {
    const { result } = renderHook(() => useLayoutMode("run-abc"));
    expect(result.current.layout).toBe("free");
  });

  it("setLayout persists per-runId to sessionStorage", () => {
    const { result } = renderHook(() => useLayoutMode("run-abc"));
    act(() => result.current.setLayout("LR"));
    expect(result.current.layout).toBe("LR");
    expect(window.sessionStorage.getItem(KEY("run-abc"))).toBe("LR");
  });

  it("seeds from sessionStorage on mount", () => {
    window.sessionStorage.setItem(KEY("run-xyz"), "TB");
    const { result } = renderHook(() => useLayoutMode("run-xyz"));
    expect(result.current.layout).toBe("TB");
  });

  it("re-reads when runId changes (different run, different slot)", () => {
    window.sessionStorage.setItem(KEY("run-a"), "LR");
    window.sessionStorage.setItem(KEY("run-b"), "TB");
    const { result, rerender } = renderHook(({ id }) => useLayoutMode(id), {
      initialProps: { id: "run-a" },
    });
    expect(result.current.layout).toBe("LR");
    rerender({ id: "run-b" });
    expect(result.current.layout).toBe("TB");
  });

  it("ignores invalid stored values and falls back to 'free'", () => {
    window.sessionStorage.setItem(KEY("run-corrupt"), "diagonal");
    const { result } = renderHook(() => useLayoutMode("run-corrupt"));
    expect(result.current.layout).toBe("free");
  });

  it("ignores invalid setLayout calls without mutating state", () => {
    const { result } = renderHook(() => useLayoutMode("run-x"));
    act(() => result.current.setLayout("diagonal" as LayoutMode));
    expect(result.current.layout).toBe("free");
    expect(window.sessionStorage.getItem(KEY("run-x"))).toBeNull();
  });

  it("works with null runId (no persistence, just defaults)", () => {
    const { result } = renderHook(() => useLayoutMode(null));
    expect(result.current.layout).toBe("free");
    act(() => result.current.setLayout("LR"));
    // No persistence when no runId — state still updates in-memory.
    expect(result.current.layout).toBe("LR");
  });
});
