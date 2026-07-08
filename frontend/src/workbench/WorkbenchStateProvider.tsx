// frontend/src/workbench/WorkbenchStateProvider.tsx
//
// V1.5.2 P2 — cross-view workbench state. Plan §7, §18.
//
// Owns the §7 transition table. Every state change goes through a
// `dispatch.*` method; each method computes the next URL in ONE pass
// (tabs + view + focus + q + panel together) and writes it via a
// single `setParams` call. This is the only correct way to write
// multiple URL slices in the same tick — React Router's setParams
// isn't functional, so two back-to-back calls overwrite each other.
//
// State partition (mirrors plan §6):
//
//   Tier 1 (URL):
//     view, tabs, active, q, panel, focus, pinned
//   Tier 2 (sessionStorage):
//     hosted in dedicated useSessionByRunId hooks at the call site
//     (viewport, expandedGroups, splitter, layout). NOT in this
//     provider so concerns stay isolated.
//   Tier 3 (memory):
//     hoverKey, searchCursor, contextMenu
//
// `selectedKey` is *derived* from `activeTabId` — never stored as its
// own URL field. Plan §18.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  emptyTabsSlice,
  maxOpenedAt,
  parseTabsParams,
  reduceCloseTab,
  reduceOpenTab,
  reduceSetActive,
  writeTabsParams,
  type TabsSlice,
} from "./state/tabsSchema";
import {
  defaultUrlSlice,
  parseWorkbenchUrl,
  writeWorkbenchUrl,
  type ViewMode,
  type WorkbenchUrlSlice,
} from "./state/urlSchema";
import type { TabState } from "./state/tabsSchema";
import type { BottomPanelId } from "./registry/bottomPanelRegistry";

// ─── public types ───────────────────────────────────────────────────

export interface ContextMenuState {
  nodeKey: string;
  x: number;
  y: number;
}

export interface WorkbenchState {
  // Tier 1
  view: ViewMode;
  tabs: TabState[];
  activeTabId: string | null;
  /** Derived: same as the active tab's nodeKey. Read-only convenience. */
  selectedKey: string | null;
  focusKey: string | null;
  pinned: boolean;
  searchQuery: string;
  bottomPanel: BottomPanelId;
  /** Set when an openTab evicted an existing tab (LRU overflow). Cleared
   *  on the next non-overflow dispatch. */
  lastEvictedTabId: string | null;
  // Tier 3
  hoverKey: string | null;
  searchCursor: number | null;
  /** F5: nodeKey of the current ⌘K search cursor (the highlighted
   *  result row). The graph highlights it one tier above the other
   *  search hits. null when the palette is closed/empty. */
  searchCursorKey: string | null;
  contextMenu: ContextMenuState | null;
}

export interface WorkbenchDispatch {
  // §7 transition rows ───────────────────────────────────────────
  selectByCanvasClick(nodeKey: string): void;
  selectByTabSwitch(tabId: string): void;
  /** Forces `pinned=0`. */
  selectBySearchCommit(nodeKey: string, query: string): void;
  pinFocus(nodeKey: string): void;
  /** F1: sets focus WITHOUT touching tabs/active/selected; forces
   *  pinned=0. The "look at A, highlight B's upstream" case — distinct
   *  from selectByCanvasClick, which also opens/activates a tab. */
  setFocusOnly(nodeKey: string): void;
  /** Sends focus back to selected (or null when no tab is active). */
  unpinFocus(): void;
  closeTab(tabId: string): void;
  // View / panel / search ────────────────────────────────────────
  setView(view: ViewMode): void;
  setBottomPanel(panel: BottomPanelId): void;
  clearSearch(): void;
  // Tier 3 (memory) ──────────────────────────────────────────────
  setHover(nodeKey: string | null): void;
  setSearchCursor(index: number | null): void;
  /** F5: set the current search-cursor nodeKey (Tier 3, memory). */
  setSearchCursorKey(nodeKey: string | null): void;
  openContextMenu(menu: ContextMenuState): void;
  closeContextMenu(): void;
}

export interface WorkbenchContextValue {
  state: WorkbenchState;
  dispatch: WorkbenchDispatch;
}

// ─── context ────────────────────────────────────────────────────────

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

/** Throws if used outside the provider — V1.5.1's LineageContext
 *  follows the same fail-loud convention. */
export function useWorkbench(): WorkbenchContextValue {
  const ctx = useContext(WorkbenchContext);
  if (ctx === null) {
    throw new Error(
      "useWorkbench() must be called inside <WorkbenchStateProvider>. " +
        "Did you forget to wrap the tree in <WorkbenchRouteContainer>?",
    );
  }
  return ctx;
}

/**
 * Variant that returns null when no provider is mounted. Use this when
 * a consumer must work both inside the new WorkbenchRouteContainer
 * AND inside V1.5.0/1.5.1 test harnesses that mount components with
 * only LineageContext.Provider. Currently used by GraphView to wire
 * the right-click context menu — when mounted bare in legacy tests,
 * right-click is simply a no-op.
 */
