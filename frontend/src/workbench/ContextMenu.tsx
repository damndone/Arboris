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

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  actionsForSurface,
  type ActionContext,
  type ActionEntry,
} from "./registry/actionRegistry";
import {
  hideGraphNodeFromView,
  readHiddenGraphNodeIds,
  restoreHiddenGraphNodes,
  useWorkbench,
} from "./WorkbenchStateProvider";
import { useLineage } from "../lineage/LineageContext";
import {
  confirmRunDeletion,
  previewRunDeletion,
  type RunDeletionPreview,
} from "../api";
import { useProjectRootOptional } from "./ProjectRootContext";
import { useForest } from "./ForestContext";
import { RunDeletionDialog } from "./RunDeletionDialog";

type DeletionState = {
  runId: string;
  preview: RunDeletionPreview | null;
  busy: boolean;
  error: string | null;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unable to prepare deletion preview.";
}

export function ContextMenu() {
  const { state, dispatch } = useWorkbench();
  const { model } = useLineage();
  const projectRoot = useProjectRootOptional();
  const forest = useForest();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [deletion, setDeletion] = useState<DeletionState | null>(null);

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

  const menu = state.contextMenu;

  const node = menu?.nodeKey === null
    ? undefined
    : model.nodes.find((n) => n.nodeKey === menu?.nodeKey);
  const hiddenNodeCount = readHiddenGraphNodeIds(model.runId).size;

  const hideNode = () => {
    if (!node) return;
    hideGraphNodeFromView(model.runId, node.id);
    dispatch.refreshGraphCleanup();
    dispatch.closeContextMenu();
  };
  const restoreHiddenNodes = () => {
    restoreHiddenGraphNodes(model.runId);
    dispatch.refreshGraphCleanup();
    dispatch.closeContextMenu();
  };
  const beginDelete = () => {
    if (!projectRoot || !forest) return;
    const runId = forest.activeRunId || model.runId;
    setDeletion({ runId, preview: null, busy: true, error: null });
    dispatch.closeContextMenu();
    void previewRunDeletion(projectRoot, runId)
      .then((preview) => setDeletion({ runId, preview, busy: false, error: null }))
      .catch((error: unknown) =>
        setDeletion({ runId, preview: null, busy: false, error: errorMessage(error) }),
      );
  };
  const confirmDelete = () => {
    if (!projectRoot || !deletion?.preview) return;
    setDeletion((current) => current ? { ...current, busy: true, error: null } : current);
    void confirmRunDeletion(projectRoot, deletion.runId, {
      fingerprint: deletion.preview.fingerprint,
      confirmationRunId: deletion.runId,
    })
      .then(() => {
        forest?.onRunDeleted?.(deletion.runId);
        setDeletion(null);
      })
      .catch((error: unknown) =>
        setDeletion((current) => current ? {
          ...current,
          busy: false,
          error: errorMessage(error),
        } : current),
      );
  };

  const ctx: ActionContext | null = node
    ? {
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
      }
    : null;
  const actions = ctx ? actionsForSurface("graph-context-menu", ctx) : [];
  const canDeleteCurrentRun = Boolean(node && projectRoot && forest);

  const menuPortal = menu && (node || hiddenNodeCount > 0)
    ? createPortal(
      <div
        ref={menuRef}
        role="menu"
        data-testid="workbench-context-menu"
        style={{
          position: "fixed",
          top: menu.y,
          left: menu.x,
          background: "var(--bg-card-2)",
          borderRadius: 12,
          padding: 6,
          minWidth: 240,
          boxShadow:
            "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
          zIndex: 1000,
        }}
      >
        {node && (
          <ContextMenuCommand
            testId="context-menu-hide-from-view"
            label="Hide from this view"
            onClick={hideNode}
          />
        )}
        {hiddenNodeCount > 0 && (
          <ContextMenuCommand
            testId="context-menu-restore-hidden"
            label={`Restore ${hiddenNodeCount} hidden ${hiddenNodeCount === 1 ? "node" : "nodes"}`}
            onClick={restoreHiddenNodes}
          />
        )}
        {canDeleteCurrentRun && (
          <ContextMenuCommand
            testId="context-menu-delete-run"
            label="Delete current Run…"
            danger
            onClick={beginDelete}
          />
        )}
        {actions.map((action) => (
          <ContextMenuItem key={action.id} action={action} ctx={ctx!} />
        ))}
      </div>,
      document.body,
    )
    : null;

  if (!menuPortal && deletion === null) return null;
  return (
    <>
      {menuPortal}
      {deletion?.preview && (
        <RunDeletionDialog
          preview={deletion.preview}
          busy={deletion.busy}
          error={deletion.error}
          onClose={() => setDeletion(null)}
          onConfirm={confirmDelete}
        />
      )}
      {deletion && !deletion.preview && (
        <RunDeletionLoading
          message={deletion.error ?? "Preparing deletion preview…"}
          onClose={() => setDeletion(null)}
        />
      )}
    </>
  );
}

function ContextMenuCommand({
  testId,
  label,
  danger = false,
  onClick,
}: {
  testId: string;
  label: string;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      onClick={onClick}
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "9px 12px",
        borderRadius: 8,
        background: "transparent",
        border: 0,
        color: danger ? "var(--danger, #c5221f)" : "var(--label)",
        cursor: "pointer",
        textAlign: "left",
        font: "inherit",
        fontSize: 13.5,
        width: "100%",
      }}
    >
      {label}
    </button>
  );
}

function RunDeletionLoading({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
  return createPortal(
    <div
      role="presentation"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1200,
        display: "grid",
        placeItems: "center",
        padding: 20,
        background: "rgba(0, 0, 0, 0.48)",
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Run deletion preview"
        style={{
          width: "min(420px, 100%)",
          borderRadius: 14,
          padding: 22,
          background: "var(--bg-card, #fff)",
          color: "var(--label, #1d1d1f)",
        }}
      >
        <p role="status" style={{ margin: 0 }}>{message}</p>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
          <button type="button" onClick={onClose}>Close</button>
        </div>
      </section>
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
