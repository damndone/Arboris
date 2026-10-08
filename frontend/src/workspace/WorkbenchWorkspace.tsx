// v1.9.0 — the workbench in the new workspace shell. The classic shell keeps
// owning tab, panel, focus and float state; this component only places the
// pieces it already builds (stage tabs, docked node or review panel, floating
// overlays) into the new regions, so both shells share one source of state
// while the new one is behind its switch (design spec §8.8).

import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { AgentPanel } from "../workbench/agent/AgentPanel";
import { LogsPanel } from "../workbench/panels/LogsPanel";
import { AiActivityPanel } from "../workbench/panels/AiActivityPanel";
import { GraphView } from "../workbench/views/GraphView";
import { WorkbenchMain } from "../workbench/WorkbenchMain";
import { useWorkbench } from "../workbench/WorkbenchStateProvider";
import { useTopbarActions } from "../workbench/useTopbarActions";
import { rootToSlug } from "../workbench/projectSlug";
import { RunsTable } from "./RunsTable";
import { StageHost } from "./StageHost";
import { WorkspaceBottomPanel, type BottomTab } from "./WorkspaceBottomPanel";
import { WorkspaceShell } from "./WorkspaceShell";
import { WorkspaceTopbar } from "./WorkspaceTopbar";

export interface WorkbenchWorkspaceProps {
  runId: string;
  projectRoot: string;
  /** Open-item tabs for the Analysis stage (the classic right-panel tabs). */
  stageTabs: ReactNode;
  /** The active docked item: node details or report review; null when none. */
  stagePanel: ReactNode | null;
  reportFocusRequest: number;
  newAnalysis?: { label: string; open: () => void };
  onOpenSettings: () => void;
  /** Floating panels, dialogs and palettes that sit above any layout. */
  overlays: ReactNode;
}

function TopbarActions() {
  const { actionCtx, actions } = useTopbarActions();
  return (
    <>
      {actions.map((action) => {
        const disabled = actionCtx ? action.disabled?.(actionCtx) : { reason: "Nothing to act on yet" };
        return (
          <button
            key={action.id}
            type="button"
            data-testid={`topbar-action-${action.id}`}
            disabled={!!disabled}
            title={disabled ? disabled.reason : undefined}
            onClick={() => {
              if (!disabled && actionCtx) action.invoke(actionCtx);
            }}
          >
            {action.label}
          </button>
        );
      })}
    </>
  );
}

export function WorkbenchWorkspace({
  runId,
  projectRoot,
  stageTabs,
  stagePanel,
  reportFocusRequest,
  newAnalysis,
  onOpenSettings,
  overlays,
}: WorkbenchWorkspaceProps) {
  const { state, dispatch } = useWorkbench();
  const navigate = useNavigate();
  const bottomTabs: BottomTab[] = [
    { id: "runs", label: "Runs", render: () => <RunsTable projectRoot={projectRoot} /> },
    { id: "logs", label: "Logs", render: () => <LogsPanel runId={runId} projectRoot={projectRoot} /> },
    { id: "activity", label: "Activity", render: () => <AiActivityPanel runId={runId} projectRoot={projectRoot} /> },
  ];
  const stage =
    state.view === "graph" ? (
      <StageHost tabs={stageTabs} panel={stagePanel} />
    ) : (
      <WorkbenchMain
        projectRoot={projectRoot}
        reportFocusRequest={reportFocusRequest}
        onOpenSettings={onOpenSettings}
        onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}/graph`)}
      />
    );

  return (
    <>
      <WorkspaceShell
        projectRoot={projectRoot}
        view={state.view}
        topbar={(controls) => (
          <WorkspaceTopbar
            projectRoot={projectRoot}
            view={state.view}
            controls={controls}
            actions={<TopbarActions />}
            newAnalysisLabel={newAnalysis?.label}
            onView={dispatch.setView}
            onHome={() => dispatch.setView("home")}
            onOpenSettings={onOpenSettings}
            onNewAnalysis={newAnalysis?.open}
          />
        )}
        map={<GraphView />}
        stage={stage}
        agent={<AgentPanel runId={runId} projectRoot={projectRoot} />}
        bottom={<WorkspaceBottomPanel projectRoot={projectRoot} tabs={bottomTabs} />}
      />
      {overlays}
    </>
  );
}
