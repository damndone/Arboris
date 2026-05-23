// frontend/src/lineage/api/nodeRef.ts
//
// Tiny helper to centralise "how to identify a node". V1.5.0: `id === nodeKey`.
// V2.0: backend UUID populates `id`, logical key populates `nodeKey`; consumers
// using these helpers do not need to change.
//
// Spec §11.3.

import type { GraphViewNode } from "./graphViewTypes";

export interface NodeRef {
  id: string;
  nodeKey: string;
}

export function refOf(node: GraphViewNode): NodeRef {
  return { id: node.id, nodeKey: node.nodeKey };
}

export function refEquals(
  a: NodeRef | null | undefined,
  b: NodeRef | null | undefined,
): boolean {
  if (!a || !b) return false;
  return a.id === b.id;
}
