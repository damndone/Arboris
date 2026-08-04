// frontend/src/workbench/WorkbenchTopbar.tsx
//
// V1.5.2 P3 — workbench top bar with view-mode switcher.
//
// View switcher tabs (Graph / Table / Pipeline) + the right-side action
// slot (plan §15), driven by actionRegistry surface="topbar". `Rerun` routes
// to the node rerun flow. Report navigation stays in the adjacent view tabs.
//
// The switcher writes `view` via `useWorkbench().dispatch.setView` —
// which goes through the provider's single-commit URL writer.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  useWorkbench,
} from "./WorkbenchStateProvider";
import { useLineage } from "../lineage/LineageContext";
import type { ViewMode } from "./state/urlSchema";
import {
  actionsForSurface,
  type ActionContext,
} from "./registry/actionRegistry";
import { pickRerunTargetKey } from "./rerunTarget";
import { rootToSlug } from "./projectSlug";
import { CreateProjectModal } from "../launcher/CreateProjectModal";
import { listRecents, touchRecent } from "../launcher/recents";

interface TabSpec {
  id: ViewMode;
  label: string;
}

// v1.6.7 — Pipeline tab entry retired (the Pipeline view merges into the main
// lineage graph via draft-in-graph). PipelineView + the "pipeline" ViewMode and
// WorkbenchMain branch are kept as a URL deep-link fallback; only the clickable
// tab is removed. Project Home is owned by the outer Home/Workbench
// navigation, so it is intentionally not duplicated in this inner switcher.
// Exported for testing.
export const VIEW_TABS: TabSpec[] = [
  { id: "notebook", label: "Notebook" },
  { id: "graph", label: "Graph" },
  { id: "table", label: "Table" },
  { id: "report", label: "Report" },
];

function projectName(root: string): string {
  return root.split("/").filter(Boolean).pop() ?? root;
}

/**
 * v1.6.8 T11 — topbar project switcher: 「项目名 ▾」 opens a dropdown of
 * recent projects (current one marked) plus 「＋ 新建项目…」 which reuses the
 * launcher's CreateProjectModal. Selecting / creating touches recents and
 * navigates to the project's graph home. Popover conventions mirror
 * ContextMenu.tsx (card background, 12px radius, separator ring).
 */
export function ProjectSwitcher({ projectRoot }: { projectRoot: string }) {
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const recents = open ? listRecents() : [];

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
    };
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (rootRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onScroll = () => setOpen(false);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onMouseDown, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onMouseDown, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  function goToProject(root: string, opts: { openGenesis?: boolean } = {}) {
    setOpen(false);
    touchRecent(root);
    const suffix = opts.openGenesis ? "?open_genesis=1" : "";
    navigate(`/p/${rootToSlug(root)}/graph${suffix}`, {
      state: opts.openGenesis ? { openGenesis: true } : undefined,
    });
  }

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button
        type="button"
        data-testid="project-switcher"
        aria-haspopup="menu"
        aria-expanded={open}
        title={projectRoot}
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 10px",
          borderRadius: 6,
          border: "1px solid var(--separator)",
          background: "transparent",
          color: "var(--label)",
          cursor: "pointer",
          fontSize: 13,
          fontWeight: 600,
        }}
      >
        {projectName(projectRoot)}
        <span aria-hidden="true" style={{ fontSize: 10 }}>
          ▾
        </span>
      </button>
      {open && (
        <div
          role="menu"
          data-testid="project-switcher-menu"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            background: "var(--bg-card-2)",
            borderRadius: 12,
            padding: 6,
            minWidth: 260,
            boxShadow:
              "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
            zIndex: 1000,
          }}
        >
          {recents.map((recent) => {
            const isCurrent = recent.root === projectRoot;
            return (
              <button
                key={recent.root}
                type="button"
                role="menuitem"
                aria-current={isCurrent ? "true" : undefined}
                onClick={() => {
                  if (isCurrent) {
                    setOpen(false);
                    return;
                  }
                  goToProject(recent.root);
                }}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  width: "100%",
                  padding: "9px 12px",
                  borderRadius: 8,
                  background: "transparent",
                  border: 0,
                  color: "var(--label)",
                  cursor: "pointer",
                  textAlign: "left",
                  font: "inherit",
                  fontSize: 13.5,
                }}
              >
                <span>{projectName(recent.root)}</span>
                {isCurrent && (
                  <span
                    style={{ color: "var(--label-tertiary)", fontSize: 12 }}
                  >
                    Current
                  </span>
                )}
              </button>
            );
          })}
          <button
            type="button"
            role="menuitem"
            data-testid="project-switcher-new"
            onClick={() => {
              setOpen(false);
              setModalOpen(true);
            }}
            style={{
              display: "block",
              width: "100%",
              padding: "9px 12px",
              borderRadius: 8,
              background: "transparent",
              border: 0,
              borderTop: recents.length > 0 ? "1px solid var(--separator)" : 0,
              color: "var(--label)",
              cursor: "pointer",
              textAlign: "left",
              font: "inherit",
              fontSize: 13.5,
            }}
          >
            ＋ New project…
          </button>
        </div>
      )}
      <CreateProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(root) => {
          setModalOpen(false);
          goToProject(root, { openGenesis: true });
        }}
      />
    </div>
  );
}

