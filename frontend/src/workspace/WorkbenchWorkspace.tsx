// v1.9.0 — the workbench in the new workspace shell. The classic shell keeps
// owning tab, panel, focus and float state; this component only places the
// pieces it already builds (stage tabs, docked node or review panel, floating
// overlays) into the new regions, so both shells share one source of state
// while the new one is behind its switch (design spec §8.8).

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useCompareOptional } from "../lineage/compare/CompareContext";
import { createAgentForkProposal } from "../workbench/agent/agentApi";
import { useAgentNavigationOptional } from "../workbench/agent/agentNavigation";
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
import { DeferredMap } from "./DeferredMap";
import { StageHost } from "./StageHost";
import { WorkspaceBottomPanel, type BottomTab } from "./WorkspaceBottomPanel";
import { WorkspaceShell, type MapPresentation } from "./WorkspaceShell";
import { OperationsPanel } from "../manual/OperationsPanel";
import { TimelinePanel, timelineSummary, useTimeline } from "./TimelinePanel";
import { WorkspaceTopbar } from "./WorkspaceTopbar";
import { openDedicated } from "./dedicatedOperations";
import { stageIsOpen } from "./layoutModel";
import { WorkspaceCommandsContext, type WorkspaceCommands } from "./workspaceCommands";

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
  const compare = useCompareOptional();
  const openAgentNavigation = useAgentNavigationOptional();
  const [operationError, setOperationError] = useState<string | null>(null);
  const { model } = useLineage();
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisSearch, setAnalysisSearch] = useState("");
  const agentHandle = useRef<{ show(): void } | null>(null);
  const commands = useMemo<WorkspaceCommands>(() => ({
    analyze: (search = "") => {
      setAnalysisSearch(search);
      setAnalyzing(true);
    },
    showAgent: () => agentHandle.current?.show(),
  }), []);
  const forest = useForest();
  const selectedNode = forest?.forest.nodes.find(node => node.nodeKey === state.selectedKey);
  const timelineRun = selectedNode && forest ? ownerRunOf(selectedNode, forest.forest, forest.activeRunId) : forest?.activeRunId;
  const timeline = useTimeline(projectRoot, timelineRun ?? runId);
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
          <ModelResultView key={`${owner}:${node.id}`} projectRoot={projectRoot} runId={owner} node={node} onRefresh={() => {
              forest?.refetch?.();
              timeline.refresh();
            }}
          />
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
      actions={
        <>
          <button type="button" className="ws-button" onClick={() => commands.analyze()}>Analyze</button>
          <TopbarActions />
        </>
      }
      newAnalysisLabel={newAnalysis?.label}
      onView={view => {setAnalyzing(false);dispatch.setView(view);}}
      onHome={() => {setAnalyzing(false);dispatch.setView("home");}}
      onOpenSettings={onOpenSettings}
      onNewAnalysis={newAnalysis?.open}
    />
  );
  const models = (forest?.forest.nodes ?? [])
    .filter((n) => n.kind === "model")
    .flatMap((n) => n.runs.map((owner) => ({ runId: owner, nodeId: n.opNodeId, label: n.title })));
  const refresh = () => {
    forest?.refetch?.();
    timeline.refresh();
  };
  const operationPanel = (
    <>
      {operationError && <p role="alert">{operationError}</p>}
      <OperationsPanel
        key={projectRoot}
        projectRoot={projectRoot}
        runId={runId}
        initialSearch={analysisSearch}
        models={models}
        onClose={() => setAnalyzing(false)}
        onRefresh={refresh}
        onOpenRun={(owner) => {
          forest?.setActiveRunId(owner);
          setAnalyzing(false);
          dispatch.setView("table");
        }}
        onDedicated={async (op, target) => {
          setOperationError(null);
          const problem = await openDedicated(op, target, {
            focus: (chosen) => {
              if (!("run_id" in chosen)) return;
              forest?.setActiveRunId(chosen.run_id);
              const node = "node_id" in chosen
                ? forest?.forest.nodes.find((n) => n.runs.includes(chosen.run_id) && n.opNodeId === chosen.node_id)
                : undefined;
              if (node) dispatch.selectByCanvasClick(node.nodeKey);
            },
            setView: dispatch.setView,
            openNewAnalysis: newAnalysis?.open,
            openAnalyze: () => commands.analyze(),
            closeAnalyze: () => setAnalyzing(false),
            proposeFork: async (chosen) => {
              if (!openAgentNavigation) throw new Error("The Agent is not available in this view.");
              const result = await createAgentForkProposal(projectRoot, {
                source_run_id: chosen.run_id,
                source_node_ref: chosen.node_id,
                active_head_run_id: chosen.run_id,
              });
              openAgentNavigation(result.navigation);
              commands.showAgent();
            },
          });
          setOperationError(problem);
        }}
      />
    </>
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
      <WorkspaceCommandsContext.Provider value={commands}>
        <div className="ws-page" data-testid="workspace-home">
          <header className="ws-topbar" role="banner">{topbarFor()}</header>
          <main className="ws-page__body" aria-label="Project home">{analyzing ? operationPanel : main}</main>
          {overlays}
        </div>
      </WorkspaceCommandsContext.Provider>
    );
  }

  const analysis = state.view === "graph";
  const hasOpenItem = stagePanel !== null;
  const stageOpen = stageIsOpen({ analyzing, analysisView: analysis, hasOpenItem, folded: stageFolded });
  const bottomTabs: BottomTab[] = [
    { id: "timeline", label: "Timeline", render: () => <TimelinePanel value={timeline.value} error={timeline.error} onRefresh={timeline.refresh}/> },
    { id: "runs", label: "Runs", render: () => <RunsTable projectRoot={projectRoot} /> },
    { id: "logs", label: "Logs", render: () => <LogsPanel runId={runId} projectRoot={projectRoot} /> },
    { id: "activity", label: "Activity", render: () => <AiActivityPanel runId={runId} projectRoot={projectRoot} /> },
  ];
  const map = (presentation: MapPresentation) => (
    <>
      <DeferredMap visible={presentation === "graph" && model.nodes.length > 0}>
        <GraphAutoFitContext.Provider value={true}>
          <GraphView />
        </GraphAutoFitContext.Provider>
      </DeferredMap>
      {presentation === "tree" && (
        <MapTree nodes={model.nodes} edges={model.edges} selectedKey={state.selectedKey} onSelect={key => { if (!compare?.handleCanvasSelect(key)) dispatch.selectByCanvasClick(key); }} />
      )}
      {analysis && hasOpenItem && stageFolded && (
        <button type="button" className="ws-button ws-map__reopen" onClick={() => setStageFolded(false)}>
          Show details
        </button>
      )}
    </>
  );

  return (
    <WorkspaceCommandsContext.Provider value={commands}>
      <WorkspaceShell
        projectRoot={projectRoot}
        view={state.view}
        topbar={(controls) => topbarFor(controls)}
        stageOpen={stageOpen}
        map={map}
        stage={
          analyzing ? operationPanel : analysis ? (
            <DetailSlotsContext.Provider value={detailSlots}>
              <StageHost tabs={stageTabs} panel={stagePanel} onFold={() => setStageFolded(true)} />
            </DetailSlotsContext.Provider>
          ) : (
            main
          )
        }
        agent={<AgentPanel runId={runId} projectRoot={projectRoot} composer={<AgentColumnComposer />} compactHeader />}
        bottom={<WorkspaceBottomPanel projectRoot={projectRoot} tabs={bottomTabs} summary={timelineSummary(timeline.value)} />}
        agentHandle={agentHandle}
      />
      {overlays}
    </WorkspaceCommandsContext.Provider>
  );
}