export function useWorkbenchOptional(): WorkbenchContextValue | null {
  return useContext(WorkbenchContext);
}

// ─── provider ───────────────────────────────────────────────────────

export interface WorkbenchStateProviderProps {
  /** runId is used by Tier-2 storage scopes downstream. */
  runId: string;
  /** When supplied, an invalid `focus` URL param is silently dropped
   *  (plan §7 last row). Pass once GraphViewModel has resolved. */
  validNodeKeys?: ReadonlySet<string>;
  children: ReactNode;
}

export function WorkbenchStateProvider({
  runId: _runId,
  validNodeKeys,
  children,
}: WorkbenchStateProviderProps) {
  const [params, setParams] = useSearchParams();

  // Parse URL → typed slices on every render. Cheap; happens once per
  // URL change. Parsing is idempotent so React's StrictMode double-
  // render doesn't cause drift.
  const tabsSlice: TabsSlice = useMemo(
    () => parseTabsParams(params),
    [params],
  );
  const urlSlice: WorkbenchUrlSlice = useMemo(
    () => parseWorkbenchUrl(params, validNodeKeys),
    [params, validNodeKeys],
  );

  // Monotonic clock for tab openedAt. Survives across dispatches via
  // ref; seeded from the parsed slice on mount so reloads don't reset
  // tie-breakers to 0.
  const clockRef = useRef<number>(maxOpenedAt(tabsSlice.tabs));
  // Keep the clock at least as high as the latest URL tabs.
  if (clockRef.current < maxOpenedAt(tabsSlice.tabs)) {
    clockRef.current = maxOpenedAt(tabsSlice.tabs);
  }

  // Refs so dispatch closures always see the latest slices without
  // re-creating every callback on every render.
  const tabsRef = useRef(tabsSlice);
  tabsRef.current = tabsSlice;
  const urlRef = useRef(urlSlice);
  urlRef.current = urlSlice;
  const paramsRef = useRef(params);
  paramsRef.current = params;

  // Last evicted tab id (transient — cleared by the next non-overflow
  // openTab. Plan §11 wiring uses this for "Closed oldest tab to make
  // room" toasts in V1.5.3+).
  const [lastEvictedTabId, setLastEvictedTabId] = useState<string | null>(
    null,
  );

  // Tier 3 — memory only.
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [searchCursor, _setSearchCursor] = useState<number | null>(null);
  const [searchCursorKey, _setSearchCursorKey] = useState<string | null>(
    null,
  );
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(
    null,
  );

  // ── single-commit URL writer ──────────────────────────────────
  // Every dispatch builds a partial { tabs?, slice? } and commit
  // applies both in ONE setParams call, avoiding the two-setParams-
  // overwrite bug.
  const commit = useCallback(
    (partial: {
      tabs?: TabsSlice;
      slice?: WorkbenchUrlSlice;
      evicted?: string | null;
    }) => {
      const nextTabs = partial.tabs ?? tabsRef.current;
      const nextSlice = partial.slice ?? urlRef.current;
      let nextParams = paramsRef.current;
      if (partial.tabs) nextParams = writeTabsParams(nextParams, nextTabs);
      if (partial.slice) nextParams = writeWorkbenchUrl(nextParams, nextSlice);
      // Update refs synchronously so a follow-up dispatch in the same
      // tick sees the new state without waiting for re-render.
      tabsRef.current = nextTabs;
      urlRef.current = nextSlice;
      paramsRef.current = nextParams;
      if (partial.evicted !== undefined) setLastEvictedTabId(partial.evicted);
      setParams(nextParams, { replace: true });
    },
    [setParams],
  );

  useEffect(() => {
    if (!paramsRef.current.has("panelOpen")) return;
    commit({ slice: urlRef.current });
  }, [commit]);

  // Derived
  const activeTab =
    tabsSlice.tabs.find((t) => t.id === tabsSlice.activeTabId) ?? null;
  const selectedKey = activeTab?.nodeKey ?? null;

  // ── §7 transition implementations ────────────────────────────

  const selectByCanvasClick = useCallback(
    (nodeKey: string) => {
      const { next, evicted, nextClock } = reduceOpenTab(
        tabsRef.current,
        clockRef.current,
        nodeKey,
      );
      clockRef.current = nextClock;
      const slice = urlRef.current.pinned
        ? urlRef.current
        : { ...urlRef.current, focusKey: nodeKey };
      commit({ tabs: next, slice, evicted });
    },
    [commit],
  );

  const selectByTabSwitch = useCallback(
    (tabId: string) => {
      const next = reduceSetActive(tabsRef.current, tabId);
      if (next === tabsRef.current) return; // no-op
      const tab = next.tabs.find((t) => t.id === tabId);
      const slice =
        urlRef.current.pinned || !tab
          ? urlRef.current
          : { ...urlRef.current, focusKey: tab.nodeKey };
      commit({ tabs: next, slice });
    },
    [commit],
  );

  const selectBySearchCommit = useCallback(
    (nodeKey: string, query: string) => {
      const { next, evicted, nextClock } = reduceOpenTab(
        tabsRef.current,
        clockRef.current,
        nodeKey,
      );
      clockRef.current = nextClock;
      const slice: WorkbenchUrlSlice = {
        ...urlRef.current,
        focusKey: nodeKey,
        pinned: false,
        searchQuery: query,
      };
      commit({ tabs: next, slice, evicted });
    },
    [commit],
  );

  const pinFocus = useCallback(
    (nodeKey: string) => {
      const slice: WorkbenchUrlSlice = {
        ...urlRef.current,
        focusKey: nodeKey,
        pinned: true,
      };
      commit({ slice });
    },
    [commit],
  );

  const setFocusOnly = useCallback(
    (nodeKey: string) => {
      // Only focus + pinned change. tabs / active / selected are left
      // exactly as they were — this is the whole point versus
      // selectByCanvasClick.
      const slice: WorkbenchUrlSlice = {
        ...urlRef.current,
        focusKey: nodeKey,
        pinned: false,
      };
      commit({ slice });
    },
    [commit],
  );

  const unpinFocus = useCallback(() => {
    const activeId = tabsRef.current.activeTabId;
    const fallback =
      tabsRef.current.tabs.find((t) => t.id === activeId)?.nodeKey ?? null;
    const slice: WorkbenchUrlSlice = {
      ...urlRef.current,
      focusKey: fallback,
      pinned: false,
    };
    commit({ slice });
  }, [commit]);

  const closeTab = useCallback(
    (tabId: string) => {
      const prevTabs = tabsRef.current;
      const next = reduceCloseTab(prevTabs, tabId);
      if (next === prevTabs) return; // unknown id, no-op

      // Per §7: closing the focus tab — focus survives (pinned or not,
      // the anchor is the URL focus key, which we don't touch here).
      // Closing the selected tab promotes a new active; if !pinned,
      // focus should follow the new selected to maintain the
      // "selected==focus when !pinned" invariant.
      let slice = urlRef.current;
      const wasActive = prevTabs.activeTabId === tabId;
      if (wasActive && !slice.pinned) {
        const newActive = next.tabs.find((t) => t.id === next.activeTabId);
        slice = { ...slice, focusKey: newActive?.nodeKey ?? null };
      }
      commit({ tabs: next, slice });
    },
    [commit],
  );

  const setView = useCallback(
    (view: ViewMode) => {
      commit({ slice: { ...urlRef.current, view } });
    },
    [commit],
  );

  const setBottomPanel = useCallback(
    (panel: BottomPanelId) => {
      commit({ slice: { ...urlRef.current, bottomPanel: panel } });
    },
    [commit],
  );

  const clearSearch = useCallback(() => {
    commit({ slice: { ...urlRef.current, searchQuery: "" } });
    _setSearchCursor(null);
    _setSearchCursorKey(null);
  }, [commit]);

  const setHover = useCallback((nodeKey: string | null) => {
    setHoverKey(nodeKey);
  }, []);

  const setSearchCursor = useCallback((index: number | null) => {
    _setSearchCursor(index);
  }, []);

  const setSearchCursorKey = useCallback((nodeKey: string | null) => {
    _setSearchCursorKey(nodeKey);
  }, []);

  const openContextMenu = useCallback((menu: ContextMenuState) => {
    setContextMenu(menu);
  }, []);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const value = useMemo<WorkbenchContextValue>(
    () => ({
      state: {
        view: urlSlice.view,
        tabs: tabsSlice.tabs,
        activeTabId: tabsSlice.activeTabId,
        selectedKey,
        focusKey: urlSlice.focusKey,
        pinned: urlSlice.pinned,
        searchQuery: urlSlice.searchQuery,
        bottomPanel: urlSlice.bottomPanel,
        lastEvictedTabId,
        hoverKey,
        searchCursor,
        searchCursorKey,
        contextMenu,
      },
      dispatch: {
        selectByCanvasClick,
        selectByTabSwitch,
        selectBySearchCommit,
        pinFocus,
        setFocusOnly,
        unpinFocus,
        closeTab,
        setView,
        setBottomPanel,
        clearSearch,
        setHover,
        setSearchCursor,
        setSearchCursorKey,
        openContextMenu,
        closeContextMenu,
      },
    }),
    [
      urlSlice,
      tabsSlice,
      selectedKey,
      lastEvictedTabId,
      hoverKey,
      searchCursor,
      searchCursorKey,
      contextMenu,
      selectByCanvasClick,
      selectByTabSwitch,
      selectBySearchCommit,
      pinFocus,
      setFocusOnly,
      unpinFocus,
      closeTab,
      setView,
      setBottomPanel,
      clearSearch,
      setHover,
      setSearchCursor,
      setSearchCursorKey,
      openContextMenu,
      closeContextMenu,
    ],
  );

  return (
    <WorkbenchContext.Provider value={value}>
      {children}
    </WorkbenchContext.Provider>
  );
}

// Re-export for convenience; consumers usually only need the value.
export { defaultUrlSlice, emptyTabsSlice };
