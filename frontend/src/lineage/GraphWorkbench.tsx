// frontend/src/lineage/GraphWorkbench.tsx
//
// V1.5.0 lineage workbench (Step 5, T5.6).
//
// Mounts GraphCanvas inside the LineageContext consumer and reserves a
// right-side slot for the DetailDrawer. The drawer itself arrives in
// Step 6 — this file currently renders a placeholder DrawerSlot when a
// node is selected so the layout grid is observable in tests.
//
// expandedGroups state lives here (not in the container) because it is
// graph-render local — V1.5.1 may persist it to URL or context, but
// today it's transient component state.

import { useState } from "react";
import { GraphCanvas } from "./GraphCanvas";
import { useLineage } from "./LineageContext";

export function GraphWorkbench() {
  const { model, selectedKey, select } = useLineage();
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const handleExpandGroup = (gid: string) => {
    setExpandedGroups((s) => {
      const next = new Set(s);
      if (next.has(gid)) next.delete(gid);
      else next.add(gid);
      return next;
    });
  };

  // V1.4.1 legacy banner — model.legacy is true for pre-V1.4 runs that
  // never recorded lineage. Surface the same copy LineageTab used.
  if (model.legacy) return <LegacyBanner />;

  return (
    <div
      className="lineage-root"
      style={{ display: "flex", gap: 0, minHeight: 600 }}
      data-testid="graph-workbench"
    >
      <div style={{ flex: 1 }}>
        <GraphCanvas
          model={model}
          selectedNodeId={selectedKey}
          expandedGroups={expandedGroups}
          onSelect={select}
          onExpandGroup={handleExpandGroup}
        />
      </div>
      {selectedKey !== null && <DrawerSlot nodeId={selectedKey} />}
    </div>
  );
}

/**
 * Placeholder until Step 6 introduces DetailDrawer. Keeps the workbench
 * layout testable end-to-end without forward-declaring the drawer API.
 */
function DrawerSlot({ nodeId }: { nodeId: string }) {
  return (
    <div
      data-testid="drawer-slot"
      style={{
        width: 460,
        borderLeft: "1px solid var(--separator)",
        padding: 24,
        color: "var(--label-secondary)",
      }}
    >
      Detail drawer for {nodeId} — arriving in Step 6.
    </div>
  );
}

function LegacyBanner() {
  return (
    <div
      className="lineage-root"
      style={{
        padding: 24,
        textAlign: "center",
        color: "var(--label-secondary)",
      }}
      data-testid="legacy-banner"
    >
      <div style={{ fontSize: 16, color: "var(--label)", marginBottom: 8 }}>
        No lineage data for this run
      </div>
      <div>
        This run predates V1.4. Lineage tracking became available with V1.4.0.
      </div>
    </div>
  );
}
