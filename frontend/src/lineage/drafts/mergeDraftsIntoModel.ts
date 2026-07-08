// v1.6.7 — inject active drafts as pending child nodes of their source model
// node. Anchor by node_hash (unique) then opNodeId; skip if source not visible.
// Runs as the final producer of ForestWorkbench's `model` so validNodeKeys
// (derived from model.nodes) includes draft keys — see spec §4.2 ordering.

import type { GraphViewModel, GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import type { DraftEntry, DraftRegistry } from "./draftRegistry";
import type { PipelineDraftNode } from "../../api";

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

function isGenesisDraft(entry: DraftEntry): boolean {
  return entry.draft?.created_from?.source_type === "genesis";
}

function genesisNodeStage(node: PipelineDraftNode): GraphViewNode["stage"] {
  if (node.node_type === "input.upload") return "source";
  if (node.node_type === "table") return "transform";
  if (node.node_type === "model") return "model";
  return "source";
}

function genesisNodeTitle(node: PipelineDraftNode): string {
  if (node.node_type === "input.upload") {
    return `draft · ${node.upload.filename}`;
  }
  if (node.node_type === "table") {
    const sheet = typeof node.params.sheet_name === "string" ? node.params.sheet_name : "table";
    return `draft · ${sheet}`;
  }
  if (node.node_type === "model") {
    return node.model_type ? `draft · ${node.model_type}` : "draft · model";
  }
  return "draft";
}

function genesisDraftNode(entry: DraftEntry, node: PipelineDraftNode): GraphViewNode {
  const key = `draft:${entry.draftId}:${node.node_id}`;
  return {
    id: key,
    nodeKey: key,
    raw: node,
    stage: genesisNodeStage(node),
    kind: node.node_type === "input.upload" ? "dataset" : node.node_type,
    title: genesisNodeTitle(node),
    parentStageId: null,
    trust: "ok",
    decisions: [],
    isDraft: true,
    draftId: entry.draftId,
    lifecycleState: entry.lifecycleState,
  };
}

function mergeGenesisDraft(
  entry: DraftEntry,
  addNodes: GraphViewNode[],
  addEdges: GraphViewModel["edges"],
) {
  const draft = entry.draft;
  if (!draft) return;
  const nodeIds = new Set(draft.graph.nodes.map((node) => node.node_id));
  for (const node of draft.graph.nodes) {
    addNodes.push(genesisDraftNode(entry, node));
  }
  for (const edge of draft.graph.edges) {
    if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to)) continue;
    const source = `draft:${entry.draftId}:${edge.from}`;
    const target = `draft:${entry.draftId}:${edge.to}`;
    addEdges.push({ id: `${source}->${target}`, source, target });
  }
}

export function mergeDraftsIntoModel(
  model: GraphViewModel,
  registry: DraftRegistry,
): GraphViewModel {
  if (registry.size === 0) return model;
  const addNodes: GraphViewNode[] = [];
  const addEdges: GraphViewModel["edges"] = [];
  for (const entry of registry.values()) {
    if (isGenesisDraft(entry)) {
      mergeGenesisDraft(entry, addNodes, addEdges);
      continue;
    }
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
