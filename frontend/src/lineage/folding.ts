// frontend/src/lineage/folding.ts
//
// Cluster folding for the canvas PROJECTION (V1.5.0 variables; v1.7 G1 data
// operations). Consumes GraphViewNode[] post-T5.5 signature swap (was raw
// LineageNode[] in V1.4.1).
//
// G1 principle: fold the projection, never the lineage. A source node with a
// dozen typed data operations stacks a dozen sibling cards off-screen, but each
// of those children is its own Operation Record, artifact and Merkle identity —
// merging them in the durable graph would break per-operation verification and
// source-immutability. So the canvas folds same-parent siblings into one card
// while the underlying nodes stay untouched and individually reachable.

import type { GraphViewNode } from "./api/graphViewTypes";

const FOLD_THRESHOLD = 3; // strictly more than 3 → fold

export type GroupVariant = "cleaned" | "dropped" | "data_operation";

export interface GroupNode {
  id: string;
  display_label: string;
  parentStageId: string;
  member_ids: string[];
  members: GraphViewNode[];
  expanded: boolean;
  /** Discriminator: variable cluster ('cleaned'/'dropped') vs data-op children. */
  variant: GroupVariant;
}

function variantOf(id: string): "cleaned" | "dropped" | null {
  if (id.endsWith(":dropped")) return "dropped";
  if (id.endsWith(":cleaned")) return "cleaned";
  return null;
}

/** Backend node id — the view id may be a forest key (`<hash>::<node_id>`). */
function backendNodeId(node: GraphViewNode): string {
  const raw = node.raw as { id?: unknown } | null;
  return raw && typeof raw.id === "string" ? raw.id : node.id;
}

/** Node id prefixes minted by typed data operations that derive a child node. */
const DATA_OPERATION_CHILD_PREFIXES = ["data-cast:", "data-casts:", "code-exec:"];

/** Children materialized by a typed data operation (cast, batch cast, code). */
function isDataOperationChild(node: GraphViewNode): boolean {
  if (node.kind !== "dataset_stage") return false;
  const id = backendNodeId(node);
  return DATA_OPERATION_CHILD_PREFIXES.some((prefix) => id.startsWith(prefix));
}

export function foldNodeClusters(
  nodes: GraphViewNode[],
  expanded: Set<string>,
): { kept: GraphViewNode[]; groups: GroupNode[] } {
  const varBuckets = new Map<
    string,
    { variant: "cleaned" | "dropped"; parent: string; nodes: GraphViewNode[] }
  >();
  const opBuckets = new Map<string, { parent: string; nodes: GraphViewNode[] }>();
  const other: GraphViewNode[] = [];

  for (const n of nodes) {
    if (n.kind === "variable" && n.parentStageId) {
      const variant = variantOf(n.id);
      if (variant) {
        const key = `${variant}|${n.parentStageId}`;
        let bucket = varBuckets.get(key);
        if (!bucket) {
          bucket = { variant, parent: n.parentStageId, nodes: [] };
          varBuckets.set(key, bucket);
        }
        bucket.nodes.push(n);
        continue;
      }
      other.push(n);
      continue;
    }
    if (isDataOperationChild(n) && n.parentStageId) {
      let bucket = opBuckets.get(n.parentStageId);
      if (!bucket) {
        bucket = { parent: n.parentStageId, nodes: [] };
        opBuckets.set(n.parentStageId, bucket);
      }
      bucket.nodes.push(n);
      continue;
    }
    other.push(n);
  }

  const kept: GraphViewNode[] = [...other];
  const groups: GroupNode[] = [];

  for (const { variant, parent, nodes: bucket } of varBuckets.values()) {
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

  for (const { parent, nodes: bucket } of opBuckets.values()) {
    if (bucket.length <= FOLD_THRESHOLD) {
      kept.push(...bucket);
      continue;
    }
    const id = `group:data-operations:${parent}`;
    groups.push({
      id,
      display_label: `Data operations (${bucket.length})`,
      parentStageId: parent,
      member_ids: bucket.map((n) => n.id),
      members: bucket,
      expanded: expanded.has(id),
      variant: "data_operation",
    });
  }

  return { kept, groups };
}
