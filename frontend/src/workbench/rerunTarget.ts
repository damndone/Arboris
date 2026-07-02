// frontend/src/workbench/rerunTarget.ts
//
// v1.6.6 ③ — which node the topbar "Rerun" acts on.
//
// Product decision (user, 2026-07-02): a dedicated "return / rollback to
// parent" is unnecessary — you navigate by clicking nodes, and you re-run
// with changes by forking from a node's own "Rerun from here". So the topbar
// "Rerun" is a global shortcut meaning "re-run THIS analysis": it targets the
// primary model node (its detail drawer hosts the editable rerun panel),
// regardless of which node happens to be selected. This makes the button
// always do something visible (open the model's rerun panel) instead of
// no-op'ing when the model was already selected.

import type { GraphViewModel, GraphViewNode } from "../lineage/api/graphViewTypes";

function isModelNode(n: GraphViewNode): boolean {
  return n.kind === "model" || n.stage === "model";
}

/**
 * Pick the node the topbar Rerun should open. Prefers the primary model node
 * (the terminal model in a run), so "Rerun" always lands on the rerun panel.
 * Falls back to the selected node, then the first node. Returns null only for
 * an empty graph.
 */
export function pickRerunTargetKey(
  model: GraphViewModel,
  selectedKey: string | null,
): string | null {
  const models = model.nodes.filter(isModelNode);
  if (models.length > 0) {
    // Terminal model = the primary/last model in a single-model run.
    return models[models.length - 1].nodeKey;
  }
  const selected = model.nodes.find((n) => n.nodeKey === selectedKey);
  if (selected) return selected.nodeKey;
  return model.nodes[0]?.nodeKey ?? null;
}
