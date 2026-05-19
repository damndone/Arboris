import type { GraphResponse, LineageNode } from "./types";
import { getDPDisplay } from "./dpRegistry";

const MAX_HOPS = 100;

function nodeDisplay(node: LineageNode): string {
  if (node.summary && node.summary.trim()) return node.summary;
  return node.display_label;
}

function dpsDisplay(node: LineageNode): string {
  if (!node.decision_points.length) return "";
  const parts = node.decision_points.map((dp) => {
    const d = getDPDisplay(dp.decision_id);
    const sel = d.displaySelected(dp.selected);
    const params = dp.reason?.chosen_params ?? {};
    const why = d.whyShort(params);
    return why ? `[${d.title}: ${sel} | ${why}]` : `[${d.title}: ${sel}]`;
  });
  return parts.join(" ");
}

export function buildBranchPath(
  graph: GraphResponse,
  targetNodeId: string,
): string {
  const target = graph.nodes[targetNodeId];
  if (!target) return "";

  const visited = new Set<string>([targetNodeId]);
  const chain: string[] = [];
  let truncationReason: string | null = null;
  let current = target;

  for (let hop = 0; hop < MAX_HOPS; hop++) {
    const incoming = Object.values(graph.edges).filter(
      (e) => e.target_id === current.id,
    );
    if (!incoming.length) break;
    incoming.sort((a, b) => a.source_id.localeCompare(b.source_id));
    const parentEdge = incoming[0];
    const parent = graph.nodes[parentEdge.source_id];
    if (!parent) break;
    if (visited.has(parent.id)) {
      truncationReason = "cycle";
      break;
    }
    visited.add(parent.id);
    chain.unshift(parent.id);
    current = parent;
    if (hop === MAX_HOPS - 1) {
      truncationReason = "too deep";
    }
  }

  const tokens: string[] = [];
  for (const nid of [...chain, targetNodeId]) {
    const n = graph.nodes[nid];
    tokens.push(nodeDisplay(n));
    const dp = dpsDisplay(n);
    if (dp) tokens.push(dp);
  }
  let out = tokens.join(" → ");
  if (truncationReason) out += ` [truncated: ${truncationReason}]`;
  return out;
}
