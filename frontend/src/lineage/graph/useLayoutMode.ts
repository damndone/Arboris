/* useLayoutMode.ts — V1.5.1 T4' phase 2.
 *
 * Persists the user's chosen graph layout per-run in sessionStorage.
 * Per-run (not global) because a panel-data run and a time-series run
 * usually want different visual flows; tying the choice to the run id
 * stops one click from leaking onto an unrelated run when the user
 * navigates the rail.
 *
 * Storage key: workbench:layout:<runId>
 * Default: "free" (per user 2026-05-25 requirement).
 * Fallback: gracefully degrades to in-memory state if sessionStorage
 * throws (quota, privacy mode, SSR).
 */
import { useCallback, useEffect, useState } from "react";
import { DEFAULT_LAYOUT, type LayoutMode } from "./GraphCanvas";

const PREFIX = "workbench:layout:";
const VALID: ReadonlyArray<LayoutMode> = ["free", "LR", "TB"];

function read(runId: string): LayoutMode {
  if (typeof window === "undefined") return DEFAULT_LAYOUT;
  try {
    const v = window.sessionStorage.getItem(PREFIX + runId);
    return VALID.includes(v as LayoutMode) ? (v as LayoutMode) : DEFAULT_LAYOUT;
  } catch {
    return DEFAULT_LAYOUT;
  }
}

function write(runId: string, mode: LayoutMode): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PREFIX + runId, mode);
  } catch {
    /* sessionStorage failure is non-fatal; in-memory state still works. */
  }
}

export interface UseLayoutModeResult {
  layout: LayoutMode;
  setLayout: (mode: LayoutMode) => void;
}

export function useLayoutMode(runId: string | null | undefined): UseLayoutModeResult {
  // Key on runId so navigating to a different run reads the right slot.
  const [layout, setLayoutState] = useState<LayoutMode>(() =>
    runId ? read(runId) : DEFAULT_LAYOUT,
  );

  // Re-read when the runId changes (e.g., user clicks RunHistoryRail).
  useEffect(() => {
    if (!runId) return;
    setLayoutState(read(runId));
  }, [runId]);

  const setLayout = useCallback(
    (mode: LayoutMode) => {
      if (!VALID.includes(mode)) return;
      setLayoutState(mode);
      if (runId) write(runId, mode);
    },
    [runId],
  );

  return { layout, setLayout };
}
