// frontend/src/lineage/graph/ForestCanvas.tsx
//
// v1.6.1 — cross-run lineage FOREST canvas (graph only).
//
// Renders the head-set as a left→right branching DAG (ReactFlow + dagre LR), reusing
// the same GraphNode boxes + bezier edges as the per-run GraphCanvas. This is ONLY the
// center canvas: it swaps in for GraphCanvas inside the full workbench shell, so the run
// rail, the rich DetailDrawer (which owns node detail + edit/rerun), and the bottom
// panels all stay. Selection is lifted to the shell (onSelect → LineageContext) so a
// node click opens the same drawer the per-run view uses. The active head's lineage is
// highlighted; selecting an ancestor head is rollback (pure view-state).

import { useMemo } from "react";
import ReactFlow, { Background, Controls, MarkerType, Panel } from "reactflow";
import type { Node as RFNode, Edge as RFEdge } from "reactflow";
import "reactflow/dist/style.css";
import dagre from "dagre";
import "../tokens/lineage.css";
import { GraphNode } from "./GraphNode";
import type { GraphNodeState } from "./GraphNode";
import type { ForestViewModel } from "../api/graphViewTypes";
import { headActiveSet, tracePath } from "./forestGraph";

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
  selectedNodeId: string | null;
  onSelect: (key: string | null) => void;
  activeRunId: string;
  onActiveHead: (runId: string) => void;
}

export function ForestCanvas({
  forest,
  selectedNodeId,
  onSelect,
  activeRunId,
  onActiveHead,
}: ForestCanvasProps) {
  const activeSet = useMemo(() => headActiveSet(forest, activeRunId), [forest, activeRunId]);
  const trace = useMemo(
    () => (selectedNodeId ? tracePath(forest, selectedNodeId) : []),
    [forest, selectedNodeId],
  );

  const { rfNodes, rfEdges } = useMemo(() => {
    const traceSet = new Set(trace);
    const baseNodes: RFNode[] = forest.nodes.map((n) => {
      const active = activeSet.has(n.id);
      const state: GraphNodeState =
        n.id === selectedNodeId ? "selected" : active ? "related" : "dim";
      return {
        id: n.id,
        type: "lineageNode",
        position: { x: 0, y: 0 },
        data: { node: n, state },
        selected: n.id === selectedNodeId,
        connectable: false,
      };
    });
    const edges: RFEdge[] = forest.edges.map((e) => {
      const onActiveEdge = activeSet.has(e.source) && activeSet.has(e.target);
      const onTrace = traceSet.has(e.source) && traceSet.has(e.target);
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        animated: onTrace,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        style: {
          opacity: onActiveEdge ? 1 : 0.28,
          strokeWidth: onTrace ? 2.5 : 1.5,
          stroke: onTrace ? "var(--tint, #0a84ff)" : undefined,
        },
      };
    });
    return { rfNodes: layoutLR(baseNodes, edges), rfEdges: edges };
  }, [forest, activeSet, selectedNodeId, trace]);

  return (
    <div
      data-testid="forest-canvas"
      data-view="forest"
      style={{ width: "100%", height: "100%", minHeight: 480, position: "relative" }}
    >
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
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
        <Panel position="top-left">
          <div
            data-testid="forest-heads"
            role="group"
            aria-label="Run versions (active head)"
            style={{ display: "flex", gap: 6, flexWrap: "wrap", maxWidth: 540 }}
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
                  onClick={() => onActiveHead(h.runId)}
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
  );
}
