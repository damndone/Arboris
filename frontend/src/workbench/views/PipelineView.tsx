// frontend/src/workbench/views/PipelineView.tsx
//
// V1.5.2 P3 — placeholder for the Pipeline view (plan §3). Same
// rationale as TableView: ship the switcher slot now so V1.5.3+ can
// fill in real content without rewriting the URL / state / drawer /
// action plumbing.

import { useWorkbench } from "../WorkbenchStateProvider";

export function PipelineView() {
  const { state } = useWorkbench();
  return (
    <div
      data-testid="view-pipeline"
      data-view="pipeline"
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
        minHeight: 0,
        overflow: "auto",
      }}
    >
      <div style={{ fontSize: 18, color: "var(--label)", fontWeight: 600 }}>
        Pipeline view — coming in V2.0
      </div>
      <div style={{ fontSize: 13, maxWidth: 420 }}>
        A flow/pipeline projection of the run's stages and operations.
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
