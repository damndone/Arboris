// frontend/src/lineage/folding.ts
//
// Variable-cluster folding (V1.5.0). Consumes GraphViewNode[] post-T5.5
// signature swap (was raw LineageNode[] in V1.4.1).

import type { GraphViewNode } from "./api/graphViewTypes";

const FOLD_THRESHOLD = 3; // strictly more than 3 → fold

export interface GroupNode {
  id: string;
  display_label: string;
  parentStageId: string;
  member_ids: string[];
  members: GraphViewNode[];
  expanded: boolean;
  /** Discriminator: 'cleaned' (kept) vs 'dropped'. Drives group title prefix. */
  variant: "cleaned" | "dropped";
}

function variantOf(id: string): "cleaned" | "dropped" | null {
  if (id.endsWith(":dropped")) return "dropped";
  if (id.endsWith(":cleaned")) return "cleaned";
  return null;
}

export function foldVariableClusters(
  nodes: GraphViewNode[],
  expanded: Set<string>,
): { kept: GraphViewNode[]; groups: GroupNode[] } {
  const buckets = new Map<
    string,
    { variant: "cleaned" | "dropped"; parent: string; nodes: GraphViewNode[] }
  >();
  const other: GraphViewNode[] = [];

  for (const n of nodes) {
    if (n.kind !== "variable" || !n.parentStageId) {
      other.push(n);
      continue;
    }
    const variant = variantOf(n.id);
    if (!variant) {
      other.push(n);
      continue;
    }
    const key = `${variant}|${n.parentStageId}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { variant, parent: n.parentStageId, nodes: [] };
      buckets.set(key, bucket);
    }
    bucket.nodes.push(n);
  }

  const kept: GraphViewNode[] = [...other];
  const groups: GroupNode[] = [];

  for (const { variant, parent, nodes: bucket } of buckets.values()) {
    if (bucket.length <= FOLD_THRESHOLD) {
      kept.push(...bucket);
      continue;
    }
    const id = `group:${variant === "cleaned" ? "variables" : "dropped-variables"}:${parent}`;
    groups.push({
      id,
      display_label: `${variant === "cleaned" ? "Variables" : "Dropped variables"} (${bucket.length})`,
      parentStageId: parent,
      member_ids: bucket.map((n) => n.id),
      members: bucket,
      expanded: expanded.has(id),
      variant,
    });
  }
  return { kept, groups };
}
