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
// Read-only actions (open / pin tab / copy / focus / pin upstream) plus
// node/topbar rerun ship live. The remaining placeholders keep their slots
// reserved with an HONEST `disabled` reason pointing at the real roadmap
// v1.6.11: askAiAboutNode (slice A, opens the drawer's Ask AI section) and
// generateReport (slice C, switches to the Report view) are LIVE. The only
// remaining placeholder is markNeedsReview → warning-layer backlog
// (roadmap §3.5 W). v1.6.6 ③ wired topbar `rerun` and made reasons honest.

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
  /** v1.6.11 slice C — switch the main view (e.g. Generate report → "report").
   *  Optional: surfaces built before v1.6.11 may not provide it. */
  setView?(view: "graph" | "table" | "pipeline" | "report"): void;
}

/** F6: structured keybinding, matched against a KeyboardEvent. Kept
 *  separate from the display-only `shortcut` string so the matcher
 *  never has to parse "⌘⇧C". `key` is compared case-insensitively
 *  against KeyboardEvent.key. Modifiers default to false; `meta`
 *  matches ⌘ (mac) OR Ctrl so bindings are cross-platform. */
export interface ShortcutKeys {
  key: string;
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
}

export interface ActionEntry extends RegistryEntry<ActionContext> {
  /** Human label. */
  label: string;
  /** Optional shortcut hint, display only (e.g. "⌘⇧C"). */
  shortcut?: string;
  /** F6: structured keybinding for the global dispatcher. An action
   *  is keyboard-triggerable iff it has `keys` AND lists the
   *  "shortcut" surface. */
  keys?: ShortcutKeys;
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
    surfaces: ["graph-context-menu", "command-palette"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.openDetail(ctx.node.nodeKey),
  },
  {
    id: "pinTab",
    order: 20,
    label: "Pin as tab",
    surfaces: ["graph-context-menu", "drawer-header-menu", "command-palette"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.pinTab(ctx.node.nodeKey),
  },
  {
    id: "copyNodeId",
    order: 30,
    label: "Copy node ID",
    // F6: first action wired to the global shortcut dispatcher. ⌘⇧C
    // avoids the taken ⌘J (raw JSON) / ⌘K (search) / Escape bindings.
    // Other actions stay keyboard-less until the keymap is reviewed
    // (handoff A.5 #3) — adding `keys` here proves the mechanism.
    shortcut: "⌘⇧C",
    keys: { key: "c", meta: true, shift: true },
    surfaces: [
      "graph-context-menu",
      "drawer-header-menu",
      "shortcut",
      "command-palette",
    ],
    shouldRender: () => true,
    invoke: (ctx) => copyToClipboard(ctx.node.nodeKey),
  },
  {
    id: "copyAsJson",
    order: 40,
    label: "Copy as JSON",
    surfaces: ["graph-context-menu", "drawer-header-menu", "command-palette"],
    shouldRender: () => true,
    invoke: (ctx) =>
      copyToClipboard(JSON.stringify(ctx.node.raw, null, 2)),
  },
  {
    id: "copyLineagePath",
    order: 50,
    label: "Copy lineage path",
    surfaces: ["graph-context-menu", "drawer-header-menu", "command-palette"],
    shouldRender: () => true,
    invoke: (ctx) =>
      copyToClipboard(buildBranchPath(ctx.model, ctx.node.id)),
  },
  {
    id: "focusUpstream",
    order: 60,
    label: "Focus upstream path",
    surfaces: ["graph-context-menu", "command-palette"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.focusUpstream(ctx.node.nodeKey),
  },
  {
    id: "pinUpstream",
    order: 70,
    label: "Pin upstream path",
    surfaces: ["graph-context-menu", "command-palette"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.pinUpstream(ctx.node.nodeKey),
  },
  {
    id: "askAiAboutNode",
    order: 80,
    label: "Ask AI about this node",
    surfaces: ["graph-context-menu", "drawer-header-menu", "command-palette"],
    shouldRender: () => true,
    // v1.6.11 slice A/C: /llm/chat is live — open the node's drawer, whose
    // Ask AI section carries the question box (flag VITE_WORKBENCH_ASK_AI).
    invoke: (ctx) => ctx.dispatch.openDetail(ctx.node.nodeKey),
  },
  {
    id: "rerunFromNode",
    order: 90,
    label: "Rerun from here",
    surfaces: ["graph-context-menu", "drawer-header-menu", "command-palette"],
    shouldRender: () => true,
    // v1.6.1 (2C.3): live. Opens the node detail whose editable OperationSection
    // submits POST /runs/<id>/rerun (forking a sibling branch in the forest).
    invoke: (ctx) => ctx.dispatch.openDetail(ctx.node.nodeKey),
  },
  {
    id: "markNeedsReview",
    order: 100,
    label: "Mark needs review",
    surfaces: ["drawer-header-menu", "command-palette"],
    shouldRender: () => true,
    // Manual review flagging (write review_status) is the warning layer —
    // roadmap §3.5 backlog W. Automatic Trust/review is already shown
    // read-only (v1.6.6 ④); the human toggle is deferred.
    disabled: () => ({ reason: "Manual review flagging lands with the warning layer (backlog W)" }),
    invoke: () => {
      /* placeholder — manual flag toggle is backlog W (roadmap §3.5) */
    },
  },
  // Topbar action slots (plan §15). v1.6.6 ③: `rerun` is now live and
  // routes to the same node rerun flow as `rerunFromNode` (open the node's
  // detail → editable OperationSection → POST /runs/<id>/rerun, forking a
  // child). `generateReport` stays an honest disabled placeholder until its
  // AI backend lands in v1.6.9.
  {
    id: "rerun",
    order: 110,
    label: "Rerun",
    surfaces: ["topbar"],
    shouldRender: () => true,
    // Live: opens the (selected/first) node's detail whose OperationSection
    // submits POST /runs/<id>/rerun — same mechanism as rerunFromNode.
    invoke: (ctx) => ctx.dispatch.openDetail(ctx.node.nodeKey),
  },
  {
    id: "generateReport",
    order: 120,
    // Named for what it does. It was called "Generate report" while only
    // switching views, so it read as a duplicate of the Report view's own
    // generate button and looked broken when nothing was produced.
    label: "Open report",
    surfaces: ["topbar"],
    shouldRender: () => true,
    invoke: (ctx) => ctx.dispatch.setView?.("report"),
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

/**
 * F6: does a keyboard event match this binding? `meta` matches ⌘ OR
 * Ctrl (cross-platform). Unspecified modifiers must be absent, so
 * ⌘⇧C does NOT fire on plain ⌘C. Key compare is case-insensitive.
 */
export function matchesKeys(
  keys: ShortcutKeys,
  e: {
    key: string;
    metaKey: boolean;
    ctrlKey: boolean;
    shiftKey: boolean;
    altKey: boolean;
  },
): boolean {
  if (e.key.toLowerCase() !== keys.key.toLowerCase()) return false;
  const wantMeta = keys.meta ?? false;
  const hasMeta = e.metaKey || e.ctrlKey;
  if (hasMeta !== wantMeta) return false;
  if ((keys.shift ?? false) !== e.shiftKey) return false;
  if ((keys.alt ?? false) !== e.altKey) return false;
  return true;
}

/**
 * F6: find the keyboard-triggerable action matching an event. Only
 * entries that list the "shortcut" surface AND have `keys` are
 * considered. Disabled / non-rendering actions are skipped so a
 * bound key silently no-ops when its action isn't available.
 * Returns the first match by `order`, or null.
 */
export function actionForShortcut(
  e: {
    key: string;
    metaKey: boolean;
    ctrlKey: boolean;
    shiftKey: boolean;
    altKey: boolean;
  },
  ctx: ActionContext,
): ActionEntry | null {
  const match = actionRegistry
    .filter((a) => a.surfaces.includes("shortcut") && a.keys)
    .filter((a) => a.shouldRender(ctx))
    .filter((a) => !a.disabled?.(ctx))
    .sort((a, b) => a.order - b.order)
    .find((a) => matchesKeys(a.keys!, e));
  return match ?? null;
}
