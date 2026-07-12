// v1.6.11 slice B-2 — drawer section for arbitrary two-node comparison.
//
// Idle: offer "Compare with another node…". Picking (this node = anchor):
// show the hint. Pair complete (this node on either side): resolve BOTH
// contexts from the forest (same pure resolver the drawer itself uses) and
// render the shared diff engine's result.
import { useForest } from "../../workbench/ForestContext";
import type { GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import { buildNodeComparison } from "../api/compareNodes";
import {
  resolveNodeOperationContext,
  type NodeOperationContextV1,
} from "../api/nodeOperationContext";
import { useCompareOptional } from "./CompareContext";
import { CompareDiffView } from "./CompareDiffView";

export function CompareNodesSection({ node }: { node: GraphViewNode }) {
  const compare = useCompareOptional();
  const forest = useForest();
  if (!compare || !forest || !("runs" in node)) return null;
  const nodeKey = (node as HeadSetNode).nodeKey;

  const body = renderBody();
  return (
    <section aria-label="Compare nodes" data-testid="compare-nodes-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Compare
      </div>
      {body}
    </section>
  );

  function renderBody() {
    if (!compare || !forest) return null;
    if (compare.pickingFromKey === nodeKey) {
      return (
        <div style={{ fontSize: 12 }} data-testid="compare-picking-hint">
          Click another node on the graph to compare with{" "}
          <strong>{node.title}</strong>.{" "}
          <button type="button" onClick={compare.cancelPick}>
            Cancel
          </button>
        </div>
      );
    }
    const pair = compare.pair;
    if (pair && (pair.anchorKey === nodeKey || pair.targetKey === nodeKey)) {
      const left = resolveContext(pair.anchorKey);
      const right = resolveContext(pair.targetKey);
      if (!left || !right) {
        return (
          <div style={{ fontSize: 12, color: "var(--label-tertiary)" }} data-testid="compare-unresolvable">
            One side of the comparison can no longer be resolved on this forest.{" "}
            <button type="button" onClick={compare.clear}>
              Clear
            </button>
          </div>
        );
      }
      return (
        <div>
          <CompareDiffView result={buildNodeComparison(left, right)} />
          <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
            <button type="button" onClick={compare.swap}>
              Swap sides
            </button>
            <button type="button" onClick={compare.clear}>
              Clear
            </button>
          </div>
        </div>
      );
    }
    return (
      <button type="button" onClick={() => compare.startPick(nodeKey)}>
        Compare with another node…
      </button>
    );
  }

  function resolveContext(key: string): NodeOperationContextV1 | null {
    if (!forest) return null;
    const resolved = resolveNodeOperationContext({
      forest: forest.forest,
      selected_forest_node_key: key,
      active_head_run_id: forest.activeRunId,
    });
    return resolved.ok ? resolved.context : null;
  }
}
