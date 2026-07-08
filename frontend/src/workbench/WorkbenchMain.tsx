// frontend/src/workbench/WorkbenchMain.tsx
//
// V1.5.2 P3 — workbench main area. Renders exactly one view based on
// `useWorkbench().state.view`. The switch is the only place that
// mounts/unmounts views — so leaving a view always unmounts its local
// state (expandedGroups, viewport overrides). This is intentional;
// per-view sessionStorage hooks (useSessionByRunId) restore the
// important pieces on remount.

import { useWorkbench } from "./WorkbenchStateProvider";
import { GraphView } from "./views/GraphView";
import { TableView } from "./views/TableView";
import { PipelineView } from "./views/PipelineView";

export function WorkbenchMain({ projectRoot }: { projectRoot: string }) {
  const { state } = useWorkbench();
  return (
    <div
      data-testid="workbench-main"
      data-view={state.view}
      style={{
        flex: 1,
        minHeight: 0,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {state.view === "graph" && <GraphView />}
      {state.view === "table" && <TableView projectRoot={projectRoot} />}
      {state.view === "pipeline" && <PipelineView />}
    </div>
  );
}
