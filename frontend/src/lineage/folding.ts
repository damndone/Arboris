import type { LineageNode } from "./types";

const FOLD_THRESHOLD = 3; // strictly more than 3 → fold

export interface GroupNode {
  id: string;
  display_label: string;
  parent_stage_id: string;
  member_ids: string[];
  /** Discriminator: 'cleaned' (kept) vs 'dropped'. Drives group title prefix. */
  variant: "cleaned" | "dropped";
}

function variantOf(id: string): "cleaned" | "dropped" | null {
  if (id.endsWith(":dropped")) return "dropped";
  if (id.endsWith(":cleaned")) return "cleaned";
  return null;
}

export function foldVariableClusters(
  nodes: LineageNode[],
  expanded: Set<string>,
): { kept: LineageNode[]; groups: GroupNode[] } {
  const buckets = new Map<
    string,
    { variant: "cleaned" | "dropped"; parent: string; nodes: LineageNode[] }
  >();
  const other: LineageNode[] = [];

  for (const n of nodes) {
    if (n.kind !== "variable" || !n.parent_stage_id) {
      other.push(n);
      continue;
    }
    const variant = variantOf(n.id);
    if (!variant) {
      other.push(n);
      continue;
    }
    const key = `${variant}|${n.parent_stage_id}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { variant, parent: n.parent_stage_id, nodes: [] };
      buckets.set(key, bucket);
    }
    bucket.nodes.push(n);
  }

  const kept: LineageNode[] = [...other];
  const groups: GroupNode[] = [];

  for (const { variant, parent, nodes: bucket } of buckets.values()) {
    if (bucket.length <= FOLD_THRESHOLD) {
      kept.push(...bucket);
      continue;
    }
    const id = `group:${variant === "cleaned" ? "variables" : "dropped-variables"}:${parent}`;
    if (expanded.has(id)) {
      kept.push(...bucket);
    } else {
      groups.push({
        id,
        display_label: `${variant === "cleaned" ? "Variables" : "Dropped variables"} (${bucket.length})`,
        parent_stage_id: parent,
        member_ids: bucket.map((n) => n.id),
        variant,
      });
    }
  }
  return { kept, groups };
}
