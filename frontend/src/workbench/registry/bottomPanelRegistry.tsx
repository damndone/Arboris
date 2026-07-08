// frontend/src/workbench/registry/bottomPanelRegistry.ts
//
// V1.5.2 P4 — BottomPanelRegistry, populated. Plan §12.
//
// V1.5.2 ships Logs live; Shell / Pending / Timeline appear in the
// tab strip as `disabled` so users see the slots are coming. URL
// `?panel=<id>` activates whichever is current — disabled panels render
// the PlaceholderPanel body explaining the deferral.

import type { FC } from "react";
import type { RegistryEntry } from "./registryTypes";
import { LogsPanel } from "../panels/LogsPanel";
import { PlaceholderPanel } from "../panels/PlaceholderPanel";

export type BottomPanelId = "logs" | "shell" | "pending" | "timeline";

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
    id: "shell",
    order: 20,
    label: "Shell",
    Component: () => (
      <PlaceholderPanel
        title="Shell"
        comingIn="V1.5.3"
        description="Run editable ops + rerun-from-here will surface their stdout/stderr in this panel."
      />
    ),
    shouldRender: () => true,
    disabled: () => ({ reason: "Shell sandbox lands in V1.5.3" }),
  },
  {
    id: "pending",
    order: 30,
    label: "Pending confirmations",
    Component: () => (
      <PlaceholderPanel
        title="Pending"
        comingIn="V1.5.3"
        description="Decisions that need user review will list here for batch confirmation."
      />
    ),
    shouldRender: () => true,
    disabled: () => ({
      reason: "Decision-review workflow lands in V1.5.3",
    }),
  },
  {
    id: "timeline",
    order: 40,
    label: "Timeline",
    Component: () => (
      <PlaceholderPanel
        title="Timeline"
        comingIn="V1.5.3"
        description="Chronological replay of stage executions + decision evaluations."
      />
    ),
    shouldRender: () => true,
    disabled: () => ({ reason: "Timeline view lands in V1.5.3" }),
  },
];

export function panelById(id: BottomPanelId): BottomPanelEntry | null {
  return bottomPanelRegistry.find((p) => p.id === id) ?? null;
}
