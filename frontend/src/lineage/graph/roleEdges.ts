// frontend/src/lineage/graph/roleEdges.ts
//
// v1.6.5 — canvas styling for role-bearing var→model edges, plus suppression
// of the legacy aggregate `stage→model` fit edge that would otherwise draw a
// redundant parallel path next to the role edges (problem P1).

import { ROLE_OF_EDGE_OP, DASHED_ROLES, roleColorVar } from "../roles";
import type { GraphViewEdge } from "../api/graphViewTypes";

export function isRoleOp(op: string | undefined): boolean {
  return Boolean(op && ROLE_OF_EDGE_OP[op]);
}

/** React Flow edge `style` for a role-bearing edge. Solid for substantive /
 *  identification / exposure roles, dashed for the inference/panel roles
 *  (unit/time/cluster), coloured by role. */
export function roleEdgeStyle(op: string): {
  stroke?: string;
  strokeDasharray?: string;
} {
  const role = ROLE_OF_EDGE_OP[op];
  if (!role) return {};
  const style: { stroke?: string; strokeDasharray?: string } = {
    stroke: roleColorVar(role),
  };
  if (DASHED_ROLES.has(role)) style.strokeDasharray = "4 4";
  return style;
}

/** Hide the legacy aggregate `stage→model` fit edge for any model that also
 *  has role edges feeding it — the role edges now carry "variables enter the
 *  model", so the aggregate edge would draw a redundant parallel path (P1).
 *  Models with no role edges (legacy runs) keep their fit edge. */
export function suppressAggregateEdges(edges: GraphViewEdge[]): GraphViewEdge[] {
  const modelsWithRoles = new Set<string>();
  for (const e of edges) if (isRoleOp(e.op)) modelsWithRoles.add(e.target);
  return edges.filter((e) => {
    const isAggregateIntoRoleModel =
      !isRoleOp(e.op) &&
      modelsWithRoles.has(e.target) &&
      e.source.startsWith("stage:");
    return !isAggregateIntoRoleModel;
  });
}
