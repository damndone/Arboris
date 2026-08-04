// frontend/src/workbench/state/tabsSchema.ts
//
// V1.5.2 P2 — pure parse / write / reduce for the `tabs` + `active`
// URL slice. Extracted from `lineage/hooks/useTabs.ts` so the provider
// can compose tab URL writes with the workbench slice into a SINGLE
// `setParams` call.
//
// Why this exists: React Router's `setParams` is not functional — two
// back-to-back calls in the same tick both build their next URL from
// the same captured `params`, so the second overwrites the first.
// useTabs + a separate URL writer therefore can't both write in the
// same dispatch without losing one update. Centralising the reducer
// here lets the provider apply tabs + view + focus + q in one write.
//
// V1.5.3: `useTabs` and `useSelectedNode` have been retired. TabState
// now lives here as the single source of truth. All tabs/active writes
// flow through WorkbenchStateProvider.commit().

export const REPORT_REVIEW_TAB_ID = "report:review" as const;

export interface NodeTabState {
  kind: "node";
  id: string;
  nodeKey: string;
  openedAt: number;
}

export interface ReportReviewTabState {
  kind: "report-review";
  id: typeof REPORT_REVIEW_TAB_ID;
  openedAt: number;
}

export type TabState = NodeTabState | ReportReviewTabState;

export function isNodeTab(tab: TabState): tab is NodeTabState {
  return tab.kind === "node";
}

export function isReportReviewTab(
  tab: TabState,
): tab is ReportReviewTabState {
  return tab.kind === "report-review";
}

export const MAX_TABS = 8;

export interface TabsSlice {
  tabs: TabState[];
  activeTabId: string | null;
}

export const emptyTabsSlice: TabsSlice = { tabs: [], activeTabId: null };

export function nodeTabOf(id: string, openedAt: number): NodeTabState {
  return { kind: "node", id, nodeKey: id, openedAt };
}

function reportReviewTabOf(openedAt: number): ReportReviewTabState {
  return { kind: "report-review", id: REPORT_REVIEW_TAB_ID, openedAt };
}

/**
 * Parse `?tabs=a,b&active=b` or legacy `?node=x`. Mirrors
 * useTabs.parseState exactly so both code paths agree on URL shape.
 */
export function parseTabsParams(params: URLSearchParams): TabsSlice {
  const rawTabs = params.get("tabs");
  const ids =
    rawTabs
      ?.split(",")
      .map((id) => id.trim())
      .filter(Boolean) ?? [];

  if (ids.length > 0) {
    let nodeCount = 0;
    const unique = Array.from(new Set(ids)).filter((id) => {
      if (id === REPORT_REVIEW_TAB_ID) return true;
      if (nodeCount >= MAX_TABS) return false;
      nodeCount += 1;
      return true;
    });
    const active = params.get("active");
    return {
      tabs: unique.map((id, index) =>
        id === REPORT_REVIEW_TAB_ID
          ? reportReviewTabOf(index + 1)
          : nodeTabOf(id, index + 1),
      ),
      activeTabId:
        active && unique.includes(active)
          ? active
          : (unique[unique.length - 1] ?? null),
    };
  }

  const legacyNode = params.get("node");
  if (legacyNode) {
    const tab =
      legacyNode === REPORT_REVIEW_TAB_ID
        ? reportReviewTabOf(1)
        : nodeTabOf(legacyNode, 1);
    return { tabs: [tab], activeTabId: legacyNode };
  }

  return emptyTabsSlice;
}

/**
 * Write the tabs slice into URLSearchParams (in place on a clone).
 * Always deletes legacy `?node=`; omits `tabs`/`active` entirely
 * when the slice is empty.
 */
export function writeTabsParams(
  params: URLSearchParams,
  slice: TabsSlice,
): URLSearchParams {
  const out = new URLSearchParams(params);
  out.delete("node");
  if (slice.tabs.length === 0 || slice.activeTabId === null) {
    out.delete("tabs");
    out.delete("active");
  } else {
    out.set("tabs", slice.tabs.map((t) => t.id).join(","));
    out.set("active", slice.activeTabId);
  }
  return out;
}

export interface ReduceResult {
  next: TabsSlice;
  /** Set when an existing tab was evicted to make room for a new one. */
  evicted: string | null;
  /** Updated clock (monotonic per-provider, used as next openedAt). */
  nextClock: number;
}

/** Add the permanent Report review tab without changing the active tab. */
export function ensureReportReviewTab(
  prev: TabsSlice,
  openedAt = maxOpenedAt(prev.tabs) + 1,
): TabsSlice {
  if (prev.tabs.some((tab) => tab.id === REPORT_REVIEW_TAB_ID)) return prev;
  return {
    ...prev,
    tabs: [...prev.tabs, reportReviewTabOf(openedAt)],
  };
}

/** Open or focus a tab. LRU evicts oldest when MAX_TABS exceeded.
 *  Returns the next slice without writing URL. */
export function reduceOpenTab(
  prev: TabsSlice,
  clock: number,
  nodeKey: string,
): ReduceResult {
  if (!nodeKey || nodeKey === REPORT_REVIEW_TAB_ID) {
    return { next: prev, evicted: null, nextClock: clock };
  }

  const existing = prev.tabs.find(
    (tab) =>
      isNodeTab(tab) && (tab.nodeKey === nodeKey || tab.id === nodeKey),
  );
  if (existing) {
    if (prev.activeTabId === existing.id) {
      return { next: prev, evicted: null, nextClock: clock };
    }
    return {
      next: { ...prev, activeTabId: existing.id },
      evicted: null,
      nextClock: clock,
    };
  }

  let tabs = prev.tabs;
  let evicted: string | null = null;
  const nodeTabs = tabs.filter(isNodeTab);
  if (nodeTabs.length >= MAX_TABS) {
    const oldest = [...nodeTabs].sort((a, b) => a.openedAt - b.openedAt)[0];
    evicted = oldest.id;
    tabs = tabs.filter((tab) => tab.id !== oldest.id);
  }

  const nextClock = clock + 1;
  return {
    next: {
      tabs: [...tabs, nodeTabOf(nodeKey, nextClock)],
      activeTabId: nodeKey,
    },
    evicted,
    nextClock,
  };
}

/** Close a tab. If it was active, promotes the next-best tab (the
 *  one that took its slot, else its left neighbour, else first). */
export function reduceCloseTab(prev: TabsSlice, id: string): TabsSlice {
  const index = prev.tabs.findIndex((t) => t.id === id);
  if (index === -1 || !isNodeTab(prev.tabs[index])) return prev;
  const tabs = prev.tabs.filter((t) => t.id !== id);
  let activeTabId = prev.activeTabId;
  if (prev.activeTabId === id) {
    activeTabId =
      tabs[index]?.id ?? tabs[index - 1]?.id ?? tabs[0]?.id ?? null;
  }
  return { tabs, activeTabId };
}

/** Switch active tab without changing the tab list. No-op if id is
 *  unknown or already active. */
export function reduceSetActive(prev: TabsSlice, id: string): TabsSlice {
  if (prev.activeTabId === id) return prev;
  if (!prev.tabs.some((t) => t.id === id)) return prev;
  return { ...prev, activeTabId: id };
}

export function maxOpenedAt(tabs: TabState[]): number {
  return Math.max(0, ...tabs.map((t) => t.openedAt));
}
