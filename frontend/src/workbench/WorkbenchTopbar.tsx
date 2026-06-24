// frontend/src/workbench/WorkbenchTopbar.tsx
//
// V1.5.2 P3 — workbench top bar with view-mode switcher.
//
// V1.5.2 scope: only the view switcher tabs (Graph / Table / Pipeline).
// Plan §15's `Rerun` and `Generate report` action slots are reserved
// for P4 (NodeActionRegistry wiring); P3 keeps the topbar minimal.
//
// The switcher writes `view` via `useWorkbench().dispatch.setView` —
// which goes through the provider's single-commit URL writer.

import type { ReactNode } from "react";
import {
  useWorkbench,
} from "./WorkbenchStateProvider";
import { useLineage } from "../lineage/LineageContext";
import { useForestMode } from "./ForestContext";
import type { ViewMode } from "./state/urlSchema";
import {
  actionsForSurface,
  type ActionContext,
} from "./registry/actionRegistry";

interface TabSpec {
  id: ViewMode;
  label: string;
}

const VIEW_TABS: TabSpec[] = [
  { id: "graph", label: "Graph" },
  { id: "table", label: "Table" },
  { id: "pipeline", label: "Pipeline" },
];

export function WorkbenchTopbar() {
  const { state, dispatch } = useWorkbench();
  const { model } = useLineage();
  const forestMode = useForestMode();

  // V1.5.2 P7 — topbar action slot, plan §15. Driven by actionRegistry
  // filtered by surface="topbar". The action context needs a node;
  // when no tab is selected we fall back to the first node in the
  // model so disabled placeholders still render their tooltips.
  // Once Rerun lands in V1.5.3 with a real handler, it'll likely
  // need a different context shape — handle that when it lands.
  const ctxNode =
    model.nodes.find((n) => n.nodeKey === state.selectedKey) ??
    model.nodes[0];
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
      {/* v1.6.1 — forest toggle. Persistent (sessionStorage) so it survives run/tab
       *  navigation — switches the center canvas between the per-run graph and the
       *  cross-run lineage forest. Only meaningful in the graph view. */}
      {forestMode && state.view === "graph" && (
        <button
          type="button"
          data-testid="forest-toggle"
          aria-pressed={forestMode.forestMode}
          onClick={() => forestMode.setForestMode(!forestMode.forestMode)}
          title={
            forestMode.forestMode
              ? "Showing the cross-run lineage forest — click for the single-run graph"
              : "Show the cross-run lineage forest (all reruns of this run)"
          }
          style={{
            padding: "6px 12px",
            borderRadius: 6,
            border: forestMode.forestMode
              ? "1px solid var(--tint, #0a84ff)"
              : "1px solid var(--separator, #2e2e30)",
            background: forestMode.forestMode
              ? "var(--tint-bg, rgba(10,132,255,0.12))"
              : "transparent",
            color: forestMode.forestMode ? "var(--tint, #0a84ff)" : "var(--label-secondary)",
            cursor: "pointer",
            fontSize: 13,
            fontWeight: forestMode.forestMode ? 600 : 400,
          }}
        >
          {forestMode.forestMode ? "Forest ✓" : "Forest"}
        </button>
      )}
      {/* Right-side action slot — V1.5.2 P7 plan §15. Driven by
       *  actionRegistry surface="topbar". V1.5.2 only has disabled
       *  Rerun + Generate report placeholders. */}
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
