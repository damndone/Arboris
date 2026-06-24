// frontend/src/lineage/graph/ForestCanvas.tsx
//
// v1.6.1 (2C.4 rebuild) — cross-run lineage FOREST rendered as a real DAG.
//
// Renders the head-set as a left→right graph (ReactFlow + dagre LR), reusing the
// same node boxes (GraphNode) and bezier edges as the per-run GraphCanvas — so it
// reads like a pipeline tree with visible branches, not a row of buttons. Shared
// prefixes appear once; a rerun fork shows as sibling branches off the shared node.
// The active head's lineage is highlighted (others dimmed); selecting an ancestor
// head is rollback (pure view-state); selecting a node shows its upstream trace and,
// for an editable model node, an in-place edit→rerun panel (forks a new branch).

import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, MarkerType, Panel } from "reactflow";
import type { Node as RFNode, Edge as RFEdge } from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import "../tokens/lineage.css";
import { GraphNode } from "./GraphNode";
import type { GraphNodeState } from "./GraphNode";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";
import { headActiveSet, tracePath } from "./forestGraph";
import { OperationSection } from "../detail/sections/OperationSection";
import { RerunProvider } from "../detail/RerunContext";

const nodeTypes = { lineageNode: GraphNode };

function layoutLR(nodes: RFNode[], edges: RFEdge[]): RFNode[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 36, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: 240, height: 84 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 120, y: pos.y - 42 } };
  });
}

export interface ForestCanvasProps {
  forest: ForestViewModel;
  projectRoot: string;
  /** The run currently being viewed; its head is active by default. */
  runId: string;
  /** Called with the new child run id after an in-place rerun (forest refetch). */
  onRerun?: (childRunId: string) => void;
}

export function ForestCanvas({ forest, projectRoot, runId, onRerun }: ForestCanvasProps) {
  const defaultHead =
    forest.heads.find((h) => h.runId === runId)?.runId ??
    forest.heads[forest.heads.length - 1]?.runId ??
    runId;
  const [activeRunId, setActiveRunId] = useState<string>(defaultHead);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const activeSet = useMemo(() => headActiveSet(forest, activeRunId), [forest, activeRunId]);
  const trace = useMemo(
    () => (selectedKey ? tracePath(forest, selectedKey) : []),
    [forest, selectedKey],
  );
  const selectedNode = useMemo(
    () => forest.nodes.find((n) => n.id === selectedKey) ?? null,
    [forest, selectedKey],
  );

  const { rfNodes, rfEdges } = useMemo(() => {
    const traceSet = new Set(trace);
    const baseNodes: RFNode[] = forest.nodes.map((n) => {
      const active = activeSet.has(n.id);
      const state: GraphNodeState =
        n.id === selectedKey ? "selected" : active ? "related" : "dim";
      return {
        id: n.id,
        type: "lineageNode",
        position: { x: 0, y: 0 },
        data: { node: n, state },
        selected: n.id === selectedKey,
        connectable: false,
      };
    });
    const edges: RFEdge[] = forest.edges.map((e) => {
      const onActive = activeSet.has(e.source) && activeSet.has(e.target);
      const onTrace = traceSet.has(e.source) && traceSet.has(e.target);
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        animated: onTrace,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        style: {
          opacity: onActive ? 1 : 0.28,
          strokeWidth: onTrace ? 2.5 : 1.5,
          stroke: onTrace ? "var(--tint, #0a84ff)" : undefined,
        },
      };
    });
    return { rfNodes: layoutLR(baseNodes, edges), rfEdges: edges };
  }, [forest, activeSet, selectedKey, trace]);

  return (
    <div
      data-testid="forest-canvas"
      data-view="forest"
      style={{ display: "flex", flex: 1, minHeight: 560, height: "100%" }}
    >
      <div style={{ flex: 1, minHeight: 560, position: "relative" }}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          defaultEdgeOptions={{ type: "default" }}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.2}
          maxZoom={1.6}
          nodesConnectable={false}
          onNodeClick={(_, n) => setSelectedKey(n.id)}
          onPaneClick={() => setSelectedKey(null)}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} />
          <Controls showInteractive={false} />
          <Panel position="top-left">
            <div
              data-testid="forest-heads"
              role="group"
              aria-label="Run versions (active head)"
              style={{ display: "flex", gap: 6, flexWrap: "wrap", maxWidth: 520 }}
            >
              {forest.heads.map((h) => {
                const isActive = h.runId === activeRunId;
                return (
                  <button
                    key={h.runId}
                    type="button"
                    data-testid={`forest-head-${h.runId}`}
                    aria-pressed={isActive}
                    title={h.rerunOf ? `rerun of ${h.rerunOf}` : "original run"}
                    onClick={() => setActiveRunId(h.runId)}
                    style={{
                      fontSize: 11,
                      fontFamily: "var(--font-mono, monospace)",
                      padding: "4px 9px",
                      borderRadius: 6,
                      cursor: "pointer",
                      border: isActive
                        ? "1px solid var(--tint, #0a84ff)"
                        : "1px solid var(--separator, #2e2e30)",
                      background: isActive
                        ? "var(--tint, #0a84ff)"
                        : "var(--bg-card, rgba(255,255,255,0.04))",
                      color: isActive ? "#fff" : "var(--label-secondary)",
                    }}
                  >
                    {h.rerunOf ? "↳ " : ""}
                    {h.runId.slice(-8)}
                  </button>
                );
              })}
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {selectedNode && (
        <ForestDetailPanel
          node={selectedNode}
          trace={trace}
          forestNodes={forest.nodes}
          projectRoot={projectRoot}
          onRerun={onRerun}
          onClose={() => setSelectedKey(null)}
        />
      )}
    </div>
  );
}

function ForestDetailPanel({
  node,
  trace,
  forestNodes,
  projectRoot,
  onRerun,
  onClose,
}: {
  node: HeadSetNode;
  trace: string[];
  forestNodes: HeadSetNode[];
  projectRoot: string;
  onRerun?: (childRunId: string) => void;
  onClose: () => void;
}) {
  const titleOf = (key: string) =>
    forestNodes.find((n) => n.id === key)?.title ?? key.slice(0, 8);
  const parentRunId = node.runs[0];
  return (
    <aside
      data-testid="forest-detail"
      style={{
        width: 320,
        borderLeft: "1px solid var(--separator, #2e2e30)",
        padding: 16,
        overflowY: "auto",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <strong style={{ fontSize: 14 }}>{node.title}</strong>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          style={{
            marginLeft: "auto",
            border: 0,
            background: "transparent",
            color: "var(--label-tertiary)",
            cursor: "pointer",
            fontSize: 16,
          }}
        >
          ×
        </button>
      </div>

      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Lineage path
      </div>
      <ol
        data-testid="forest-trace"
        style={{ listStyle: "none", padding: 0, margin: "0 0 14px", display: "flex", flexWrap: "wrap", gap: 4 }}
      >
        {trace.map((key, i) => (
          <li
            key={key}
            data-testid={`forest-trace-step-${i}`}
            style={{
              fontSize: 11,
              padding: "3px 7px",
              borderRadius: 5,
              background: "var(--bg-card-2, rgba(255,255,255,0.05))",
            }}
          >
            {titleOf(key)}
            {i < trace.length - 1 ? " →" : ""}
          </li>
        ))}
      </ol>

      {parentRunId ? (
        <RerunProvider projectRoot={projectRoot} runId={parentRunId} onRerun={onRerun}>
          <OperationSection node={node} />
        </RerunProvider>
      ) : (
        <OperationSection node={node} />
      )}
    </aside>
  );
}
