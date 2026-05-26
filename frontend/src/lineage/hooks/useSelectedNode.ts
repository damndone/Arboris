// frontend/src/lineage/hooks/useSelectedNode.ts
//
// V1.5.1 selected-node compatibility wrapper (T7).
//
// The V1.5.1 drawer is multi-tabbed and stores selection as
// `?tabs=k1,k2&active=k2`. This hook preserves the V1.5.0 API used by
// GraphWorkbench and tests: selectedKey is the active tab's node key, and
// select(key) opens/focuses a tab while select(null) closes the active tab.

import { useCallback, useEffect, useRef } from "react";
import type { GraphViewNode } from "../api/graphViewTypes";
import { useTabs, type TabState } from "./useTabs";

export interface UseSelectedNodeResult {
  selectedKey: string | null;
  select: (key: string | null) => void;
  tabs: TabState[];
  activeTabId: string | null;
  setActiveTab: (id: string) => void;
  closeTab: (id: string) => void;
  lastEvictedTabId: string | null;
}

export function useSelectedNode(
  nodes?: GraphViewNode[] | null,
  autoSelectScope?: string | null,
): UseSelectedNodeResult {
  const {
    activeNodeKey,
    activeTabId,
    closeTab,
    lastEvictedTabId,
    openTab,
    setActive,
    tabs,
  } = useTabs();
  const didAutoSelectRef = useRef(false);
  const autoSelectScopeRef = useRef<string | null>(autoSelectScope ?? null);
  const selectedKey = activeNodeKey;

  useEffect(() => {
    const scope = autoSelectScope ?? null;
    if (autoSelectScopeRef.current === scope) return;
    autoSelectScopeRef.current = scope;
    didAutoSelectRef.current = false;
  }, [autoSelectScope]);

  useEffect(() => {
    if (didAutoSelectRef.current) return;
    if (!nodes || nodes.length === 0) return;
    didAutoSelectRef.current = true;

    if (activeNodeKey !== null) return;

    const pick =
      nodes.find((node) => node.trust === "review") ??
      nodes.find((node) => node.trust === "caution");
    if (!pick) return;

    openTab(pick.id);
  }, [activeNodeKey, nodes, openTab]);

  const select = useCallback(
    (key: string | null) => {
      if (key === null) {
        if (activeTabId !== null) closeTab(activeTabId);
        return;
      }
      openTab(key);
    },
    [activeTabId, closeTab, openTab],
  );

  return {
    selectedKey,
    select,
    tabs,
    activeTabId,
    setActiveTab: setActive,
    closeTab,
    lastEvictedTabId,
  };
}
