// frontend/src/workbench/registry/bottomPanelRegistry.ts
//
// V1.5.2 P4 — BottomPanelRegistry. Plan §12.
//
// v1.6.12 (V3 + dead-button honesty): the three "lands in V1.5.3" placeholder
// tabs (Shell / Pending / Timeline) sat disabled for seven minor versions —
// stale promises, removed. In their place ships a REAL panel: AI activity,
// the typed AI interaction log (first consumer of the operation-record
// contract that v1.7's agent loop extends). Shell/decision-review return with
// v1.7 when they have an implementation behind them.

import type { FC } from "react";
import type { RegistryEntry } from "./registryTypes";
import { LogsPanel } from "../panels/LogsPanel";
import { AiActivityPanel } from "../panels/AiActivityPanel";

export type BottomPanelId = "logs" | "ai";

export interface BottomPanelContext {
  runId: string;
  projectRoot: string;
}

export interface BottomPanelEntry extends RegistryEntry<BottomPanelContext> {
  id: BottomPanelId;
  label: string;
  Component: FC<BottomPanelContext>;
  disabled?: (ctx: BottomPanelContext) => false | { reason: string };
}

export const bottomPanelRegistry: BottomPanelEntry[] = [
  {
    id: "logs",
    order: 10,
    label: "Logs",
    Component: LogsPanel,
    shouldRender: () => true,
  },
  {
    id: "ai",
    order: 20,
    label: "AI activity",
    Component: AiActivityPanel,
    shouldRender: () => true,
  },
];

export function panelById(id: BottomPanelId): BottomPanelEntry | null {
  return bottomPanelRegistry.find((p) => p.id === id) ?? null;
}
