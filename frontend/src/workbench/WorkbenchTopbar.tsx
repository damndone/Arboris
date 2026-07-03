// frontend/src/workbench/WorkbenchTopbar.tsx
//
// V1.5.2 P3 — workbench top bar with view-mode switcher.
//
// View switcher tabs (Graph / Table / Pipeline) + the right-side action
// slot (plan §15), driven by actionRegistry surface="topbar". v1.6.6 ③:
// `Rerun` is live (routes to the node rerun flow); `Generate report` stays
// an honest disabled placeholder (AI backend — v1.6.8).
//
// The switcher writes `view` via `useWorkbench().dispatch.setView` —
// which goes through the provider's single-commit URL writer.

import type { ReactNode } from "react";
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

interface TabSpec {
  id: ViewMode;
  label: string;
}

// v1.6.7 — Pipeline tab entry retired (the Pipeline view merges into the main
// lineage graph via draft-in-graph). PipelineView + the "pipeline" ViewMode and
// WorkbenchMain branch are kept as a URL deep-link fallback; only the clickable
// tab is removed. Exported for testing.
export const VIEW_TABS: TabSpec[] = [
  { id: "graph", label: "Graph" },
  { id: "table", label: "Table" },
];

export function WorkbenchTopbar() {
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
        role="tablist"
        aria-label="Workbench view mode"
        style={{ display: "flex", gap: 4 }}
      >
        {VIEW_TABS.map((tab) => (
          <ViewTabButton
            key={tab.id}
            active={state.view === tab.id}
            onClick={() => dispatch.setView(tab.id)}
            testId={`view-tab-${tab.id}`}
          >
            {tab.label}
          </ViewTabButton>
        ))}
      </div>
      {/* Right-side action slot — plan §15. Driven by actionRegistry
       *  surface="topbar": live Rerun + disabled Generate report (v1.6.8). */}
      <div
        data-testid="workbench-topbar-actions"
        style={{ marginLeft: "auto", display: "flex", gap: 8 }}
      >
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
                border: "1px solid var(--separator)",
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
