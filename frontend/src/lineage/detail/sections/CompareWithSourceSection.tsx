import { useState } from "react";
import { useForest } from "../../../workbench/ForestContext";
import { resolveNodeOperationContext } from "../../api/nodeOperationContext";
import { buildNodeComparison } from "../../api/compareNodes";
import { CompareDiffView } from "../../compare/CompareDiffView";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { getCompareWithSourceGate } from "../../api/rerunProvenance";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";

export function CompareWithSourceSection(_props: { node?: GraphViewNode }) {
  const forest = useForest();
  const [showComparison, setShowComparison] = useState(false);
  const resolved = useResolvedNodeOperationContext();
  if (!resolved || !resolved.ok) return null;
  const gate = getCompareWithSourceGate(resolved.context);
  if (!gate.ok) {
    return (
      <section
        aria-label="Compare with source"
        data-testid="compare-with-source-section"
        style={{ marginTop: 18 }}
      >
        <div className="ln-section-label" style={{ marginBottom: 6 }}>
          Compare with source
        </div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          No rerun source recorded for this node.
        </div>
      </section>
    );
  }
  const sourceNode = forest?.forest.nodes.find(node => node.runs.includes(gate.rerun_from.owner_run_id) && node.opNodeId === gate.rerun_from.op_node_id && node.nodeHash === gate.rerun_from.node_hash);
  const source = sourceNode && forest ? resolveNodeOperationContext({ forest: forest.forest, selected_forest_node_key: sourceNode.nodeKey, active_head_run_id: forest.activeRunId, selected_run_hint: gate.rerun_from.owner_run_id, selected_run_hint_source: "manual_candidate_selection" }) : null;
  return (
    <section
      aria-label="Compare with source"
      data-testid="compare-with-source-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Compare with source
      </div>
      <button type="button" onClick={() => setShowComparison(value => !value)} aria-expanded={showComparison}>Compare with source</button>
      {showComparison && (source?.ok ? <CompareDiffView result={buildNodeComparison(source.context, resolved.context)} /> : <p role="status">The recorded source cannot be resolved in this project. Open its run to compare.</p>)}
    </section>
  );
}
