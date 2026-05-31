// frontend/src/lineage/graph/NodeActionMenu.tsx
//
// V1.5.2 P6 — refactored to consume actionRegistry (plan §11).
//
// Renders the actions registered for the `drawer-header-menu` surface.
// V1.5.0 hardcoded 4 items inline; that's replaced with a registry
// loop so new actions (or disabled placeholders for AI / rerun /
// mark-review) appear automatically.
//
// When mounted outside WorkbenchStateProvider (legacy test harness),
// the menu degrades to V1.5.0's read-only invokes — copyNodeId,
// copyAsJson, copyLineagePath, plus the "View Raw JSON" item that
// is NOT in the registry (it's drawer-internal — owned by the
// drawer, not a node-scoped action). This keeps the existing
// RawJsonModal flow intact.
//
// Popup is rendered via createPortal into document.body and positioned
// against the trigger's getBoundingClientRect() with `position: fixed`.
// Closes on outside-click + Escape + scroll (V1.4.1 MoreMenu pattern
// hardened in V1.5.0 REV-3 F1+F2).

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";
import {
  actionsForSurface,
  type ActionContext,
} from "../../workbench/registry/actionRegistry";
import { useWorkbenchOptional } from "../../workbench/WorkbenchStateProvider";
import "../tokens/lineage.css";

export interface NodeActionMenuProps {
  node: GraphViewNode;
  /** Needed by "Copy lineage path"; pass the same model the workbench owns. */
  model: GraphViewModel;
  /** Caller wires this to open the RawJsonModal. View Raw JSON stays
   *  drawer-local (not a registry action) because it controls a
   *  drawer-owned modal, not a node-scoped imperative. */
  onShowJson: () => void;
}

interface PopupCoords {
  top: number;
  right: number;
}

const GAP_PX = 6;

export function NodeActionMenu({
  node,
  model,
  onShowJson,
}: NodeActionMenuProps) {
  const wb = useWorkbenchOptional();
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<PopupCoords | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setCoords(null);
      return undefined;
    }
    const compute = () => {
      const btn = triggerRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      setCoords({
        top: rect.bottom + GAP_PX,
        right: window.innerWidth - rect.right,
      });
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onDocMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (popupRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDocMouseDown, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  // Build the action context. When the provider is absent the
  // registry's dispatch-dependent actions (openDetail, pinTab,
  // pinUpstream, focusUpstream) gracefully no-op via the stub
  // dispatch below — V1.5.0/1.5.1 test harnesses keep working.
  const ctx: ActionContext = {
    node,
    model,
    selectedKey: wb?.state.selectedKey ?? null,
    focusKey: wb?.state.focusKey ?? null,
    pinned: wb?.state.pinned ?? false,
    dispatch: {
      openDetail: wb?.dispatch.selectByCanvasClick ?? (() => {}),
      pinTab: wb?.dispatch.selectByCanvasClick ?? (() => {}),
      pinUpstream: wb?.dispatch.pinFocus ?? (() => {}),
      // F1: focus-only (see ContextMenu) — don't move selection.
      focusUpstream: wb?.dispatch.setFocusOnly ?? (() => {}),
    },
  };
  const registryActions = actionsForSurface("drawer-header-menu", ctx);

  const closeAfter = (fn: () => void) => () => {
    fn();
    setOpen(false);
  };

  const popup =
    open && coords !== null ? (
      <div
        ref={popupRef}
        role="menu"
        data-testid="node-action-menu-popup"
        style={{
          position: "fixed",
          top: coords.top,
          right: coords.right,
          background: "var(--bg-card-2)",
          borderRadius: 12,
          padding: 6,
          minWidth: 240,
          boxShadow:
            "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
          zIndex: 1000,
        }}
      >
        {/* View Raw JSON is drawer-owned (not registry) — stays at top. */}
        <MenuItem
          label="View Raw JSON"
          shortcut="⌘J"
          onClick={closeAfter(onShowJson)}
          testId="drawer-menu-item-view-raw-json"
        />
        {registryActions.map((action) => {
          const disabled = action.disabled?.(ctx);
          return (
            <MenuItem
              key={action.id}
              label={action.label}
              shortcut={action.shortcut}
              disabled={disabled ? disabled.reason : undefined}
              onClick={closeAfter(() => action.invoke(ctx))}
              testId={`drawer-menu-item-${action.id}`}
            />
          );
        })}
      </div>
    ) : null;

  return (
    <div
      style={{ display: "inline-block" }}
      data-testid="node-action-menu"
    >
      <button
        ref={triggerRef}
        type="button"
        className="ln-btn-secondary"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Node actions"
      >
        Actions ⌄
      </button>
      {popup !== null && createPortal(popup, document.body)}
    </div>
  );
}

function MenuItem({
  label,
  shortcut,
  onClick,
  disabled,
  testId,
}: {
  label: string;
  shortcut?: string;
  onClick: () => void;
  disabled?: string;
  testId: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      data-disabled={disabled ? "true" : undefined}
      title={disabled}
      disabled={!!disabled}
      onClick={() => {
        if (disabled) return;
        onClick();
      }}
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "9px 12px",
        borderRadius: 8,
        background: "transparent",
        border: 0,
        color: disabled ? "var(--label-tertiary)" : "var(--label)",
        cursor: disabled ? "not-allowed" : "pointer",
        textAlign: "left",
        font: "inherit",
        fontSize: 13.5,
        width: "100%",
        opacity: disabled ? 0.55 : 1,
      }}
    >
      <span>{label}</span>
      {shortcut && (
        <span
          style={{
            color: "var(--label-tertiary)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
        >
          {shortcut}
        </span>
      )}
    </button>
  );
}
