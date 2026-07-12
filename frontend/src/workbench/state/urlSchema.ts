// frontend/src/workbench/state/urlSchema.ts
//
// V1.5.2 P2 — Tier 1 URL contract. Plan §6.
//
// Single source of truth for parsing / serialising every URL-backed
// workbench field. V1.5.3: tabs/active are now also owned by the
// provider (via tabsSchema), folded into the single commit() call.
//
// Schema:
//
//   view        ∈ {graph, table, pipeline}        default "graph"
//   q           string                            default ""        (omitted from URL when empty)
//   panel       ∈ {logs, ai} default "logs"
//   focus       string                            default null
//   pinned      ∈ {"0","1"}                       default "0"       (omitted from URL when 0)
//
// Unknown query parameters are preserved on every write — there are
// other consumers (`tab=lineage`, `project_root`) and the
// workbench is not authoritative over them.

import type { BottomPanelId } from "../registry/bottomPanelRegistry";

export type ViewMode = "graph" | "table" | "pipeline" | "report";

const VIEW_MODES: readonly ViewMode[] = ["graph", "table", "pipeline", "report"];
// v1.6.12: shell/pending/timeline placeholder panels removed; legacy URLs
// carrying them fall back to the "logs" default via pickEnum.
const PANEL_IDS: readonly BottomPanelId[] = ["logs", "ai"];

/** Parsed Tier 1 URL state. */
export interface WorkbenchUrlSlice {
  view: ViewMode;
  searchQuery: string;
  bottomPanel: BottomPanelId;
  focusKey: string | null;
  pinned: boolean;
}

export const defaultUrlSlice: WorkbenchUrlSlice = {
  view: "graph",
  searchQuery: "",
  bottomPanel: "logs",
  focusKey: null,
  pinned: false,
};

/**
 * Parse the workbench-owned URL params out of a URLSearchParams.
 * Anything malformed silently falls back to defaults (the URL is
 * user-mutable; we never throw on bad input).
 *
 * `validNodeKeys`, if provided, scrubs `focus` when it doesn't point
 * at a node in the current run. Per plan §7: "URL parse: focus not
 * in current run → null (silently dropped); pinned → 0."
 */
export function parseWorkbenchUrl(
  params: URLSearchParams,
  validNodeKeys?: ReadonlySet<string>,
): WorkbenchUrlSlice {
  const view = pickEnum(params.get("view"), VIEW_MODES, "graph");
  const searchQuery = params.get("q") ?? "";
  const panelId = pickEnum(params.get("panel"), PANEL_IDS, "logs");

  let focusKey: string | null = params.get("focus");
  if (focusKey === "") focusKey = null;
  let pinned = params.get("pinned") === "1";

  if (focusKey !== null && validNodeKeys && !validNodeKeys.has(focusKey)) {
    focusKey = null;
    pinned = false;
  }
  // Pinned without focus is meaningless — collapse to pinned=0 so we
  // never write `?pinned=1` without a `?focus=…` companion.
  if (focusKey === null) pinned = false;

  return {
    view,
    searchQuery,
    bottomPanel: panelId,
    focusKey,
    pinned,
  };
}

/**
 * Write a workbench slice back into a URLSearchParams without
 * touching unrelated params (`tabs`, `active`, `project_root`,
 * `tab=lineage`, etc). Empty/default values are *removed* rather
 * than serialised — keeps URLs short and shareable.
 */
export function writeWorkbenchUrl(
  params: URLSearchParams,
  slice: WorkbenchUrlSlice,
): URLSearchParams {
  const out = new URLSearchParams(params);

  // view: omit when default "graph"
  if (slice.view === "graph") out.delete("view");
  else out.set("view", slice.view);

  // q: omit when empty
  if (slice.searchQuery === "") out.delete("q");
  else out.set("q", slice.searchQuery);

  // panel: default logs omitted; legacy panelOpen is always stripped.
  if (slice.bottomPanel !== "logs") {
    out.set("panel", slice.bottomPanel);
  } else {
    out.delete("panel");
  }
  out.delete("panelOpen");

  // focus / pinned
  if (slice.focusKey === null) {
    out.delete("focus");
    out.delete("pinned");
  } else {
    out.set("focus", slice.focusKey);
    if (slice.pinned) out.set("pinned", "1");
    else out.delete("pinned");
  }

  return out;
}

function pickEnum<T extends string>(
  raw: string | null,
  allowed: readonly T[],
  fallback: T,
): T {
  if (raw && (allowed as readonly string[]).includes(raw)) return raw as T;
  return fallback;
}
