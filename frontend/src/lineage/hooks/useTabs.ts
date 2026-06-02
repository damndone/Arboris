import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

const MAX_TABS = 8;

import type { TabState } from "../../workbench/state/tabsSchema";

interface TabsState {
  tabs: TabState[];
  activeTabId: string | null;
}

export interface UseTabsResult extends TabsState {
  activeNodeKey: string | null;
  lastEvictedTabId: string | null;
  openTab: (nodeKey: string) => void;
  closeTab: (id: string) => void;
  setActive: (id: string) => void;
}

function tabOf(id: string, openedAt: number): TabState {
  return { id, nodeKey: id, openedAt };
}

function parseState(params: URLSearchParams): TabsState {
  const rawTabs = params.get("tabs");
  const ids =
    rawTabs
      ?.split(",")
      .map((id) => id.trim())
      .filter(Boolean) ?? [];

  if (ids.length > 0) {
    const unique = Array.from(new Set(ids)).slice(0, MAX_TABS);
    const active = params.get("active");
    return {
      tabs: unique.map((id, index) => tabOf(id, index + 1)),
      activeTabId:
        active && unique.includes(active)
          ? active
          : (unique[unique.length - 1] ?? null),
    };
  }

  const legacyNode = params.get("node");
  if (legacyNode) {
    return { tabs: [tabOf(legacyNode, 1)], activeTabId: legacyNode };
  }

  return { tabs: [], activeTabId: null };
}

function maxOpenedAt(tabs: TabState[]): number {
  return Math.max(0, ...tabs.map((tab) => tab.openedAt));
}

export function useTabs(): UseTabsResult {
  const [params, setParams] = useSearchParams();
  const [state, setState] = useState<TabsState>(() => parseState(params));
  const [lastEvictedTabId, setLastEvictedTabId] = useState<string | null>(null);
  const clockRef = useRef(maxOpenedAt(state.tabs));
  const stateRef = useRef(state);

  useEffect(() => {
    const next = parseState(params);
    clockRef.current = Math.max(clockRef.current, maxOpenedAt(next.tabs));
    stateRef.current = next;
    setState(next);
  }, [params]);

  const writeUrl = useCallback(
    (nextState: TabsState) => {
      const nextParams = new URLSearchParams(params);
      nextParams.delete("node");
      if (nextState.tabs.length === 0 || nextState.activeTabId === null) {
        nextParams.delete("tabs");
        nextParams.delete("active");
      } else {
        nextParams.set("tabs", nextState.tabs.map((tab) => tab.id).join(","));
        nextParams.set("active", nextState.activeTabId);
      }
      setParams(nextParams, { replace: true });
    },
    [params, setParams],
  );

  const openTab = useCallback(
    (nodeKey: string) => {
      if (!nodeKey) return;
      const prev = stateRef.current;
      const existing = prev.tabs.find((tab) => tab.id === nodeKey);
      if (existing) {
        if (prev.activeTabId === nodeKey) return;
        const next = { ...prev, activeTabId: nodeKey };
        stateRef.current = next;
        setLastEvictedTabId(null);
        setState(next);
        writeUrl(next);
        return;
      }

      let tabs = prev.tabs;
      let evicted: string | null = null;
      if (tabs.length >= MAX_TABS) {
        const oldest = [...tabs].sort((a, b) => a.openedAt - b.openedAt)[0];
        evicted = oldest.id;
        tabs = tabs.filter((tab) => tab.id !== oldest.id);
      }

      clockRef.current += 1;
      const next = {
        tabs: [...tabs, tabOf(nodeKey, clockRef.current)],
        activeTabId: nodeKey,
      };
      stateRef.current = next;
      setLastEvictedTabId(evicted);
      setState(next);
      writeUrl(next);
    },
    [writeUrl],
  );

  const closeTab = useCallback(
    (id: string) => {
      const prev = stateRef.current;
      const index = prev.tabs.findIndex((tab) => tab.id === id);
      if (index === -1) return;

      const tabs = prev.tabs.filter((tab) => tab.id !== id);
      let activeTabId = prev.activeTabId;
      if (prev.activeTabId === id) {
        activeTabId =
          tabs[index]?.id ?? tabs[index - 1]?.id ?? tabs[0]?.id ?? null;
      }

      const next = { tabs, activeTabId };
      stateRef.current = next;
      setLastEvictedTabId(null);
      setState(next);
      writeUrl(next);
    },
    [writeUrl],
  );

  const setActive = useCallback(
    (id: string) => {
      const prev = stateRef.current;
      if (prev.activeTabId === id) return;
      if (!prev.tabs.some((tab) => tab.id === id)) return;
      const next = { ...prev, activeTabId: id };
      stateRef.current = next;
      setLastEvictedTabId(null);
      setState(next);
      writeUrl(next);
    },
    [writeUrl],
  );

  return {
    ...state,
    activeNodeKey: state.activeTabId,
    lastEvictedTabId,
    openTab,
    closeTab,
    setActive,
  };
}
