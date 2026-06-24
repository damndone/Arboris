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
  const sources = new Set(forest.edges.map((e) => e.source));
  return {
    schemaVersion: forest.schemaVersion,
    runId,
    legacy: forest.legacy,
    nodes: forest.nodes,
    edges: forest.edges,
    stats: {
      nodeCount: forest.nodes.length,
      edgeCount: forest.edges.length,
      leafCount: forest.nodes.filter((n) => !sources.has(n.id)).length,
      hasDpCount: forest.nodes.filter((n) => n.decisions.length > 0).length,
    },
  };
}
