// frontend/src/workbench/views/TableView.tsx
//
// V1.5.2 P3 — placeholder for the Table view (plan §3). V1.5.2 ships
// it as a real `view=table` mode so the switcher contract is locked,
// but no business functionality. Real implementation lands in V1.5.3+.
//
// What this view WILL show eventually (per plan §3 + §10):
//   - tabular layout of nodes, variables, models
//   - same `selected / focus / search / action` contract as GraphView
//   - bottom panel + drawer + topbar all keep working
//
// For P3 it's only a "coming soon" surface. Wired to the Workbench
// state via `data-view` so tests can assert the switcher works.

import { useWorkbench } from "../WorkbenchStateProvider";

export function TableView() {
  const { state } = useWorkbench();
  return (
    <div
      data-testid="view-table"
      data-view="table"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 48,
        gap: 12,
        color: "var(--label-secondary)",
        textAlign: "center",
        height: "100%",
        minHeight: 320,
      }}
    >
      <div style={{ fontSize: 18, color: "var(--label)", fontWeight: 600 }}>
        Table view — coming in V1.5.3
      </div>
      <div style={{ fontSize: 13, maxWidth: 420 }}>
        A tabular projection of the run's nodes, variables, and models.
        Selection, search, and node actions will work the same as the
        Graph view.
      </div>
      {state.selectedKey && (
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            color: "var(--label-tertiary)",
            fontFamily: "var(--font-mono, monospace)",
          }}
        >
          Selected: {state.selectedKey}
        </div>
      )}
    </div>
  );
}
