import { type AppShellStatusContext, type WorkbenchHomeProps } from "./workbenchPanelUi";
import "../lineage/tokens/lineage.css";
import "./panelHost.css";
import { ForestWorkbench } from "./ForestWorkbench";
import { WorkbenchShell } from "./WorkbenchShell";
import { useEffect, useMemo } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { useGraphData } from "../lineage/hooks/useGraphData";
import { ErrorBanner, Loading } from "../lineage/statusViews";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { LineageBridge } from "./LineageBridge";
import { ReportWorkspaceProvider } from "../report/ReportWorkspaceContext";
import { registerBuiltinFeatureViews } from "./agent/builtinFeatureViews";
// Workbench route data, providers and shared node/report window state.
// The workspace owns the only layout; legacy run URLs enter the same shell.
// Draft execution, selection, overlays and pending-index recovery remain here.


/** v1.6.8 T11 — the project-keyed workbench home. The forest is keyed by
 *  projectRoot alone; runId is only an optional focus hint. */
export function WorkbenchHome({
  projectRoot,
  focusRunId,
  openGenesis = false,
  settingsRequestVersion = 0,
}: WorkbenchHomeProps) {
  // This is the live project-home mount path. The bootstrap itself is
  // idempotent so React StrictMode and route remounts cannot duplicate a view.
  useEffect(() => {
    registerBuiltinFeatureViews();
  }, []);

  // v1.6.8 — the project home renders the project forest. A run deep link is
  // only a focus hint; if that run is absent from the project forest, probe the
  // old run-keyed headset once so true legacy runs can still use the legacy
  // per-run workbench.
  return (
    <ForestWorkbench
      projectRoot={projectRoot}
      focusRunId={focusRunId}
      openGenesis={openGenesis}
      settingsRequestVersion={settingsRequestVersion}
    />
  );
}

interface WorkbenchRouteContainerProps {
  projectRoot: string;
  runId: string;
}

/** Legacy per-run entry point (runDetail.tsx still passes a required runId).
 *  Same component; runId becomes the focus hint. */
export function WorkbenchRouteContainer({
  projectRoot,
  runId,
}: WorkbenchRouteContainerProps) {
  return <WorkbenchHome projectRoot={projectRoot} focusRunId={runId} />;
}

export function LegacyGraphWorkbench({
  projectRoot,
  runId,
  onOpenSettings,
}: WorkbenchRouteContainerProps & { onOpenSettings: () => void }) {
  const navigate = useNavigate();
  const appShellContext = useOutletContext<AppShellStatusContext>();
  const { model, loading, error, refetch } = useGraphData(projectRoot, runId);

  useEffect(() => {
    if (!appShellContext?.setError) return;
    if (error?.kind === "not_found") {
      appShellContext.setError("Project not found");
      return;
    }
    appShellContext.setError(null);
  }, [appShellContext?.setError, error]);

  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(() => {
    if (model === null) return undefined;
    return new Set(model.nodes.map((n) => n.nodeKey));
  }, [model]);

  if (loading) return <Loading />;
  if (error !== null) {
    return (
      <ErrorBanner
        error={error}
        onRetry={refetch}
        onHome={() => navigate("/?launcher=1")}
      />
    );
  }
  if (model === null) return <Loading />;

  return (
    <WorkbenchStateProvider runId={runId} validNodeKeys={validNodeKeys}>
      <LineageBridge model={model}>
          <ReportWorkspaceProvider projectRoot={projectRoot}>
            <WorkbenchShell
              runId={runId}
              projectRoot={projectRoot}
              onOpenSettings={onOpenSettings}
            />
          </ReportWorkspaceProvider>
      </LineageBridge>
    </WorkbenchStateProvider>
  );
}
