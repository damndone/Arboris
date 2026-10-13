import { useCallback, useEffect, useState } from "react";

import { fetchRunDetail } from "../api";
import { useForest } from "../workbench/ForestContext";
import { DataGrid } from "./DataGrid";
import {
  fetchDatasetVariables,
  listDatasets,
  type DatasetNode,
  type DatasetVariables,
} from "./dataViewApi";
import { DatasetExportPanel } from "../workbench/views/DatasetExportPanel";
import { SharingPanel } from "./SharingPanel";
import { TransformPanel } from "./TransformPanel";
import { VariableView } from "./VariableView";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import { ExportIcon, ShieldIcon, TransformIcon } from "../workspace/icons";
import "./dataView.css";

type Tab = "data" | "variables";

const TERMINAL = new Set(["completed", "failed", "blocked", "cancelled", "interrupted", "partial"]);
const POLL_MS = 1500;

/** The Data view: browse the active run's datasets and edit variable metadata. */
export function DataView({ projectRoot, runId: runIdProp }: { projectRoot: string; runId?: string }) {
  const forest = useForest();
  const runId = runIdProp ?? forest?.activeRunId ?? "";
  const [tab, setTab] = useState<Tab>("data");
  const [datasets, setDatasets] = useState<DatasetNode[]>([]);
  const workbench = useWorkbenchOptional();
  const selected = forest?.forest.nodes?.find(node => node.nodeKey === workbench?.state.selectedKey && node.runs.includes(runId));
  const [nodeId, setNodeId] = useState(() => selected?.kind === "dataset_stage" ? selected.opNodeId : "stage:raw");
  const [variables, setVariables] = useState<DatasetVariables | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [transforming, setTransforming] = useState(false);
  const [sharingOpen, setSharingOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [datasetsVersion, setDatasetsVersion] = useState(0);
  // Keyed by run: a status left over from the previous run must never mark a
  // newly selected, still-running run as ready for one render.
  const [runState, setRunState] = useState<{ runId: string; status: string } | null>(null);
  const runStatus = runState?.runId === runId ? runState.status : null;

  // The Agent is about the dataset this page shows (agent/focus.ts): a
  // question asked here runs on this dataset, not on the project overview.
  const setAgentFocus = workbench?.dispatch.setAgentFocus;
  useEffect(() => {
    if (!setAgentFocus || !runId) return undefined;
    setAgentFocus({ kind: "dataset", id: nodeId, runId });
    return () => setAgentFocus(null);
  }, [nodeId, runId, setAgentFocus]);

  // A run saved from the Variable view is still re-estimating when the view
  // switches to it; its datasets exist only once it finishes.
  useEffect(() => {
    if (!projectRoot || !runId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () => {
      fetchRunDetail(projectRoot, runId)
        .then((detail) => {
          if (cancelled) return;
          const status = String(detail.status ?? "");
          setRunState({ runId, status });
          if (!TERMINAL.has(status)) timer = setTimeout(poll, POLL_MS);
        })
        .catch((caught) => {
          if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not read the run");
        });
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [projectRoot, runId]);

  const ready = runStatus !== null && TERMINAL.has(runStatus);

  useEffect(() => {
    if (!projectRoot || !runId || !ready) return;
    let cancelled = false;
    setError(null);
    listDatasets(projectRoot, runId)
      .then((nodes) => {
        if (cancelled) return;
        setDatasets(nodes);
        setNodeId((current) => (nodes.some((node) => node.node_id === current) ? current : nodes[0]?.node_id ?? ""));
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not list datasets");
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, ready, datasetsVersion]);

  const loadVariables = useCallback(() => {
    if (!projectRoot || !runId || !nodeId || !ready) return () => {};
    let cancelled = false;
    setVariables(null);
    fetchDatasetVariables(projectRoot, runId, nodeId)
      .then((next) => {
        if (!cancelled) setVariables(next);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load variables");
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, nodeId, ready]);

  useEffect(() => loadVariables(), [loadVariables]);

  function onDatasetCreated(childNodeId: string) {
    setTransforming(false);
    setNodeId(childNodeId);
    setTab("data");
    setDatasetsVersion((version) => version + 1);
    forest?.refetch?.();
  }

  function onSaved(newRunId: string) {
    setSaved(newRunId);
    forest?.refetch?.();
    forest?.setActiveRunId(newRunId);
  }

  if (!runId) {
    return (
      <div className="dv">
        <p className="dv-note">Open or create a run to see its data.</p>
      </div>
    );
  }
  const tool = (open: boolean, set: (open: boolean) => void, others: Array<(open: boolean) => void>) => () => {
    // One tool at a time: the sheets share the space above the grid.
    others.forEach((close) => close(false));
    set(!open);
  };
  return (
    <div data-testid="data-view" className="dv dv-controls">
      <div className="dv-toolbar">
        <div role="tablist" aria-label="Data view mode" className="dv-seg">
          {(["data", "variables"] as const).map((mode) => (
            <button key={mode} role="tab" type="button" className="dv-seg__item" aria-selected={tab === mode} onClick={() => setTab(mode)}>
              {mode === "data" ? "Data View" : "Variable View"}
            </button>
          ))}
        </div>
        <select aria-label="Dataset" className="dv-dataset" value={nodeId} onChange={(event) => setNodeId(event.target.value)}>
          {datasets.map((node) => (
            <option key={node.node_id} value={node.node_id}>
              {datasets.filter((other) => other.label === node.label).length > 1 ? `${node.label} (${node.node_id})` : node.label}
            </option>
          ))}
        </select>
        <span className="dv-spacer" />
        <button
          type="button"
          className="dv-tool"
          aria-expanded={transforming}
          disabled={!variables}
          title="Filter, recode, compute or rename into a new dataset"
          onClick={tool(transforming, setTransforming, [setExportOpen, setSharingOpen])}
        >
          <TransformIcon />
          Transform
        </button>
        <button
          type="button"
          className="dv-tool"
          aria-expanded={exportOpen}
          disabled={!variables}
          title="Save this dataset as Stata, SPSS, CSV or Excel"
          onClick={tool(exportOpen, setExportOpen, [setTransforming, setSharingOpen])}
        >
          <ExportIcon />
          Export
        </button>
        <button
          type="button"
          className="dv-tool"
          aria-expanded={sharingOpen}
          title="What the AI provider may see from this project"
          onClick={tool(sharingOpen, setSharingOpen, [setTransforming, setExportOpen])}
        >
          <ShieldIcon />
          AI sharing
        </button>
        <span className="dv-run" title={runId}>run {runId.slice(-8)}</span>
      </div>
      {saved && (
        <p data-testid="data-view-saved" className="dv-note">
          Saved as run {saved.slice(-8)}; {ready ? "the updated data and metadata are ready." : "it is re-estimating with the new metadata."}
        </p>
      )}
      {error && <p role="alert" className="dv-alert">{error}</p>}
      {!error && runStatus !== null && !ready && (
        <p data-testid="data-view-running" className="dv-note">This run is still {runStatus}; its data appears when it finishes.</p>
      )}
      {!error && ready && runStatus !== "completed" && (
        <p role="alert" className="dv-alert">This run ended {runStatus}; its datasets may be incomplete.</p>
      )}
      {!error && (runStatus === null || (ready && !variables)) && <p className="dv-note">Loading…</p>}
      {sharingOpen && <SharingPanel projectRoot={projectRoot} onClose={() => setSharingOpen(false)} />}
      {exportOpen && variables && (
        <DatasetExportPanel projectRoot={projectRoot} runId={runId} nodeId={nodeId} onClose={() => setExportOpen(false)} />
      )}
      {variables && transforming && (
        <TransformPanel
          key={`${runId}:${nodeId}`}
          projectRoot={projectRoot}
          runId={runId}
          nodeId={nodeId}
          artifactId={variables.artifact_id}
          variables={variables.variables}
          onCreated={onDatasetCreated}
          onClose={() => setTransforming(false)}
        />
      )}
      {variables && tab === "data" && (
        <DataGrid projectRoot={projectRoot} runId={runId} nodeId={nodeId} variables={variables.variables} />
      )}
      {variables && tab === "variables" && (
        <VariableView
          projectRoot={projectRoot}
          runId={runId}
          variables={variables.variables}
          totalRows={variables.total_rows}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}
