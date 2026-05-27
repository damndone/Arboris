// frontend/src/workbench/state/useSessionByRunId.ts
//
// V1.5.2 P2 — Tier 2 storage hook. Plan §6.
//
// "How this page is configured" — survives refresh within the same
// browser session, but does not pollute shared URLs and resets when
// the tab closes. Scoped by `runId` so two open runs in the same
// session don't trample each other's viewport, expanded groups, or
// panel splitter height.
//
// Storage key shape: `workbench:<key>:<runId>`. The `workbench:`
// prefix keeps these from colliding with V1.5.0-era sessionStorage
// keys (e.g. `lineage:legacy-hint-dismissed:<runId>` from
// GraphWorkbench) — those keep working unchanged; new keys live in
// the new namespace.

import { useCallback, useEffect, useState } from "react";

/**
 * Per-run sessionStorage hook.
 *
 * - `initial` is used both for the initial state when storage is
 *   empty AND as the type seed; pass a stable reference (or a value
 *   produced from a lazy factory below) to avoid stale-closure bugs.
 * - On the first render the hook attempts to read `workbench:<key>:<runId>`;
 *   on each `set()` it writes the new value back synchronously.
 * - Storage failures (privacy mode, quota) downgrade silently to
 *   in-memory state — same fallback strategy GraphWorkbench's
 *   legacy-hint dismissal uses today.
 *
 * The hook deliberately does NOT cross-tab sync: V1.5.2 has no
 * multi-window-same-run story. If two tabs open the same run, each
 * keeps its own sessionStorage scope.
 */
export function useSessionByRunId<T>(
  runId: string,
  key: string,
  initial: T,
): [T, (next: T) => void] {
  const storageKey = `workbench:${key}:${runId}`;

  const [value, setValue] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw === null) return initial;
      return JSON.parse(raw) as T;
    } catch {
      return initial;
    }
  });

  // Re-seed when runId/key changes (e.g. user navigates between runs
  // while the provider stays mounted — uncommon but possible).
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw === null) {
        setValue(initial);
        return;
      }
      setValue(JSON.parse(raw) as T);
    } catch {
      setValue(initial);
    }
    // initial is intentionally excluded — callers should pass a stable
    // reference (or rely on the eslint suppression they'd add anyway).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* fall back to in-memory only */
      }
    },
    [storageKey],
  );

  return [value, set];
}
