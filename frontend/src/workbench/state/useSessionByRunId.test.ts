// frontend/src/workbench/state/useSessionByRunId.test.ts
//
// V1.5.2 P2 — Tier 2 storage hook tests.

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useSessionByRunId } from "./useSessionByRunId";

describe("useSessionByRunId", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("returns initial value when storage is empty", () => {
    const { result } = renderHook(() =>
      useSessionByRunId("r1", "splitter", 240),
    );
    expect(result.current[0]).toBe(240);
  });

  it("persists to sessionStorage with workbench:<key>:<runId> shape", () => {
    const { result } = renderHook(() =>
      useSessionByRunId("r1", "splitter", 240),
    );
    act(() => result.current[1](320));
    expect(result.current[0]).toBe(320);
    expect(sessionStorage.getItem("workbench:splitter:r1")).toBe("320");
  });

  it("hydrates from existing sessionStorage on mount", () => {
    sessionStorage.setItem("workbench:splitter:r1", "180");
    const { result } = renderHook(() =>
      useSessionByRunId("r1", "splitter", 240),
    );
    expect(result.current[0]).toBe(180);
  });

  it("isolates runIds — different runs don't see each other", () => {
    sessionStorage.setItem("workbench:splitter:r1", "100");
    sessionStorage.setItem("workbench:splitter:r2", "200");
    const { result: r1 } = renderHook(() =>
      useSessionByRunId("r1", "splitter", 240),
    );
    const { result: r2 } = renderHook(() =>
      useSessionByRunId("r2", "splitter", 240),
    );
    expect(r1.current[0]).toBe(100);
    expect(r2.current[0]).toBe(200);
  });

  it("handles arbitrary JSON-serialisable shapes", () => {
    const { result } = renderHook(() =>
      useSessionByRunId<{ x: number; tags: string[] }>(
        "r1",
        "viewport",
        { x: 0, tags: [] },
      ),
    );
    act(() => result.current[1]({ x: 42, tags: ["a", "b"] }));
    expect(JSON.parse(sessionStorage.getItem("workbench:viewport:r1")!)).toEqual({
      x: 42,
      tags: ["a", "b"],
    });
  });
});
