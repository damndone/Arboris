// frontend/src/workbench/registry/actionRegistry.ts
//
// V1.5.2 P4 — NodeActionRegistry, populated. Plan §11.
//
// Single source of truth for actions exposed via:
//   - graph-context-menu (right-click on a node)
//   - drawer-header-menu (V1.5.0 NodeActionMenu's ⋯ button)
//   - topbar (V1.5.2 P3 right-side slot)
//   - shortcut (keyboard)
//   - command-palette (future)
//
// Read-only actions (open / pin tab / copy / focus / pin upstream)
// ship live. Mutating placeholders (ask AI / rerun / mark review)
// register as `disabled` so their slots, ordering, and shortcuts are
// reserved — V1.5.3+ flips the disabled function to return `false`
// once the backends land.

import type { ReactNode } from "react";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";
import { buildBranchPath } from "../../lineage/pathBuilder";
import type { GraphViewModel } from "../../lineage/api/graphViewTypes";
import type { RegistryEntry } from "./registryTypes";

export interface ActionContext {
  node: GraphViewNode;
  /** The full model — actions like Copy lineage path need it. */
  model: GraphViewModel;
  selectedKey: string | null;
  focusKey: string | null;
  pinned: boolean;
  dispatch: ActionDispatch;
}

export interface ActionDispatch {
  /** Open/activate a tab AND set selected (handled by provider via
   *  selectByCanvasClick semantics — no separate selected setter). */
  openDetail(nodeKey: string): void;
  /** Same as openDetail today; named for the user-facing verb. */
  pinTab(nodeKey: string): void;
  /** Pin upstream — sets focus + pinned=1 without touching selected. */
  pinUpstream(nodeKey: string): void;
  /** Set focus without pinning — focus follows tab switches. */
  focusUpstream(nodeKey: string): void;
}

export interface ActionEntry extends RegistryEntry<ActionContext> {
  /** Human label. */
  label: string;
  /** Optional shortcut hint, display only. */
  shortcut?: string;
  /** Surfaces this action appears in. Registered once, rendered N times. */
  surfaces: ActionSurface[];
  /** Optional icon next to label. */
  icon?: ReactNode;
  /** Disabled actions render greyed out with reason as tooltip. */
  disabled?: (ctx: ActionContext) => false | { reason: string };
  /** Imperative handler. */
  invoke: (ctx: ActionContext) => void;
}

export type ActionSurface =
  | "graph-context-menu"
  | "drawer-header-menu"
  | "topbar"
  | "shortcut"
  | "command-palette";

// ─── helpers ────────────────────────────────────────────────────────

function copyToClipboard(text: string) {
  // navigator.clipboard isn't available in jsdom; tests mock it.
  // Fall back to a no-op so production-only API absence never throws.
  try {
    void navigator.clipboard?.writeText(text);
  } catch {
    /* silent — user can right-click to copy as fallback */
  }
}

// ─── registry ───────────────────────────────────────────────────────

export const actionRegistry: ActionEntry[] = [
  {
    id: "openDetail",
    order: 10,
    label: "Open detail",
    surfaces: ["graph-context-menu"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.openDetail(ctx.node.nodeKey),
  },
  {
    id: "pinTab",
    order: 20,
    label: "Pin as tab",
    surfaces: ["graph-context-menu", "drawer-header-menu"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.pinTab(ctx.node.nodeKey),
  },
  {
    id: "copyNodeId",
    order: 30,
    label: "Copy node ID",
    surfaces: ["graph-context-menu", "drawer-header-menu"],
    shouldRender: () => true,
    invoke: (ctx) => copyToClipboard(ctx.node.nodeKey),
  },
  {
    id: "copyAsJson",
    order: 40,
    label: "Copy as JSON",
    surfaces: ["graph-context-menu", "drawer-header-menu"],
    shouldRender: () => true,
    invoke: (ctx) =>
      copyToClipboard(JSON.stringify(ctx.node.raw, null, 2)),
  },
  {
    id: "copyLineagePath",
    order: 50,
    label: "Copy lineage path",
    surfaces: ["graph-context-menu", "drawer-header-menu"],
    shouldRender: () => true,
    invoke: (ctx) =>
      copyToClipboard(buildBranchPath(ctx.model, ctx.node.id)),
  },
  {
    id: "focusUpstream",
    order: 60,
    label: "Focus upstream path",
    surfaces: ["graph-context-menu"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.focusUpstream(ctx.node.nodeKey),
  },
  {
    id: "pinUpstream",
    order: 70,
    label: "Pin upstream path",
    surfaces: ["graph-context-menu"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.pinUpstream(ctx.node.nodeKey),
  },
  {
    id: "askAiAboutNode",
    order: 80,
    label: "Ask AI about this node",
    surfaces: ["graph-context-menu", "drawer-header-menu"],
    shouldRender: () => true,
    disabled: () => ({ reason: "AI backend lands in V1.5.3" }),
    invoke: () => {
      /* placeholder — wired in V1.5.3 with /llm/chat */
    },
  },
  {
    id: "rerunFromNode",
    order: 90,
    label: "Rerun from here",
    surfaces: ["graph-context-menu", "drawer-header-menu"],
    shouldRender: () => true,
    disabled: () => ({ reason: "Partial rerun backend lands in V1.5.3" }),
    invoke: () => {
      /* placeholder — wired in V1.5.3 with /runs/<id>/rerun */
    },
  },
  {
    id: "markNeedsReview",
    order: 100,
    label: "Mark needs review",
    surfaces: ["drawer-header-menu"],
    shouldRender: () => true,
    disabled: () => ({ reason: "Review workflow lands in V1.5.3" }),
    invoke: () => {
      /* placeholder — wired in V1.5.3 */
    },
  },
  // V1.5.2 P7 — topbar action slots (plan §15). Both ship disabled
  // in V1.5.2 because real backends are V1.5.3+/V2.0. Registering
  // them now reserves their slot + ordering so the topbar can show
  // them as greyed buttons (with reason tooltips) instead of having
  // a hardcoded list.
  {
    id: "rerun",
    order: 110,
    label: "Rerun",
    surfaces: ["topbar"],
    shouldRender: () => true,
    disabled: () => ({ reason: "Full rerun backend lands in V1.5.3" }),
    invoke: () => {
      /* placeholder — wired in V1.5.3 with POST /runs/<id>/rerun */
    },
  },
  {
    id: "generateReport",
    order: 120,
    label: "Generate report",
    surfaces: ["topbar"],
    shouldRender: () => true,
    disabled: () => ({ reason: "Report generation lands in V2.0" }),
    invoke: () => {
      /* placeholder — wired in V2.0 */
    },
  },
];

/**
 * Filter registry entries for a specific surface, then by
 * `shouldRender(ctx)`, then sort by order. Returns a new array each
 * call — fine for the small N (≤ 10 actions in V1.5.2).
 */
export function actionsForSurface(
  surface: ActionSurface,
  ctx: ActionContext,
): ActionEntry[] {
  return actionRegistry
    .filter((e) => e.surfaces.includes(surface))
    .filter((e) => e.shouldRender(ctx))
    .sort((a, b) => a.order - b.order);
}
