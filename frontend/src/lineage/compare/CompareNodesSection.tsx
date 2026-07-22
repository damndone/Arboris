// v1.6.11 slice B-2 — drawer section for arbitrary two-node comparison.
//
// Idle: offer "Compare with another node…". Picking (this node = anchor):
// show the hint. Pair complete (this node on either side): resolve BOTH
// contexts from the forest (same pure resolver the drawer itself uses) and
// render the shared diff engine's result.
import { useForest } from "../../workbench/ForestContext";
import type {
  ForestViewModel,
  GraphViewNode,
  HeadSetNode,
} from "../api/graphViewTypes";
import { buildNodeComparison } from "../api/compareNodes";
import {
  resolveNodeOperationContext,
  type NodeOperationContextV1,
} from "../api/nodeOperationContext";
import { useProjectRootOptional } from "../../workbench/ProjectRootContext";
import { KeepComparisonButton } from "./KeepComparisonButton";
import { useCompareOptional } from "./CompareContext";
import { CompareDiffView } from "./CompareDiffView";

export function CompareNodesSection({ node }: { node: GraphViewNode }) {
  const compare = useCompareOptional();
  const forest = useForest();
  const projectRoot = useProjectRootOptional();
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
          <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center" }}>
            <KeepComparisonButton
              projectRoot={projectRoot}
              left={left}
              right={right}
              onKept={() => {
                // The comparison now exists on the graph, so the transient
                // pick has served its purpose.
                compare.clear();
                forest.refetch?.();
              }}
            />
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
    const selectedRunHint = nearestActiveAncestorOwningNode(
      forest.forest,
      forest.activeRunId,
      key,
    );
    const resolved = resolveNodeOperationContext({
      forest: forest.forest,
      selected_forest_node_key: key,
      active_head_run_id: forest.activeRunId,
      selected_run_hint: selectedRunHint,
      selected_run_hint_source: selectedRunHint
        ? "manual_candidate_selection"
        : "none",
    });
    return resolved.ok ? resolved.context : null;
  }
}

function nearestActiveAncestorOwningNode(
  forest: ForestViewModel,
  activeRunId: string,
  nodeKey: string,
): string | null {
  const target = forest.nodes.find((candidate) => candidate.nodeKey === nodeKey);
  if (!target || target.runs.includes(activeRunId)) return null;

  const headsByRunId = new Map(forest.heads.map((head) => [head.runId, head]));
  const seen = new Set<string>([activeRunId]);
  let ancestor = headsByRunId.get(activeRunId)?.rerunOf ?? null;
  while (ancestor && !seen.has(ancestor)) {
    if (target.runs.includes(ancestor)) return ancestor;
    seen.add(ancestor);
    ancestor = headsByRunId.get(ancestor)?.rerunOf ?? null;
  }
  return null;
}
