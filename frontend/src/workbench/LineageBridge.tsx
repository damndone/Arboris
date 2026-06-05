// frontend/src/workbench/LineageBridge.tsx
//
// V1.5.3 F3 — bridges WorkbenchStateProvider → LineageContext.
//
// Before this bridge, LineageContext was fed by `useSelectedNode` (which
// used `useTabs` with its own independent URL writer via `setParams`).
// That created a dual-writer architecture where `useTabs.writeUrl` and
// `WorkbenchStateProvider.commit()` could overwrite each other's
// `?tabs=` / `?active=` params in the same tick.
//
// LineageBridge eliminates the second writer by sourcing ALL selection
// state (selectedKey, select, tabs, activeTabId, setActiveTab, closeTab,
// lastEvictedTabId) from WorkbenchStateProvider's dispatch table. The
// LineageContext interface shape stays identical — zero consumer changes.
//
// Architecture after this bridge:
//
//   WorkbenchRouteContainer
//     └── <WorkbenchStateProvider>         ← single URL writer (commit)
//           └── <LineageBridge model={m}>  ← reads useWorkbench()
//                 └── <LineageContext.Provider>
//                       └── <WorkbenchShell>  ← unchanged, useLineage()

// LineageBridge also inherits the auto-select behaviour from
// `useSelectedNode`: on first load (or when the run scope changes), if no
// tab is active, it auto-opens the first review (or caution) node so the
// drawer isn't empty on initial render.

import { useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import { LineageContext, type LineageContextValue } from "../lineage/LineageContext";
import type { GraphViewModel } from "../lineage/api/graphViewTypes";
import { useWorkbench } from "./WorkbenchStateProvider";

export interface LineageBridgeProps {
  model: GraphViewModel;
  children: ReactNode;
}

export function LineageBridge({ model, children }: LineageBridgeProps) {
  const { state, dispatch } = useWorkbench();

  // ── auto-select (migrated from useSelectedNode) ──────────────────
  // On first render (or when the run changes), if the drawer would be
  // empty, auto-open the first review/caution node. This matches the
  // V1.5.1 behaviour exactly — auto-select never overrides an existing
  // user selection and re-arms when the run scope changes.
  const didAutoSelectRef = useRef(false);
  const lastAutoSelectScopeRef = useRef<string | null>(null);
  const autoSelectScope = model.runId ?? null;

  // Re-arm auto-select when the scope (run) changes.
  useEffect(() => {
    if (lastAutoSelectScopeRef.current === autoSelectScope) return;
    lastAutoSelectScopeRef.current = autoSelectScope;
    didAutoSelectRef.current = false;
  }, [autoSelectScope]);

  // Execute auto-select: pick first review (then caution) node when no
  // tab is active. Uses selectByCanvasClick so focus follows selection
  // on initial load (correct: user hasn't pinned anything yet).
  useEffect(() => {
    if (didAutoSelectRef.current) return;
    if (model.nodes.length === 0) return;
    didAutoSelectRef.current = true;

    if (state.activeTabId !== null) return;

    const pick =
      model.nodes.find((n) => n.trust === "review") ??
      model.nodes.find((n) => n.trust === "caution");
    if (!pick) return;

    dispatch.selectByCanvasClick(pick.id);
  }, [state.activeTabId, model.nodes, dispatch]);

  // select(key) → open/activate a tab + set focus (normal UX for user clicks)
  // select(null) → close the active tab (drawer close / Escape)
  const select = useCallback(
    (key: string | null) => {
      if (key === null) {
        if (state.activeTabId !== null) dispatch.closeTab(state.activeTabId);
        return;
      }
      dispatch.selectByCanvasClick(key);
    },
    [state.activeTabId, dispatch],
  );

  // setActiveTab switches the active tab without modifying the tab list.
  // Maps to Provider's selectByTabSwitch which handles focus correctly.
  const setActiveTab = useCallback(
    (id: string) => {
      dispatch.selectByTabSwitch(id);
    },
    [dispatch],
  );

  // closeTab removes a specific tab. Provider's closeTab handles active
  // promotion + focus follow correctly.
  const closeTab = useCallback(
    (id: string) => {
      dispatch.closeTab(id);
    },
    [dispatch],
  );

  const value = useMemo<LineageContextValue>(
    () => ({
      model,
      selectedKey: state.selectedKey,
      select,
      tabs: state.tabs,
      activeTabId: state.activeTabId,
      setActiveTab,
      closeTab,
      lastEvictedTabId: state.lastEvictedTabId,
    }),
    [
      model,
      state.selectedKey,
      select,
      state.tabs,
      state.activeTabId,
      setActiveTab,
      closeTab,
      state.lastEvictedTabId,
    ],
  );

  return (
    <LineageContext.Provider value={value}>
      {children}
    </LineageContext.Provider>
  );
}
