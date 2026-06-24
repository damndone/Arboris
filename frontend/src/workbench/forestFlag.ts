// frontend/src/workbench/forestFlag.ts
//
// v1.6.1 (2C.6) — frontend gate for the cross-run forest view. Ship-dark:
// OFF by default, so the legacy per-run GraphCanvas path is byte-identical
// unless explicitly opted in with `?forest=1`. A URL param (not a new toolbar
// control) keeps the integration scoped — no invented UI, easy to smoke-test.

export function forestViewEnabled(
  search: string = typeof window !== "undefined" ? window.location.search : "",
): boolean {
  try {
    return new URLSearchParams(search).get("forest") === "1";
  } catch {
    return false;
  }
}
