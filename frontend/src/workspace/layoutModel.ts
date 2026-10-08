// v1.9.0 — the workspace grid: one set of regions, two layouts.
//
// Results first: map column | stage (wide) | Agent column.
// Lineage first: map (wide) | stage as an inspector | Agent column.
// The same components fill the same regions in both; only the map column's
// width changes, so switching never remounts anything (design spec §8.2).

import type { ViewMode } from "../workbench/state/urlSchema";

export type Layout = "results" | "lineage";

export interface ColumnSpec {
  map: number;
  inspector: number;
  agent: number;
  rail: number;
}

/** Column widths by window width (design spec §8.6; ≥1440 is the 14" MBP). */
export function columnSpec(windowWidth: number): ColumnSpec {
  if (windowWidth >= 1440) return { map: 280, inspector: 360, agent: 380, rail: 52 };
  return { map: 240, inspector: 320, agent: 340, rail: 52 };
}

export function agentWidth(spec: ColumnSpec, agentOpen: boolean): number {
  return agentOpen ? spec.agent : spec.rail;
}

/** Map column width for a layout, given the shell's measured width. */
export function mapWidthFor(layout: Layout, shellWidth: number, spec: ColumnSpec, agentOpen: boolean): number {
  if (layout === "results") return spec.map;
  return Math.max(spec.map, shellWidth - agentWidth(spec, agentOpen) - spec.inspector);
}

// Momentum projection (UIScrollView's normal deceleration, per millisecond):
// where a released drag would come to rest if it kept decelerating.
export const DECELERATION = 0.998;

export function projectedPosition(position: number, velocityPxPerMs: number): number {
  return position + (velocityPxPerMs * DECELERATION) / (1 - DECELERATION);
}

/** The layout whose detent is nearest to where the released divider would land. */
export function releaseLayout(
  mapWidth: number,
  velocityPxPerMs: number,
  detents: Record<Layout, number>,
): Layout {
  const landing = projectedPosition(mapWidth, velocityPxPerMs);
  return Math.abs(landing - detents.results) <= Math.abs(landing - detents.lineage) ? "results" : "lineage";
}

/** Data, Tables, Report and Plans need width: in lineage first they borrow the wide stage. */
export const WIDE_VIEWS: ReadonlySet<ViewMode> = new Set<ViewMode>(["data", "table", "report", "notebook"]);

export function effectiveLayout(chosen: Layout, view: ViewMode): Layout {
  return chosen === "lineage" && WIDE_VIEWS.has(view) ? "results" : chosen;
}

const LAYOUT_PREFIX = "workbench:layout:";
const AGENT_OPEN_KEY = "workbench:agent-open";

export function readLayout(projectRoot: string): Layout {
  try {
    return localStorage.getItem(LAYOUT_PREFIX + projectRoot) === "lineage" ? "lineage" : "results";
  } catch {
    return "results";
  }
}

export function writeLayout(projectRoot: string, layout: Layout): void {
  try {
    localStorage.setItem(LAYOUT_PREFIX + projectRoot, layout);
  } catch {
    // Storage may be unavailable; the layout still applies for this session.
  }
}

/** The Agent column starts open; a user who folds it keeps it folded. */
export function readAgentOpen(): boolean {
  try {
    return localStorage.getItem(AGENT_OPEN_KEY) !== "false";
  } catch {
    return true;
  }
}

export function writeAgentOpen(open: boolean): void {
  try {
    localStorage.setItem(AGENT_OPEN_KEY, open ? "true" : "false");
  } catch {
    // ignore
  }
}