export function WorkbenchTopbar({
  projectRoot,
  extraActions = null,
  leadingActions = null,
  onViewChange,
}: {
  projectRoot: string;
  extraActions?: ReactNode;
  leadingActions?: ReactNode;
  onViewChange?: () => void;
}) {
  const { state, dispatch } = useWorkbench();
  const { model } = useLineage();

  // Topbar action slot (plan §15). Driven by actionRegistry filtered by
  // surface="topbar". These actions are analysis-level, so the context node
  // is the primary MODEL node (its drawer hosts the editable rerun panel) —
  // not whatever happens to be selected. v1.6.6 ③: this makes "Rerun" a
  // meaningful "re-run this analysis" shortcut that opens the model's rerun
  // panel from any view, instead of no-op'ing on the current selection.
  const targetKey = pickRerunTargetKey(model, state.selectedKey);
  const ctxNode =
    model.nodes.find((n) => n.nodeKey === targetKey) ?? model.nodes[0];
  const actionCtx: ActionContext | null = ctxNode
    ? {
        node: ctxNode,
        model,
        selectedKey: state.selectedKey,
        focusKey: state.focusKey,
        pinned: state.pinned,
        dispatch: {
          openDetail: dispatch.selectByCanvasClick,
          pinTab: dispatch.selectByCanvasClick,
          pinUpstream: dispatch.pinFocus,
          // F1: focus-only (see ContextMenu) — don't move selection.
          focusUpstream: dispatch.setFocusOnly,
        },
      }
    : null;
  const topbarActions = actionCtx
    ? actionsForSurface("topbar", actionCtx)
    : [];

  return (
    <div
      data-testid="workbench-topbar"
      role="toolbar"
      aria-label="Workbench views"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "0 16px",
        height: 40,
        borderBottom: "1px solid var(--separator, #2e2e30)",
        background: "var(--surface-elevated, transparent)",
      }}
    >
      <div
        data-testid="workbench-topbar-navigation"
        style={{ display: "flex", alignItems: "center", gap: 8 }}
      >
        {leadingActions}
        <ProjectSwitcher projectRoot={projectRoot} />
      </div>
      <div
        role="tablist"
        aria-label="Workbench view mode"
        style={{ display: "flex", gap: 4 }}
      >
        {VIEW_TABS.map((tab) => (
          <ViewTabButton
            key={tab.id}
            active={state.view === tab.id}
            onClick={() => {
              onViewChange?.();
              dispatch.setView(tab.id);
            }}
            testId={`view-tab-${tab.id}`}
          >
            {tab.label}
          </ViewTabButton>
        ))}
      </div>
      {/* Right-side analysis action slot, driven by actionRegistry. */}
      <div
        data-testid="workbench-topbar-actions"
        style={{ marginLeft: "auto", display: "flex", gap: 8 }}
      >
        {extraActions}
        {topbarActions.map((action) => {
          const disabled = action.disabled?.(actionCtx!);
          return (
            <button
              key={action.id}
              type="button"
              data-testid={`topbar-action-${action.id}`}
              data-disabled={disabled ? "true" : undefined}
              title={disabled ? disabled.reason : undefined}
              disabled={!!disabled}
              onClick={() => {
                if (disabled || !actionCtx) return;
                action.invoke(actionCtx);
              }}
              style={{
                padding: "4px 10px",
                borderRadius: 6,
                border: 0,
                background: "transparent",
                color: disabled ? "var(--label-tertiary)" : "var(--label)",
                cursor: disabled ? "not-allowed" : "pointer",
                fontSize: 12,
                opacity: disabled ? 0.7 : 1,
              }}
            >
              {action.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ViewTabButton({
  active,
  onClick,
  children,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  testId: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      data-testid={testId}
      onClick={onClick}
      style={{
        padding: "8px 12px",
        border: 0,
        background: active ? "var(--tint-bg, rgba(10,132,255,0.12))" : "transparent",
        color: active ? "var(--tint, #0a84ff)" : "var(--label-secondary)",
        cursor: "pointer",
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        borderRadius: 6,
      }}
    >
      {children}
    </button>
  );
}
