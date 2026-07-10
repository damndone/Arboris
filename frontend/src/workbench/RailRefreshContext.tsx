// frontend/src/workbench/RailRefreshContext.tsx
//
// v1.6.9 B1-4 — a one-way "refresh the RUNS rail now" signal.
//
// The RUNS rail (RunHistoryRail) owns its own useRunHistory instance and polls
// /runs every 30s. When a pending run (genesis / draft-execute) finally indexes
// into the forest, the rail would otherwise lag up to 30s before showing it.
// ForestWorkbench bumps this monotonic token in the pending-run onIndexed
// callbacks; the rail re-fetches immediately when the token changes.
//
// Deliberately a bare number rather than a subscribe/notify pair: the rail owns
// the refresh function (it is born inside useRunHistory), so a value flows DOWN
// far more simply than a callback flows UP. The default value (0) never changes
// in providerless paths (LegacyGraphWorkbench and any other route that mounts
// the rail without this provider), so the rail behaves exactly as today — the
// token-effect only ever fires after a real bump.

import { createContext, useContext } from "react";

export const RailRefreshContext = createContext<number>(0);

/** The current rail-refresh token. Changes → the rail should re-fetch now. */
export function useRailRefreshToken(): number {
  return useContext(RailRefreshContext);
}
