// v1.6.7 — inject active drafts as pending child nodes of their source model
// node. Anchor by node_hash (unique) then opNodeId; skip if source not visible.
// Runs as the final producer of ForestWorkbench's `model` so validNodeKeys
// (derived from model.nodes) includes draft keys — see spec §4.2 ordering.

import type { GraphViewModel, GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import type { DraftEntry, DraftRegistry } from "./draftRegistry";

function resolveAnchor(
  model: GraphViewModel,
  entry: DraftEntry,
): GraphViewNode | null {
  const nodes = model.nodes as HeadSetNode[];
  // node_hash is the authoritative anchor when present: a hash that fails to
  // match means the exact source version is gone → degrade (don't inject).
  // opNodeId is only a best-effort fallback for entries that never recorded a
  // hash (e.g. hydrated summaries with a null source_node_hash).
  if (entry.sourceNodeHash) {
    return nodes.find((n) => n.nodeHash === entry.sourceNodeHash) ?? null;
  }
  if (entry.sourceOpNodeId) {
    return nodes.find((n) => n.opNodeId === entry.sourceOpNodeId) ?? null;
  }
  return null;
}

function draftNode(entry: DraftEntry, anchor: GraphViewNode): GraphViewNode {
  const key = `draft:${entry.draftId}`;
  return {
    id: key,
    nodeKey: key,
    raw: entry.draft ?? { draft_id: entry.draftId },
    stage: anchor.stage,
    kind: "model",
    title: entry.modelType ? `draft · ${entry.modelType}` : "draft",
    parentStageId: anchor.parentStageId,
    trust: "ok",
    decisions: [],
    isDraft: true,
    draftId: entry.draftId,
    lifecycleState: entry.lifecycleState,
  };
}

export function mergeDraftsIntoModel(
  model: GraphViewModel,
  registry: DraftRegistry,
): GraphViewModel {
  if (registry.size === 0) return model;
  const addNodes: GraphViewNode[] = [];
  const addEdges: GraphViewModel["edges"] = [];
  for (const entry of registry.values()) {
    const anchor = resolveAnchor(model, entry);
    if (!anchor) continue; // source not visible → degrade
    const node = draftNode(entry, anchor);
    addNodes.push(node);
    addEdges.push({ id: `${anchor.id}->${node.id}`, source: anchor.id, target: node.id });
  }
  if (addNodes.length === 0) return model;
  const nodes = [...model.nodes, ...addNodes];
  const edges = [...model.edges, ...addEdges];
  return {
    ...model,
    nodes,
    edges,
    stats: { ...model.stats, nodeCount: nodes.length, edgeCount: edges.length },
  };
}
