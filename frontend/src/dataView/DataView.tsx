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
import { VariableView } from "./VariableView";

type Tab = "data" | "variables";

const TERMINAL = new Set(["completed", "failed", "blocked", "cancelled", "interrupted", "partial"]);
const POLL_MS = 1500;

/** The Data view: browse the active run's datasets and edit variable metadata. */
export function DataView({ projectRoot, runId: runIdProp }: { projectRoot: string; runId?: string }) {
  const forest = useForest();
  const runId = runIdProp ?? forest?.activeRunId ?? "";
  const [tab, setTab] = useState<Tab>("data");
  const [datasets, setDatasets] = useState<DatasetNode[]>([]);
  const [nodeId, setNodeId] = useState("stage:raw");
  const [variables, setVariables] = useState<DatasetVariables | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  // Keyed by run: a status left over from the previous run must never mark a
  // newly selected, still-running run as ready for one render.
  const [runState, setRunState] = useState<{ runId: string; status: string } | null>(null);
  const runStatus = runState?.runId === runId ? runState.status : null;

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
  }, [projectRoot, runId, ready]);

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

  function onSaved(newRunId: string) {
    setSaved(newRunId);
    forest?.refetch?.();
    forest?.setActiveRunId(newRunId);
  }

  if (!runId) {
    return <div style={{ padding: 16, color: "var(--label-secondary)" }}>Open or create a run to see its data.</div>;
  }
  return (
    <div data-testid="data-view" style={{ padding: 12, overflow: "auto", flex: 1, minHeight: 0 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, fontSize: 12 }}>
        <div role="tablist" aria-label="Data view mode">
          {(["data", "variables"] as const).map((mode) => (
            <button
              key={mode}
              role="tab"
              type="button"
              aria-selected={tab === mode}
              onClick={() => setTab(mode)}
              style={{ fontWeight: tab === mode ? 600 : 400 }}
            >
              {mode === "data" ? "Data View" : "Variable View"}
            </button>
          ))}
        </div>
        <label>
          Dataset{" "}
          <select aria-label="Dataset" value={nodeId} onChange={(event) => setNodeId(event.target.value)}>
            {datasets.map((node) => (
              <option key={node.node_id} value={node.node_id}>
                {node.label} ({node.node_id})
              </option>
            ))}
          </select>
        </label>
        <span style={{ color: "var(--label-tertiary)" }}>run {runId.slice(-8)}</span>
      </div>
      {saved && (
        <div data-testid="data-view-saved" style={{ fontSize: 12, marginBottom: 8 }}>
          Saved as run {saved.slice(-8)}; it is re-estimating with the new metadata.
        </div>
      )}
      {error && <div role="alert" style={{ color: "var(--red, #c00)", fontSize: 12 }}>{error}</div>}
      {!error && runStatus !== null && !ready && (
        <div data-testid="data-view-running" style={{ fontSize: 12, color: "var(--label-secondary)" }}>
          This run is still {runStatus}; its data appears when it finishes.
        </div>
      )}
      {!error && ready && runStatus !== "completed" && (
        <div role="alert" style={{ fontSize: 12, color: "var(--red, #c00)" }}>
          This run ended {runStatus}; its datasets may be incomplete.
        </div>
      )}
      {!error && (runStatus === null || (ready && !variables)) && (
        <div style={{ fontSize: 12, color: "var(--label-secondary)" }}>Loading…</div>
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
