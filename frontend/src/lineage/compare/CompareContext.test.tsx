import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { CompareProvider, useCompareOptional } from "./CompareContext";

function wrapper({ children }: { children: ReactNode }) {
  return <CompareProvider>{children}</CompareProvider>;
}

describe("CompareContext", () => {
  it("returns null outside the provider", () => {
    const { result } = renderHook(() => useCompareOptional());
    expect(result.current).toBeNull();
  });

  it("startPick → canvas click on another node completes the pair", () => {
    const { result } = renderHook(() => useCompareOptional(), { wrapper });
    act(() => result.current!.startPick("node-a"));
    expect(result.current!.pickingFromKey).toBe("node-a");

    let consumed = false;
    act(() => {
      consumed = result.current!.handleCanvasSelect("node-b");
    });
    expect(consumed).toBe(true);
    expect(result.current!.pair).toEqual({ anchorKey: "node-a", targetKey: "node-b" });
    expect(result.current!.pickingFromKey).toBeNull();
  });

  it("self-click while picking is consumed but keeps picking", () => {
    const { result } = renderHook(() => useCompareOptional(), { wrapper });
    act(() => result.current!.startPick("node-a"));
    let consumed = false;
    act(() => {
      consumed = result.current!.handleCanvasSelect("node-a");
    });
    expect(consumed).toBe(true);
    expect(result.current!.pickingFromKey).toBe("node-a");
    expect(result.current!.pair).toBeNull();
  });

  it("clicks are not consumed when no pick is pending", () => {
    const { result } = renderHook(() => useCompareOptional(), { wrapper });
    let consumed = true;
    act(() => {
      consumed = result.current!.handleCanvasSelect("node-b");
    });
    expect(consumed).toBe(false);
  });

  it("startPick clears a previous pair; cancel keeps it cleared; swap flips sides", () => {
    const { result } = renderHook(() => useCompareOptional(), { wrapper });
    act(() => result.current!.startPick("a"));
    act(() => void result.current!.handleCanvasSelect("b"));
    act(() => result.current!.swap());
    expect(result.current!.pair).toEqual({ anchorKey: "b", targetKey: "a" });

    act(() => result.current!.startPick("c"));
    expect(result.current!.pair).toBeNull();
    act(() => result.current!.cancelPick());
    expect(result.current!.pickingFromKey).toBeNull();

    act(() => result.current!.clear());
    expect(result.current!.pair).toBeNull();
  });
});
