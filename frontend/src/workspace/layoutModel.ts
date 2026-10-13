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

export interface RegionState {
  /** The layout on screen (after the wide-view rule). */
  layout: Layout;
  /** Whether the stage shows: something is open and it is not folded away. */
  stageOpen: boolean;
  /** Whether the user folded the map column away (results first only). */
  mapHidden: boolean;
  agentOpen: boolean;
}

/** Map column width. With the stage closed the map takes everything the Agent leaves. */
export function mapWidthFor(state: RegionState, shellWidth: number, spec: ColumnSpec): number {
  const rest = shellWidth - agentWidth(spec, state.agentOpen);
  if (!state.stageOpen) return Math.max(spec.map, rest);
  if (state.layout === "lineage") return Math.max(spec.map, rest - spec.inspector);
  return state.mapHidden ? 0 : spec.map;
}

/** A narrow map is a navigator (tree of cards); a wide one is the full graph. */
export function mapPresentation(state: RegionState): "graph" | "tree" | "none" {
  if (!state.stageOpen || state.layout === "lineage") return "graph";
  return state.mapHidden ? "none" : "tree";
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

export type AgentMode = "bubble" | "floating" | "docked";
const AGENT_MODE_KEY = "workbench:agent-mode";
const AGENT_WIDTH_KEY = "workbench:agent-width";

/** The Agent reopens the way it was left: docked, floating, or folded to the bubble. */
export function readAgentMode(): AgentMode {
  try {
    const stored = localStorage.getItem(AGENT_MODE_KEY);
    if (stored === "bubble" || stored === "floating" || stored === "docked") return stored;
  } catch {
    // fall through to the older open/folded flag
  }
  return readAgentOpen() ? "docked" : "bubble";
}

export function writeAgentMode(mode: AgentMode): void {
  writeAgentOpen(mode !== "bubble");
  try {
    localStorage.setItem(AGENT_MODE_KEY, mode);
  } catch {
    // ignore
  }
}

export const DEFAULT_AGENT_WIDTH = 380;

export function readAgentWidth(): number {
  try {
    const stored = Number(localStorage.getItem(AGENT_WIDTH_KEY));
    return Number.isFinite(stored) && stored >= 240 && stored <= 960 ? stored : DEFAULT_AGENT_WIDTH;
  } catch {
    return DEFAULT_AGENT_WIDTH;
  }
}

export function writeAgentWidth(width: number): void {
  try {
    localStorage.setItem(AGENT_WIDTH_KEY, String(Math.round(width)));
  } catch {
    // ignore
  }
}

/**
 * Whether the stage takes width beside the map. Analyze and the document views
 * always have content; on Analysis the stage shows only while a step is open
 * and not folded away, so the map gets the whole width otherwise (user review
 * 1: the stage must not sit empty over the map).
 */
export function stageIsOpen(state: { analyzing: boolean; analysisView: boolean; hasOpenItem: boolean; folded: boolean }): boolean {
  if (state.analyzing || !state.analysisView) return true;
  return state.hasOpenItem && !state.folded;
}
