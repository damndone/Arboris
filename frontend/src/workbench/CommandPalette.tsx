// frontend/src/workbench/CommandPalette.tsx
//
// V1.5.3 F7 — ⌘⇧P command palette. Plan §10 (command-palette surface).
//
// Mirrors SearchPalette's portal + ↑/↓ + Enter UX, but lists ACTIONS
// (actionRegistry "command-palette" surface) instead of nodes. Actions
// run against the current selected node — the same subject the shortcut
// dispatcher (F6) and drawer menu use.
//
// Contract:
//   - ⌘⇧P toggles (Ctrl+Shift+P cross-platform). Reuses F4's
//     isEditableTarget guard so it never fires while typing.
//   - Escape closes without side effects.
//   - Up/Down move the cursor; Enter / click invoke the cursor action.
//   - Disabled actions render greyed (reason tooltip) and cannot be
//     invoked (keyboard skips them; click is a no-op).
//   - No selected node → actions are node-scoped, so the palette shows
//     an empty-state hint instead of a list.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useLineage } from "../lineage/LineageContext";
import { useWorkbench } from "./WorkbenchStateProvider";
import {
  actionsForSurface,
  type ActionContext,
  type ActionEntry,
} from "./registry/actionRegistry";
import { isEditableTarget } from "./keyboard";
import { useProjectRootOptional } from "./ProjectRootContext";
import { rootToSlug } from "./projectSlug";

export interface CommandPaletteProps {
  projectRoot?: string | null;
}

type PaletteItem = {
  id: string;
  label: string;
  shortcut?: string;
  disabled: false | { reason: string };
  invoke: () => void;
};

