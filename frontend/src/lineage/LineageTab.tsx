import { useEffect, useMemo, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { getRunGraph, ApiError } from "../api";
import { GraphCanvas } from "./GraphCanvas";
import { Inspector } from "./Inspector";
import { DecisionCard } from "./DecisionCard";
import { DecisionExpanded } from "./DecisionExpanded";
import { MoreMenu } from "./MoreMenu";
import { buildBranchPath } from "./pathBuilder";
import { adaptRunGraph } from "./api/graphAdapter";
import type { GraphResponse } from "./types";
import "./tokens/lineage.css";

interface LineageTabProps {
  projectRoot: string;
  runId: string;
}

type LoadState =
  | { kind: "loading" }
  | {
      kind: "error";
      code: "not-found" | "corrupt" | "network";
      detail: string;
    }
  | { kind: "ok"; graph: GraphResponse };

export function LineageTab({ projectRoot, runId }: LineageTabProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [params, setParams] = useSearchParams();
  const selectedNodeId = params.get("node");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [expandedDP, setExpandedDP] = useState<Set<string>>(new Set());
  const [showJson, setShowJson] = useState(false);
  const [copyFlash, setCopyFlash] = useState(false);

  // V1.5.0 bridge: GraphCanvas + pathBuilder consume GraphViewModel post-T5.5.
  // Computed unconditionally to satisfy Rules of Hooks; returns null while
  // loading or on error. T5.7 swaps this whole component out for
  // LineageRouteContainer, retiring the bridge.
  const viewModel = useMemo(
    () => (state.kind === "ok" ? adaptRunGraph(state.graph) : null),
    [state],
  );

  const load = useCallback(() => {
    setState({ kind: "loading" });
    getRunGraph(projectRoot, runId)
      .then((g) => setState({ kind: "ok", graph: g }))
      .catch((e) => {
        if (e instanceof ApiError) {
          if (e.status === 404)
            setState({
              kind: "error",
              code: "not-found",
              detail: "Run not found",
            });
          else if (e.status === 422)
            setState({ kind: "error", code: "corrupt", detail: e.message });
          else setState({ kind: "error", code: "network", detail: e.message });
        } else {
          setState({ kind: "error", code: "network", detail: String(e) });
        }
      });
  }, [projectRoot, runId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        (e.metaKey || e.ctrlKey) &&
        e.key.toLowerCase() === "j" &&
        selectedNodeId
      ) {
        e.preventDefault();
        setShowJson((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedNodeId]);

  if (state.kind === "loading")
    return (
      <div className="lineage-root" style={{ padding: 24 }}>
        Loading lineage…
      </div>
    );

  if (state.kind === "error") {
    const labels = {
      "not-found": "Run not found",
      corrupt: "Lineage data is corrupt",
      network: "Could not load lineage",
    };
    return (
      <div className="lineage-root" style={{ padding: 24 }}>
        <div className="ln-callout ln-callout--red">
          <div className="ln-callout-title">{labels[state.code]}</div>
          <div className="ln-callout-body">{state.detail}</div>
          {state.code !== "not-found" && (
            <button
              className="ln-btn-primary"
              onClick={load}
              style={{ marginTop: 12 }}
            >
              Try again
            </button>
          )}
        </div>
      </div>
    );
  }

  if (state.graph.legacy) {
    return (
      <div
        className="lineage-root"
        style={{
          padding: 24,
          textAlign: "center",
          color: "var(--label-secondary)",
        }}
      >
        <div style={{ fontSize: 16, color: "var(--label)", marginBottom: 8 }}>
          No lineage data for this run
        </div>
        <div>
          This run predates V1.4. Lineage tracking became available with V1.4.0.
        </div>
      </div>
    );
  }

  const selectedNode = selectedNodeId
    ? state.graph.nodes[selectedNodeId]
    : null;

  const handleSelect = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("node", id);
    setParams(next, { replace: false });
    setExpandedDP(new Set());
  };
  const handleClose = () => {
    const next = new URLSearchParams(params);
    next.delete("node");
    setParams(next, { replace: false });
  };
  const handleExpandGroup = (gid: string) => {
    setExpandedGroups((s) => {
      const next = new Set(s);
      if (next.has(gid)) next.delete(gid);
      else next.add(gid);
      return next;
    });
  };
  const handleCopyPath = () => {
    if (!selectedNode || !viewModel) return;
    navigator.clipboard.writeText(buildBranchPath(viewModel, selectedNode.id));
    setCopyFlash(true);
    setTimeout(() => setCopyFlash(false), 1500);
  };

  return (
    <div
      className="lineage-root"
      style={{ display: "flex", gap: 0, minHeight: 600 }}
    >
      <div style={{ flex: 1 }}>
        {viewModel && (
          <GraphCanvas
            model={viewModel}
            selectedNodeId={selectedNodeId}
            expandedGroups={expandedGroups}
            onSelect={handleSelect}
            onExpandGroup={handleExpandGroup}
          />
        )}
      </div>
      {selectedNode && (
        <div
          style={{ width: 460, borderLeft: "1px solid var(--separator)" }}
        >
          <Inspector node={selectedNode} onClose={handleClose} />
          <div
            style={{ padding: "0 22px 18px", display: "flex", gap: 8 }}
          >
            <button className="ln-btn-primary" onClick={handleCopyPath}>
              {copyFlash ? "✓ Copied" : "📋 Copy path"}
            </button>
            <MoreMenu
              node={selectedNode}
              onShowJson={() => setShowJson(true)}
            />
          </div>
          <div
            style={{
              padding: "12px 22px 22px",
              borderTop: "0.5px solid var(--separator)",
            }}
          >
            <div className="ln-section-label" style={{ marginBottom: 12 }}>
              Decisions to review · {selectedNode.decision_points.length}
            </div>
            {selectedNode.decision_points.map((dp) => {
              const isExp = expandedDP.has(dp.decision_id);
              return isExp ? (
                <DecisionExpanded key={dp.decision_id} dp={dp} />
              ) : (
                <DecisionCard
                  key={dp.decision_id}
                  dp={dp}
                  expanded={false}
                  onToggle={() =>
                    setExpandedDP((s) => new Set(s).add(dp.decision_id))
                  }
                />
              );
            })}
          </div>
          {showJson && (
            <div
              role="dialog"
              aria-label="Raw JSON"
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0,0,0,0.6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 100,
              }}
            >
              <div
                className="ln-card"
                style={{
                  background: "var(--bg-card-2)",
                  width: 600,
                  maxHeight: "80vh",
                  overflow: "auto",
                  borderRadius: 14,
                }}
              >
                <pre
                  style={{
                    margin: 0,
                    padding: 18,
                    fontFamily: "ui-monospace, SF Mono, monospace",
                    fontSize: 12,
                    color: "var(--label)",
                  }}
                >
                  {JSON.stringify(selectedNode, null, 2)}
                </pre>
                <button
                  className="ln-btn-secondary"
                  onClick={() => setShowJson(false)}
                  style={{ margin: 12 }}
                >
                  Close
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
