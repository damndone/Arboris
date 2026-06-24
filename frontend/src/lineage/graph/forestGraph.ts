// frontend/src/lineage/graph/forestGraph.ts
//
// v1.6.1 (2C.4) — pure graph helpers for the cross-run lineage forest.
//
// The backend head-set already dedups nodes by node_hash, so the forest is a
// union DAG: a shared prefix (e.g. the cleaned dataset C) appears once, and a
// rerun fork shows as sibling branches off it (M1 / M2). These helpers compute
// the two interactions the canvas needs without any layout/rendering concern:
//   - tracePath: the upstream lineage of a node (root → node).
//   - headActiveSet: the node set belonging to a given head's run (highlight set;
//     also the basis for non-mutating rollback — see 2C.5).

import type { ForestViewModel, GraphViewEdge } from "../api/graphViewTypes";

/** target node key → its parent (source) keys, from the union edge set. */
export function parentMap(edges: GraphViewEdge[]): Map<string, string[]> {
  const parents = new Map<string, string[]>();
  for (const e of edges) {
    const list = parents.get(e.target) ?? [];
    list.push(e.source);
    parents.set(e.target, list);
  }
  return parents;
}

/**
 * Upstream lineage of `nodeKey`, ordered root → node (inclusive). Walks parent
 * pointers; on the rare multi-parent node it follows the lexicographically-first
 * parent (deterministic) so the result is always a simple path. Cycle-guarded.
 */
export function tracePath(forest: ForestViewModel, nodeKey: string): string[] {
  const parents = parentMap(forest.edges);
  const chain: string[] = [nodeKey];
  const seen = new Set<string>([nodeKey]);
  let cursor = nodeKey;
  for (;;) {
    const ps = (parents.get(cursor) ?? []).slice().sort();
    const next = ps.find((p) => !seen.has(p));
    if (next === undefined) break;
    chain.push(next);
    seen.add(next);
    cursor = next;
  }
  return chain.reverse();
}

/**
 * The set of node keys belonging to a head run (a node belongs to every run that
 * produced it — shared prefixes belong to all heads). This is the highlight set
 * when a head is active, and selecting an ancestor head is rollback (2C.5): pure
 * view state, no backend mutation.
 */
export function headActiveSet(forest: ForestViewModel, runId: string): Set<string> {
  const set = new Set<string>();
  for (const node of forest.nodes) {
    if (node.runs.includes(runId)) set.add(node.id);
  }
  return set;
}
