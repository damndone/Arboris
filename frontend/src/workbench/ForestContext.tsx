// frontend/src/workbench/ForestContext.tsx
//
// v1.6.1 — carries the cross-run forest (head-set) + active-head state down to the
// canvas (GraphView → ForestCanvas) without threading props through the shell. Only
// present in forest mode; absent in the legacy per-run workbench.

import { createContext, useContext } from "react";
import type { ForestViewModel } from "../lineage/api/graphViewTypes";

export interface ForestContextValue {
  forest: ForestViewModel;
  /** The active head's run id (its lineage is highlighted). Selecting an ancestor
   *  head is rollback — pure view-state, no backend mutation. */
  activeRunId: string;
  setActiveRunId: (runId: string) => void;
}

export const ForestContext = createContext<ForestContextValue | null>(null);

export function useForest(): ForestContextValue | null {
  return useContext(ForestContext);
}
