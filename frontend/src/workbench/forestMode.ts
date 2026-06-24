// frontend/src/workbench/forestMode.ts
//
// v1.6.1 — persistent forest-view mode. Unlike the old `?forest=1` URL flag (which
// was dropped the moment you clicked a run or tab), this lives in sessionStorage so
// the forest stays on across navigation — it's a global UI preference, not per-URL.
// The URL `?forest=1` still works as a one-time bootstrap (deep-link / smoke).

const KEY = "workbench:forest-mode";

export function readForestMode(): boolean {
  try {
    const stored = sessionStorage.getItem(KEY);
    if (stored === "1") return true;
    if (stored === "0") return false;
    // First visit: bootstrap from the URL, then persist so it survives navigation.
    if (
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).get("forest") === "1"
    ) {
      sessionStorage.setItem(KEY, "1");
      return true;
    }
  } catch {
    /* sessionStorage unavailable — default off */
  }
  return false;
}

export function writeForestMode(on: boolean): void {
  try {
    sessionStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}
