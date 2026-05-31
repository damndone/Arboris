// frontend/src/workbench/ContextMenu.tsx
//
// V1.5.2 P4 — right-click context menu driven by NodeActionRegistry.
//
// Reads `state.contextMenu` (Tier 3 memory) — when non-null, renders
// a portal at (x, y) showing the actions registered for surface
// `graph-context-menu`. Closes on Escape, outside click, or scroll
// (same UX as the existing NodeActionMenu).
//
// V1.5.2 only wires the graph-context-menu surface; the drawer-header-
// menu and topbar surfaces stay on V1.5.0's hardcoded NodeActionMenu
// for now and will migrate in V1.5.3 once the registry is proven.

import { useEffect, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import {
  actionsForSurface,
  type ActionContext,
  type ActionEntry,
} from "./registry/actionRegistry";
import { useWorkbench } from "./WorkbenchStateProvider";
import { useLineage } from "../lineage/LineageContext";

export function ContextMenu() {
  const { state, dispatch } = useWorkbench();
  const { model } = useLineage();
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Close on Escape / outside click / scroll.
  useEffect(() => {
    if (state.contextMenu === null) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        dispatch.closeContextMenu();
      }
    };
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t)) return;
      dispatch.closeContextMenu();
    };
    const onScroll = () => dispatch.closeContextMenu();
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onMouseDown, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onMouseDown, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [state.contextMenu, dispatch]);

  // Reposition if menu would clip the viewport. Runs once per open.
  useLayoutEffect(() => {
    if (state.contextMenu === null || !menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      menuRef.current.style.left = `${window.innerWidth - rect.width - 8}px`;
    }
    if (rect.bottom > window.innerHeight) {
      menuRef.current.style.top = `${window.innerHeight - rect.height - 8}px`;
    }
  }, [state.contextMenu]);

  if (state.contextMenu === null) return null;

  const node = model.nodes.find((n) => n.nodeKey === state.contextMenu!.nodeKey);
  if (!node) return null;

  const ctx: ActionContext = {
    node,
    model,
    selectedKey: state.selectedKey,
    focusKey: state.focusKey,
    pinned: state.pinned,
    dispatch: {
      openDetail: dispatch.selectByCanvasClick,
      pinTab: dispatch.selectByCanvasClick,
      pinUpstream: dispatch.pinFocus,
      // F1: focus-only. Sets focusKey + pinned=0 without touching the
      // selected tab — the drawer stays on the current node while the
      // graph highlights `key`'s upstream. Previously reused
      // selectByCanvasClick, which wrongly moved selection too.
      focusUpstream: dispatch.setFocusOnly,
    },
  };

  const actions = actionsForSurface("graph-context-menu", ctx);

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      data-testid="workbench-context-menu"
      style={{
        position: "fixed",
        top: state.contextMenu.y,
        left: state.contextMenu.x,
        background: "var(--bg-card-2)",
        borderRadius: 12,
        padding: 6,
        minWidth: 240,
        boxShadow:
          "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
        zIndex: 1000,
      }}
    >
      {actions.map((action) => (
        <ContextMenuItem key={action.id} action={action} ctx={ctx} />
      ))}
    </div>,
    document.body,
  );
}

function ContextMenuItem({
  action,
  ctx,
}: {
  action: ActionEntry;
  ctx: ActionContext;
}) {
  const { dispatch } = useWorkbench();
  const disabled = action.disabled?.(ctx);
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={`context-menu-item-${action.id}`}
      data-disabled={disabled ? "true" : undefined}
      title={disabled ? disabled.reason : undefined}
      disabled={!!disabled}
      onClick={() => {
        if (disabled) return;
        action.invoke(ctx);
        dispatch.closeContextMenu();
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
      <span>{action.label}</span>
      {action.shortcut && (
        <span
          style={{
            color: "var(--label-tertiary)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
        >
          {action.shortcut}
        </span>
      )}
    </button>
  );
}
