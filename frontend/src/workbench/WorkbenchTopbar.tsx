// frontend/src/workbench/WorkbenchTopbar.tsx
//
// V1.5.2 P3 — workbench top bar with view-mode switcher.
//
// V1.5.2 scope: only the view switcher tabs (Graph / Table / Pipeline).
// Plan §15's `Rerun` and `Generate report` action slots are reserved
// for P4 (NodeActionRegistry wiring); P3 keeps the topbar minimal.
//
// The switcher writes `view` via `useWorkbench().dispatch.setView` —
// which goes through the provider's single-commit URL writer — so
// switching never collides with useTabs's tabs/active writes.

import type { ReactNode } from "react";
import {
  useWorkbench,
} from "./WorkbenchStateProvider";
import type { ViewMode } from "./state/urlSchema";

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
      {/* Right-side action slot — reserved for P4 Rerun / Generate report */}
      <div
        data-testid="workbench-topbar-actions"
        style={{ marginLeft: "auto", display: "flex", gap: 8 }}
      />
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