export function CommandPalette({ projectRoot = null }: CommandPaletteProps) {
  const { model, selectedKey } = useLineage();
  const { state, dispatch } = useWorkbench();
  const contextProjectRoot = useProjectRootOptional();
  const effectiveProjectRoot = projectRoot ?? contextProjectRoot;
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const panelRef = useRef<HTMLDivElement | null>(null);

  // The action subject is the selected node. Node-scoped actions need it.
  const node = useMemo(
    () =>
      selectedKey === null
        ? null
        : (model.nodes.find((n) => n.nodeKey === selectedKey) ?? null),
    [model.nodes, selectedKey],
  );

  const ctx = useMemo<ActionContext | null>(() => {
    if (node === null) return null;
    return {
      node,
      model,
      selectedKey: state.selectedKey,
      focusKey: state.focusKey,
      pinned: state.pinned,
      dispatch: {
        openDetail: dispatch.selectByCanvasClick,
        pinTab: dispatch.selectByCanvasClick,
        pinUpstream: dispatch.pinFocus,
        focusUpstream: dispatch.setFocusOnly,
      },
    };
  }, [node, model, state, dispatch]);

  const nodeActions = useMemo<ActionEntry[]>(
    () => (ctx === null ? [] : actionsForSurface("command-palette", ctx)),
    [ctx],
  );
  const openGenesisAction = useMemo<PaletteItem>(
    () => ({
      id: "open-genesis",
      label: "Open data upload",
      disabled: effectiveProjectRoot ? false : { reason: "Project root required" },
      invoke: () => {
        if (!effectiveProjectRoot) return;
        navigate(`/p/${rootToSlug(effectiveProjectRoot)}/graph?open_genesis=1`, {
          state: { openGenesis: true },
        });
      },
    }),
    [navigate, effectiveProjectRoot],
  );
  const actions = useMemo<PaletteItem[]>(
    () => [
      ...nodeActions.map((action) => ({
        id: action.id,
        label: action.label,
        shortcut: action.shortcut,
        disabled: ctx ? (action.disabled?.(ctx) ?? false) : false,
        invoke: () => {
          if (ctx) action.invoke(ctx);
        },
      })),
      openGenesisAction,
    ],
    [ctx, nodeActions, openGenesisAction],
  );

  // Keep cursor in range as the list changes.
  useEffect(() => {
    if (cursor >= actions.length) setCursor(Math.max(0, actions.length - 1));
  }, [actions, cursor]);

  // ⌘⇧P / Ctrl+Shift+P toggle. Self-contained listener.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        (e.key === "p" || e.key === "P") &&
        (e.metaKey || e.ctrlKey) &&
        e.shiftKey
      ) {
        // F4 guard: don't hijack while typing (unless already open —
        // then the focus is the palette itself and toggle-close is fine).
        if (!open && isEditableTarget(document.activeElement)) return;
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape" && open) {
        e.stopPropagation();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Reset cursor + focus the panel when opening (so ↑/↓/Enter work
  // without a text input to host them).
  useEffect(() => {
    if (open) {
      setCursor(0);
      queueMicrotask(() => panelRef.current?.focus());
    }
  }, [open]);

  const invokeAction = useCallback(
    (action: PaletteItem) => {
      if (action.disabled) return;
      action.invoke();
      setOpen(false);
    },
    [],
  );

  const onPanelKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, Math.max(0, actions.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const action = actions[cursor];
      if (action) invokeAction(action);
    }
  };

  if (!open) return null;

  return createPortal(
    <div
      data-testid="command-palette-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        paddingTop: "12vh",
        zIndex: 1100,
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="listbox"
        aria-label="Command palette"
        data-testid="command-palette"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onPanelKey}
        style={{
          width: "min(560px, 92vw)",
          maxHeight: "60vh",
          background: "var(--bg-card-2, #1c1c1e)",
          borderRadius: 12,
          boxShadow: "0 24px 60px rgba(0,0,0,0.6)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          outline: "none",
        }}
      >
        <div
          style={{
            padding: "12px 16px",
            borderBottom: "1px solid var(--separator)",
            fontSize: 12,
            color: "var(--label-tertiary)",
          }}
        >
          {node === null
            ? "Commands"
            : `Commands · ${node.title ?? node.nodeKey}`}
        </div>
        <div
          data-testid="command-palette-results"
          style={{ overflow: "auto", flex: 1 }}
        >
          {node === null && (
            <div
              style={{
                padding: 16,
                color: "var(--label-tertiary)",
                fontSize: 13,
              }}
            >
              Select a node first — commands act on the selected node.
            </div>
          )}
          {node !== null && nodeActions.length === 0 && (
            <div
              style={{
                padding: 16,
                color: "var(--label-tertiary)",
                fontSize: 13,
              }}
            >
              No commands available for this node.
            </div>
          )}
          {actions.map((action, i) => {
            const disabled = action.disabled;
            return (
              <button
                key={action.id}
                type="button"
                role="option"
                aria-selected={i === cursor}
                aria-disabled={disabled ? "true" : undefined}
                data-testid={`command-palette-item-${action.id}`}
                data-active={i === cursor ? "true" : undefined}
                data-disabled={disabled ? "true" : undefined}
                title={disabled ? disabled.reason : undefined}
                disabled={!!disabled}
                onMouseEnter={() => setCursor(i)}
                onClick={() => invokeAction(action)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 16px",
                  border: 0,
                  width: "100%",
                  background:
                    i === cursor
                      ? "var(--tint-bg, rgba(10,132,255,0.15))"
                      : "transparent",
                  color: disabled ? "var(--label-tertiary)" : "var(--label)",
                  cursor: disabled ? "not-allowed" : "pointer",
                  textAlign: "left",
                  font: "inherit",
                  fontSize: 13.5,
                  opacity: disabled ? 0.55 : 1,
                }}
              >
                <span>{action.label}</span>
                {action.shortcut && (
                  <span
                    style={{
                      fontSize: 12,
                      color: "var(--label-tertiary)",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {action.shortcut}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div
          style={{
            borderTop: "1px solid var(--separator)",
            padding: "6px 12px",
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "var(--label-tertiary)",
          }}
        >
          <span>↑↓ navigate · Enter run · Esc close</span>
          <span>⌘⇧P</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
