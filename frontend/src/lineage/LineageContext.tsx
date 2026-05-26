// frontend/src/lineage/LineageContext.tsx
//
// V1.5.0 lineage context (Step 5, T5.4).
//
// Per architect review (plan §8 T5.4 step 1): V1.5.0 uses React Context to
// share `{ model, selectedKey, select }` between the route container and
// downstream consumers (workbench, drawer, decisions panel). V1.5.1's
// multi-tab work will swap the Provider implementation without touching
// consumers.

import { createContext, useContext } from "react";
import type { GraphViewModel } from "./api/graphViewTypes";
import type { TabState } from "./hooks/useTabs";

export interface LineageContextValue {
  model: GraphViewModel;
  selectedKey: string | null;
  select: (key: string | null) => void;
  tabs?: TabState[];
  activeTabId?: string | null;
  setActiveTab?: (id: string) => void;
  closeTab?: (id: string) => void;
  lastEvictedTabId?: string | null;
}

/**
 * `null` sentinel value means "no provider above this consumer" — calling
 * `useLineage()` outside the provider throws so missing wiring fails loud.
 */
export const LineageContext = createContext<LineageContextValue | null>(null);

export function useLineage(): LineageContextValue {
  const ctx = useContext(LineageContext);
  if (ctx === null) {
    throw new Error(
      "useLineage() must be called inside <LineageContext.Provider>. " +
        "Did you forget to wrap the tree in <LineageRouteContainer>?",
    );
  }
  return ctx;
}
