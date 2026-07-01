// frontend/src/lineage/detail/sections/RoleGroups.tsx
//
// V1.6.5 — Variable role groups (Plan §8 / Phase D3). Pure presentational
// component: renders one labelled section per role group, each column as a
// chip. Roles live on the var->model *edge*, so a single column can show up
// under several groups (e.g. focal + cluster). Dashed treatment for the
// structural inference/panel roles (unit / time / cluster) mirrors the
// canvas edge styling. Dropped columns keep their pre-drop role but are
// marked so the reader sees they were silently removed from the fit.

import { roleLabel, DASHED_ROLES } from "../../roles";
import type { RoleGroup } from "../../../workbench/RunSnapshotAdapter";

export function RoleGroups({ groups }: { groups: RoleGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <div data-testid="role-groups">
      {groups.map((g) => {
        const dashed = DASHED_ROLES.has(g.role);
        return (
          <div
            key={g.role}
            data-role={g.role}
            data-edge={dashed ? "dashed" : undefined}
            style={{ marginBottom: 10 }}
          >
            <div
              className="ln-section-label"
              style={{
                marginBottom: 4,
                fontSize: 11,
                color: "var(--label-secondary)",
              }}
            >
              {roleLabel(g.role)}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {g.columns.map((col) => {
                const isDropped = g.dropped.has(col);
                return (
                  <span
                    key={col}
                    data-dropped={isDropped ? "true" : undefined}
                    title={isDropped ? `${col} (dropped from fit)` : col}
                    style={{
                      padding: "2px 8px",
                      borderRadius: 6,
                      border: dashed
                        ? "1px dashed var(--separator)"
                        : "1px solid var(--separator)",
                      background: "var(--bg-card-2, transparent)",
                      color: isDropped
                        ? "var(--label-tertiary)"
                        : "var(--label)",
                      textDecoration: isDropped ? "line-through" : undefined,
                      fontSize: 11,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {col}
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
