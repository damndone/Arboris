// v1.9.0 — the workbench in the new workspace shell. The classic shell keeps
// owning tab, panel, focus and float state; this component only places the
// pieces it already builds (stage tabs, docked node or review panel, floating
// overlays) into the new regions, so both shells share one source of state
// while the new one is behind its switch (design spec §8.8).

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { AgentPanel } from "../workbench/agent/AgentPanel";
import { LogsPanel } from "../workbench/panels/LogsPanel";
import { AiActivityPanel } from "../workbench/panels/AiActivityPanel";
import { GraphView } from "../workbench/views/GraphView";
import { GraphAutoFitContext } from "../lineage/graph/AutoFitOnResize";
import { useLineage } from "../lineage/LineageContext";
import { DetailSlotsContext, type DetailSlots } from "../lineage/detail/detailSlots";
import type { HeadSetNode } from "../lineage/api/graphViewTypes";
import { useForest } from "../workbench/ForestContext";
import { ownerRunOf } from "../workbench/agent/focus";
import { ModelResultView } from "./result/ModelResultView";
import { StageIndex } from "./result/StageIndex";
import { modelIdOf } from "./result/resultModel";
import { WorkbenchMain } from "../workbench/WorkbenchMain";
import { useWorkbench } from "../workbench/WorkbenchStateProvider";
import { useTopbarActions } from "../workbench/useTopbarActions";
import { rootToSlug } from "../workbench/projectSlug";
import { RunsTable } from "./RunsTable";
import { AgentColumnComposer } from "./agent/AgentColumnComposer";
import { MapTree } from "./MapTree";
import { StageHost } from "./StageHost";
import { WorkspaceBottomPanel, type BottomTab } from "./WorkspaceBottomPanel";
import { WorkspaceShell, type MapPresentation } from "./WorkspaceShell";
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

// Ask AI is the Agent column in the workspace; the analysis-loop status is an
// internal record (design spec §8.7). Both stay in the classic shell.
const STAGE_HIDDEN_SECTIONS: ReadonlySet<string> = new Set(["askAi", "analysisLoop"]);

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
  const { model } = useLineage();
  const forest = useForest();
  const navigate = useNavigate();
  const detailSlots: DetailSlots = {
    hiddenSections: STAGE_HIDDEN_SECTIONS,
    lead: (node) => {
      if (!modelIdOf(node)) return <StageIndex key={node.id} />;
      const owner = forest && "runs" in node
        ? ownerRunOf(node as HeadSetNode, forest.forest, forest.activeRunId) ?? runId
        : runId;
      return (
        <>
          <StageIndex key={node.id} />
          <ModelResultView key={`${owner}:${node.id}`} projectRoot={projectRoot} runId={owner} node={node} />
        </>
      );
    },
  };
  // The details fold away to give the map the whole width; choosing another
  // step brings them back.
  const [stageFolded, setStageFolded] = useState(false);
  useEffect(() => setStageFolded(false), [state.selectedKey]);
  // Choosing a step from project home (search, the command palette) shows it.
  const lastSelected = useRef(state.selectedKey);
  useEffect(() => {
    if (state.selectedKey !== lastSelected.current && state.selectedKey && state.view === "home") dispatch.setView("graph");
    lastSelected.current = state.selectedKey;
  }, [state.selectedKey, state.view, dispatch]);

  const topbarFor = (controls?: Parameters<Parameters<typeof WorkspaceShell>[0]["topbar"]>[0]) => (
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
  );
  const main = (
    <WorkbenchMain
      projectRoot={projectRoot}
      reportFocusRequest={reportFocusRequest}
      onOpenSettings={onOpenSettings}
      onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}/graph`)}
    />
  );

  if (state.view === "home") {
    return (
      <div className="ws-page" data-testid="workspace-home">
        <header className="ws-topbar" role="banner">{topbarFor()}</header>
        <main className="ws-page__body" aria-label="Project home">{main}</main>
        {overlays}
      </div>
    );
  }

  const analysis = state.view === "graph";
  const hasOpenItem = stagePanel !== null;
  const stageOpen = analysis ? hasOpenItem && !stageFolded : true;
  const bottomTabs: BottomTab[] = [
    { id: "runs", label: "Runs", render: () => <RunsTable projectRoot={projectRoot} /> },
    { id: "logs", label: "Logs", render: () => <LogsPanel runId={runId} projectRoot={projectRoot} /> },
    { id: "activity", label: "Activity", render: () => <AiActivityPanel runId={runId} projectRoot={projectRoot} /> },
  ];
  const map = (presentation: MapPresentation) => (
    <>
      <div className="ws-map__graph" hidden={presentation !== "graph"}>
        <GraphAutoFitContext.Provider value={true}>
          <GraphView />
        </GraphAutoFitContext.Provider>
      </div>
      {presentation === "tree" && (
        <MapTree nodes={model.nodes} edges={model.edges} selectedKey={state.selectedKey} onSelect={dispatch.selectByCanvasClick} />
      )}
      {analysis && hasOpenItem && stageFolded && (
        <button type="button" className="ws-button ws-map__reopen" onClick={() => setStageFolded(false)}>
          Show details
        </button>
      )}
    </>
  );

  return (
    <>
      <WorkspaceShell
        projectRoot={projectRoot}
        view={state.view}
        topbar={(controls) => topbarFor(controls)}
        stageOpen={stageOpen}
        map={map}
        stage={
          analysis ? (
            <DetailSlotsContext.Provider value={detailSlots}>
              <StageHost tabs={stageTabs} panel={stagePanel} onFold={() => setStageFolded(true)} />
            </DetailSlotsContext.Provider>
          ) : (
            main
          )
        }
        agent={<AgentPanel runId={runId} projectRoot={projectRoot} composer={<AgentColumnComposer />} />}
        bottom={<WorkspaceBottomPanel projectRoot={projectRoot} tabs={bottomTabs} />}
      />
      {overlays}
    </>
  );
}
