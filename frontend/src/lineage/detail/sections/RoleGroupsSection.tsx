// frontend/src/lineage/detail/sections/RoleGroupsSection.tsx
//
// V1.6.5 — wires the pure RoleGroups view into the node detail drawer for
// model nodes (Plan §8 / Phase D3). Pulls the var->model role edges off the
// current GraphViewModel (edges now carry `op` + `params`), groups them by
// role, and renders them in canonical order. Also stamps the model-node
// role tag per spec §5 back-compat:
//   - run has NO role edges at all          -> "roles: legacy_unspecified"
//   - this model's only RHS group is the
//     explanatory_unspecified fallback      -> "roles: unspecified"

import { useLineage } from "../../LineageContext";
import { groupVariablesByRole } from "../../../workbench/RunSnapshotAdapter";
import { ROLE_OF_EDGE_OP } from "../../roles";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { RoleGroups } from "./RoleGroups";

/** Role groups that count as a "specified" RHS (i.e. not the fallback). */
const RHS_SPECIFIED = new Set([
  "focal",
  "treatment",
  "covariates",
  "instruments",
  "exposure",
]);

export function RoleGroupsSection({ node }: { node: GraphViewNode }) {
  const { model } = useLineage();

  const roleEdges = model.edges
    .filter((e) => e.op && ROLE_OF_EDGE_OP[e.op])
    .map((e) => ({
      source: e.source,
      target: e.target,
      op: e.op as string,
      params: e.params,
    }));

  const groups = groupVariablesByRole(roleEdges, node.id);
  if (groups.length === 0) return null;

  // Back-compat tag (spec §5). `legacy_unspecified` would mean the whole
  // run predates the role layer — but if we got here we *have* role edges,
  // so the only tag we can surface from the graph is `unspecified` when the
  // sole RHS group is the explanatory fallback.
  const rhsRoles = groups
    .map((g) => g.role)
    .filter((r) => RHS_SPECIFIED.has(r) || r === "explanatory_unspecified");
  const unspecified =
    rhsRoles.length > 0 && rhsRoles.every((r) => r === "explanatory_unspecified");

  return (
    <section
      aria-label="Variables by role"
      data-testid="role-groups-section"
      style={{ marginTop: 18 }}
    >
      <div
        className="ln-section-label"
        style={{ marginBottom: 6, display: "flex", alignItems: "center" }}
      >
        <span>Variables by role</span>
        {unspecified && (
          <span
            data-testid="role-tag"
            style={{
              marginLeft: "auto",
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              color: "var(--label-tertiary)",
            }}
          >
            roles: unspecified
          </span>
        )}
      </div>
      <RoleGroups groups={groups} />
    </section>
  );
}
