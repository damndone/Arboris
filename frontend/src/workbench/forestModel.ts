// frontend/src/workbench/forestModel.ts
//
// v1.6.1 — project the cross-run ForestViewModel into the per-run GraphViewModel
// shape the workbench shell already understands. Because head-set nodes are the
// same graph_to_json nodes the per-run view uses (HeadSetNode extends GraphViewNode),
// the existing selection / DetailDrawer / rail / bottom-panel machinery works on the
// forest unchanged — the forest only swaps the center canvas (see GraphView).

import type { ForestViewModel, GraphViewModel } from "../lineage/api/graphViewTypes";

export function forestToGraphViewModel(
  forest: ForestViewModel,
  runId: string,
): GraphViewModel {
  const nodeIds = new Set(forest.nodes.map((n) => n.id));
  const haveEdge = new Set(forest.edges.map((e) => `${e.source}->${e.target}`));
  // Variable nodes carry no edges in the per-run graph (they're annotations on the
  // cleaned stage), so they'd float as orphan cards. Attach each to its parent stage so
  // it hangs off the cleaned node (and folds cleanly when there are many).
  const synthesized: GraphViewModel["edges"] = [];
  for (const n of forest.nodes) {
    if (n.kind !== "variable" || !n.parentStageId) continue;
    if (!nodeIds.has(n.parentStageId)) continue;
    const id = `${n.parentStageId}->${n.id}`;
    if (haveEdge.has(`${n.parentStageId}->${n.id}`)) continue;
    synthesized.push({ id, source: n.parentStageId, target: n.id });
  }
  const edges = [...forest.edges, ...synthesized];
  const sources = new Set(edges.map((e) => e.source));
  return {
    schemaVersion: forest.schemaVersion,
    runId,
    legacy: forest.legacy,
    nodes: forest.nodes,
    edges,
    stats: {
      nodeCount: forest.nodes.length,
      edgeCount: edges.length,
      leafCount: forest.nodes.filter((n) => !sources.has(n.id)).length,
      hasDpCount: forest.nodes.filter((n) => n.decisions.length > 0).length,
    },
  };
}
