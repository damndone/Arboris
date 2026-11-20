import "../lineage/tokens/lineage.css";
import "./panelHost.css";
import { type WorkbenchState } from "./WorkbenchStateProvider";
// Workbench route data, providers and shared node/report window state.
// The workspace owns the only layout; legacy run URLs enter the same shell.
// Draft execution, selection, overlays and pending-index recovery remain here.


export type PendingFocusTarget = {
  runId: string;
  focus: {
    forest_node_key: string | null;
    op_node_id: string;
    node_hash: string | null;
  };
  attempts: number;
};

export type LegacyFocusProbe = {
  key: string;
  loading: boolean;
  kind: "blocked" | "legacy" | "not_indexed";
};

export const PENDING_FOCUS_RETRY_LIMIT = 20;
export const PENDING_FOCUS_RETRY_DELAY_MS = 200;

type PanelLayout = "docked" | "floating";

export type PanelPosition = {
  x: number;
  y: number;
};

// Corners resize both ways; edges resize one way (user review 3: resizing
// only from four invisible corners was not discoverable).
export type ResizeCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right" | "top" | "right" | "bottom" | "left";
export const RESIZE_HANDLES: ResizeCorner[] = ["top", "right", "bottom", "left", "top-left", "top-right", "bottom-left", "bottom-right"];

export type NodePanelResizeState = {
  corner: ResizeCorner;
  startX: number;
  startY: number;
  startWidth: number;
  startHeight: number;
  startLeft: number;
  startTop: number;
  pointerId: number;
};

type PanelUiState = {
  layout: PanelLayout;
  pinned: boolean;
  collapsed: boolean;
  position: PanelPosition;
  /** The tab detached into the floating node window, when applicable. */
  floatingTabId: string | null;
};

export type ReportReviewUiState = PanelUiState;
export type NodePanelUiState = PanelUiState;

export const REPORT_REVIEW_FLOATING_WIDTH = 680;
export const NODE_PANEL_FLOATING_WIDTH = 680;
const REPORT_REVIEW_STORAGE_PREFIX = "workbench:report-review:";
const NODE_PANEL_STORAGE_PREFIX = "workbench:node-panel:";
const DEFAULT_REPORT_REVIEW_UI_STATE: ReportReviewUiState = {
  layout: "docked",
  pinned: false,
  collapsed: false,
  position: { x: 36, y: 116 },
  floatingTabId: null,
};
const DEFAULT_NODE_PANEL_UI_STATE: NodePanelUiState = {
  layout: "docked",
  pinned: false,
  collapsed: false,
  position: { x: 36, y: 116 },
  floatingTabId: null,
};

function reportReviewStorageKey(projectRoot: string): string {
  return `${REPORT_REVIEW_STORAGE_PREFIX}${projectRoot}`;
}

function nodePanelStorageKey(projectRoot: string): string {
  return `${NODE_PANEL_STORAGE_PREFIX}${projectRoot}`;
}

function readPanelUiState(storageKey: string, fallback: PanelUiState): PanelUiState {
  if (typeof sessionStorage === "undefined") return fallback;
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<PanelUiState>;
    const position = parsed.position;
    return {
      layout: parsed.layout === "floating" ? "floating" : "docked",
      pinned: parsed.pinned === true,
      collapsed: parsed.collapsed === true,
      floatingTabId: typeof parsed.floatingTabId === "string" ? parsed.floatingTabId : fallback.floatingTabId,
      position: {
        x: typeof position?.x === "number" && Number.isFinite(position.x)
          ? Math.max(8, position.x)
          : fallback.position.x,
        y: typeof position?.y === "number" && Number.isFinite(position.y)
          ? Math.max(56, position.y)
          : fallback.position.y,
      },
    };
  } catch {
    return fallback;
  }
}

export function findDockedFallbackTabId(
  tabs: WorkbenchState["tabs"],
  activeTabId: string | null,
  floatingTabId: string | null,
): string | null {
  const dockedTabs = tabs.filter((tab) => tab.id !== floatingTabId);
  if (dockedTabs.length === 0) return null;
  if (activeTabId !== floatingTabId && dockedTabs.some((tab) => tab.id === activeTabId)) {
    return activeTabId;
  }

  const activeIndex = tabs.findIndex((tab) => tab.id === activeTabId);
  if (activeIndex >= 0) {
    const next = tabs.slice(activeIndex + 1).find((tab) => tab.id !== floatingTabId);
    if (next) return next.id;
    const previous = tabs.slice(0, activeIndex).reverse().find((tab) => tab.id !== floatingTabId);
    if (previous) return previous.id;
  }
  return dockedTabs[0].id;
}

export function readReportReviewUiState(projectRoot: string): ReportReviewUiState {
  return readPanelUiState(reportReviewStorageKey(projectRoot), DEFAULT_REPORT_REVIEW_UI_STATE);
}

export function readNodePanelUiState(projectRoot: string): NodePanelUiState {
  return readPanelUiState(nodePanelStorageKey(projectRoot), DEFAULT_NODE_PANEL_UI_STATE);
}

function persistPanelUiState(storageKey: string, state: PanelUiState): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
    // A private browsing context can reject sessionStorage; the UI remains usable.
  }
}

export function persistReportReviewUiState(projectRoot: string, state: ReportReviewUiState): void {
  persistPanelUiState(reportReviewStorageKey(projectRoot), state);
}

export function persistNodePanelUiState(projectRoot: string, state: NodePanelUiState): void {
  persistPanelUiState(nodePanelStorageKey(projectRoot), state);
}

// A draft-execute focus that never recorded a produced op node id degrades to
// "no target": the pending-focus effect then simply finds nothing and gives up
// after its budget instead of crashing — the run still activated + indexed.
export const EMPTY_FOCUS: PendingFocusTarget["focus"] = {
  forest_node_key: null,
  op_node_id: "",
  node_hash: null,
};

export interface WorkbenchHomeProps {
  projectRoot: string;
  /** Optional run deep link (?run=). Absent → newest head is the active run;
   *  a zero-run project renders the empty canvas + genesis CTA instead. */
  focusRunId?: string;
  /** One-shot upload handoff from launcher and compatibility routes. */
  openGenesis?: boolean;
  /** Monotonic request from the outer project navigation. */
  settingsRequestVersion?: number;
}

export type AppShellStatusContext = {
  setError?: (message: string | null) => void;
};

