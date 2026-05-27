// frontend/src/workbench/registry/bottomPanelRegistry.ts
//
// V1.5.2 — BottomPanelRegistry. Plan §12.
//
// Entries become tabs inside the BottomPanel component (P4). URL
// params `panel=<id>` / `panelOpen=0|1` are owned by
// WorkbenchStateProvider (P2). Splitter height lives in sessionStorage
// (Tier 2) keyed by runId.
//
// V1.5.2 ships Logs live; Shell / Pending / Timeline registered with
// `disabled: true` so their slots are reserved and they appear in the
// tab strip greyed out. Real implementations land in later versions.

import type { FC } from "react";
import type { RegistryEntry } from "./registryTypes";

/** Stable ids — narrow union so URL parsing rejects garbage. */
export type BottomPanelId = "logs" | "shell" | "pending" | "timeline";

/**
 * V1.5.2-P1: panels don't depend on per-node context the way sections
 * do; their context is just the runId and the workbench state. P4
 * widens this as needed; for P1 we use `unknown` so the type compiles
 * without forcing a concrete shape too early.
 */
export interface BottomPanelContext {
  runId: string;
}

export interface BottomPanelEntry
  extends RegistryEntry<BottomPanelContext> {
  id: BottomPanelId;
  /** Tab label in the panel strip. */
  label: string;
  /** Panel body. Receives the same context as `shouldRender`. */
  Component: FC<BottomPanelContext>;
  /** Disabled panels still appear in the tab strip but cannot be
   *  activated. Reason surfaces as a tooltip. */
  disabled?: (ctx: BottomPanelContext) => false | { reason: string };
}

// V1.5.2-P1: registry is exported empty. P4 fills with Logs (live)
// + Shell/Pending/Timeline (disabled placeholders).
export const bottomPanelRegistry: BottomPanelEntry[] = [];
