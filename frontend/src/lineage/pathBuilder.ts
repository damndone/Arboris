import type {
  GraphViewModel,
  GraphViewNode,
} from "./api/graphViewTypes";
import { getDPDisplay } from "./decisions/decisionRegistry";

const MAX_HOPS = 100;

function nodeDisplay(node: GraphViewNode): string {
  if (node.summary && node.summary.trim()) return node.summary;
  return node.title;
}

function dpsDisplay(node: GraphViewNode): string {
  if (!node.decisions.length) return "";
  // Use the registry's `displaySelected` to enrich picked values
  // (e.g. "continuous" → "OLS" for model_type_auto_select). The
  // `whyShort` enrichment from V1.4.1 is dropped here because the
  // ViewModel does not carry `chosen_params` (no-fabrication rule).
  const parts = node.decisions.map((dp) => {
    const reg = getDPDisplay(dp.id);
    const sel = reg.displaySelected(dp.picked) || dp.picked;
    return `[${reg.title}: ${sel}]`;
  });
  return parts.join(" ");
}

export function buildBranchPath(
  model: GraphViewModel,
  targetNodeId: string,
): string {
  const nodeById = new Map<string, GraphViewNode>(
    model.nodes.map((n) => [n.id, n]),
  );
  const target = nodeById.get(targetNodeId);
  if (!target) return "";

  const visited = new Set<string>([targetNodeId]);
  const chain: string[] = [];
  let truncationReason: string | null = null;
  let current = target;
  let hop = 0;

  for (; hop < MAX_HOPS; hop++) {
    const incoming = model.edges.filter((e) => e.target === current.id);
    if (!incoming.length) break;
    // Multi-parent: pick lex-smallest source deterministically.
    incoming.sort((a, b) => a.source.localeCompare(b.source));
    const parentEdge = incoming[0];
    const parent = nodeById.get(parentEdge.source);
    if (!parent) break;
    if (visited.has(parent.id)) {
      truncationReason = "cycle";
      break;
    }
    visited.add(parent.id);
    chain.unshift(parent.id);
    current = parent;
  }

  // Only mark "too deep" if we exhausted the loop *and* there's still more
  // ancestry to walk — a chain of exactly MAX_HOPS ancestors that terminates
  // naturally is NOT truncated.
  if (hop === MAX_HOPS && truncationReason === null) {
    const moreIncoming = model.edges.filter((e) => e.target === current.id);
    if (moreIncoming.length > 0) truncationReason = "too deep";
  }

  const tokens: string[] = [];
  for (const nid of [...chain, targetNodeId]) {
    const n = nodeById.get(nid);
    if (!n) continue;
    tokens.push(nodeDisplay(n));
    const dp = dpsDisplay(n);
    if (dp) tokens.push(dp);
  }
  let out = tokens.join(" → ");
  if (truncationReason) out += ` [truncated: ${truncationReason}]`;
  return out;
}
