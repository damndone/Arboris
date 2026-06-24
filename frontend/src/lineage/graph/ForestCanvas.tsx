// frontend/src/lineage/graph/ForestCanvas.tsx
//
// v1.6.1 (2C.4) — cross-run lineage forest renderer.
//
// Consumes the ForestViewModel (head-set union DAG). The functional closure
// (spec §3.3, guardrail G3): shared prefixes render once, rerun forks show as
// sibling branches, the active head's lineage is highlighted, selecting a node
// shows its upstream trace, and editing a model node forks a new branch in place
// (via OperationSection + RerunProvider — no navigation). Selecting an ancestor
// head is rollback (2C.5): pure view state, never a backend mutation.
//
// G3 — this is the FUNCTIONAL forest on plain layout; visual/dagre polish is
// explicitly out of scope here and does NOT block the closure.

import { useMemo, useState } from "react";
import type { ForestViewModel, HeadSetNode } from "../api/graphViewTypes";
import { headActiveSet, tracePath } from "./forestGraph";
import { OperationSection } from "../detail/sections/OperationSection";
import { RerunProvider } from "../detail/RerunContext";

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

  const activeSet = useMemo(
    () => headActiveSet(forest, activeRunId),
    [forest, activeRunId],
  );
  const trace = useMemo(
    () => (selectedKey ? tracePath(forest, selectedKey) : []),
    [forest, selectedKey],
  );
  const selectedNode = useMemo(
    () => forest.nodes.find((n) => n.id === selectedKey) ?? null,
    [forest, selectedKey],
  );

  return (
    <div data-testid="forest-canvas">
      <div data-testid="forest-heads" role="group" aria-label="Active head" style={{ display: "flex", gap: 6 }}>
        {forest.heads.map((h) => (
          <button
            key={h.runId}
            type="button"
            data-testid={`forest-head-${h.runId}`}
            aria-pressed={h.runId === activeRunId}
            onClick={() => setActiveRunId(h.runId)}
          >
            {h.rerunOf ? "↳ " : ""}
            {h.runId}
          </button>
        ))}
      </div>

      <ul data-testid="forest-nodes" style={{ listStyle: "none", padding: 0, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {forest.nodes.map((n) => {
          const active = activeSet.has(n.id);
          return (
            <li key={n.id}>
              <button
                type="button"
                data-testid={`forest-node-${n.id}`}
                data-active={active ? "true" : "false"}
                data-stage={n.stage}
                aria-pressed={n.id === selectedKey}
                onClick={() => setSelectedKey(n.id)}
                style={{ opacity: active ? 1 : 0.45 }}
              >
                {n.title}
              </button>
            </li>
          );
        })}
      </ul>

      {selectedNode && (
        <SelectedNodePanel
          node={selectedNode}
          trace={trace}
          projectRoot={projectRoot}
          onRerun={onRerun}
        />
      )}
    </div>
  );
}

function SelectedNodePanel({
  node,
  trace,
  projectRoot,
  onRerun,
}: {
  node: HeadSetNode;
  trace: string[];
  projectRoot: string;
  onRerun?: (childRunId: string) => void;
}) {
  // The rerun parent is the run that produced this node (its from_node lives there).
  const parentRunId = node.runs[0];
  return (
    <div data-testid="forest-detail">
      <ol data-testid="forest-trace" style={{ display: "flex", gap: 4, listStyle: "none", padding: 0 }}>
        {trace.map((key, i) => (
          <li key={key} data-testid={`forest-trace-step-${i}`}>
            {key}
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
    </div>
  );
}
