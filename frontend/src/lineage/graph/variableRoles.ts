// frontend/src/lineage/graph/variableRoles.ts
//
// v1.6.5 — derive each variable node's role(s) for a given model from the
// role-bearing var→model edges. Roles live on edges, not nodes, so a column
// can hold >1 role (e.g. Unit + Cluster) and the canvas badge shows the
// primary (first by canonical group order).

import { ROLE_OF_EDGE_OP, ROLE_GROUP_ORDER, type Role } from "../roles";
import type { GraphViewEdge } from "../api/graphViewTypes";

const ORDER: Role[] = [...ROLE_GROUP_ORDER, "explanatory_unspecified"];

/** Map each variable node id to the role(s) it holds for `modelId`,
 *  derived from its role-bearing var→model edges, in canonical order. */
export function rolesByVariable(
  edges: GraphViewEdge[],
  modelId: string,
): Map<string, Role[]> {
  const out = new Map<string, Role[]>();
  for (const e of edges) {
    if (e.target !== modelId || !e.op) continue;
    const role = ROLE_OF_EDGE_OP[e.op];
    if (!role) continue;
    const list = out.get(e.source) ?? [];
    if (!list.includes(role)) list.push(role);
    out.set(e.source, list);
  }
  for (const [k, v] of out) {
    out.set(k, [...v].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)));
  }
  return out;
}

/** The role shown as the node's badge: first by canonical group order. */
export function primaryRole(roles: Role[]): Role {
  return [...roles].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))[0];
}
