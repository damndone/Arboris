// frontend/src/workbench/registry/actionRegistry.ts
//
// V1.5.2 — NodeActionRegistry. Plan §11.
//
// Single source of truth for actions exposed via right-click menu,
// DetailDrawer header menu, Topbar buttons, keyboard shortcuts, and
// (future) command palette. Wiring each surface into the registry
// keeps action additions to a one-line change.
//
// V1.5.2 ships the *contract* and the safe read-only actions (open,
// copy, focus). Mutating actions (rerun, AI, mark-review) are
// registered as `disabled: true` placeholders so their slots and
// shortcuts are reserved — they get real handlers in V1.5.3+.

import type { ReactNode } from "react";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";
import type { RegistryEntry } from "./registryTypes";

/**
 * The context an action receives. Concrete handlers + the right-click
 * menu component are wired in P4. V1.5.2-P1 only locks the shape so
 * other modules (provider, drawer) can import the type now.
 */
export interface ActionContext {
  node: GraphViewNode;
  /** Selected (drawer's active tab) — may differ from `node` when
   *  the action is dispatched from a right-click on a non-active node. */
  selectedKey: string | null;
  /** Pinned focus anchor — drives upstream overlay. */
  focusKey: string | null;
  pinned: boolean;
  /** Imperative handles exposed by WorkbenchStateProvider (wired P2/P4). */
  dispatch: ActionDispatch;
}

export interface ActionDispatch {
  openDetail(nodeKey: string): void;
  pinTab(nodeKey: string): void;
  setFocus(nodeKey: string | null, opts?: { pinned?: boolean }): void;
  setSearchQuery(q: string): void;
}

export interface ActionEntry extends RegistryEntry<ActionContext> {
  /** i18n-ready label (English in V1.5.2). */
  label: string;
  /** Optional keyboard shortcut hint (e.g. "⌘C"). Display only. */
  shortcut?: string;
  /** Where this action surfaces. Multiple surfaces = registered once,
   *  rendered from many places. */
  surfaces: ActionSurface[];
  /** Optional icon. Component is rendered next to the label. */
  icon?: ReactNode;
  /** Disabled actions still render (greyed out + reason tooltip) so
   *  users can discover capabilities arriving in later versions. */
  disabled?: (ctx: ActionContext) => false | { reason: string };
  /** Imperative handler. V1.5.2-P1 leaves bodies as TODO; P4 wires them. */
  invoke: (ctx: ActionContext) => void;
}

export type ActionSurface =
  | "graph-context-menu"
  | "drawer-header-menu"
  | "topbar"
  | "shortcut"
  | "command-palette";

// V1.5.2-P1: registry is exported empty. P4 fills it with the
// initial action set listed in plan §11.
export const actionRegistry: ActionEntry[] = [];
