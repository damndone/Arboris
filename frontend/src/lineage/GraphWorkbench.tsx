// frontend/src/lineage/GraphWorkbench.tsx
//
// V1.5.0 lineage workbench (Step 5, T5.6 + Step 6, T6.11).
//
// Mounts GraphCanvas inside the LineageContext consumer. When a node is
// selected, the right rail mounts DetailDrawer (Step 6, T6.11 swap from
// the T5.6 DrawerSlot placeholder). RawJsonModal is mounted at workbench
// root and controlled by ⌘J via useGraphKeyboard.
//
// expandedGroups state lives here (not in the container) because it is
// graph-render local — V1.5.1 may persist it to URL or context, but
// today it's transient component state.

import { useMemo, useState } from "react";
import { GraphCanvas } from "./GraphCanvas";
import { useLineage } from "./LineageContext";
import { useGraphKeyboard } from "./hooks/useGraphKeyboard";
import { DetailDrawer } from "./detail/DetailDrawer";
import { RawJsonModal } from "./modals/RawJsonModal";

export function GraphWorkbench() {
  const { model, selectedKey, select } = useLineage();
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [rawJsonOpen, setRawJsonOpen] = useState(false);

  // Coerce selectedKey to null when it doesn't point at a real node in the
  // current model. Covers cross-run URL leak (/runs/A?node=x → /runs/B
  // would otherwise mount an orphan drawer) and any other stale URL state.
  // [REV-3 #3 — Step 5 adversarial review]
  const nodeIndex = useMemo(
    () => new Map(model.nodes.map((n) => [n.id, n])),
    [model.nodes],
  );
  const effectiveSelectedKey =
    selectedKey !== null && nodeIndex.has(selectedKey) ? selectedKey : null;
  const selectedNode =
    effectiveSelectedKey !== null
      ? (nodeIndex.get(effectiveSelectedKey) ?? null)
      : null;

  useGraphKeyboard({
    onToggleRawJson: () => {
      // Only open the modal when we actually have a node — otherwise it's
      // a no-op rather than rendering an empty modal.
      if (selectedNode === null && !rawJsonOpen) return;
      setRawJsonOpen((v) => !v);
    },
    onEscape: () => {
      // Modal owns its own Escape handler (capture phase, stops
      // propagation) so this only fires when the modal is closed.
      select(null);
    },
    onCmdK: () => {
      /* parent search palette — wired in V1.5.x */
    },
  });

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
          selectedNodeId={effectiveSelectedKey}
          expandedGroups={expandedGroups}
          onSelect={select}
          onExpandGroup={handleExpandGroup}
        />
      </div>
      {selectedNode !== null && (
        <DetailDrawer node={selectedNode} onClose={() => select(null)} />
      )}
      <RawJsonModal
        open={rawJsonOpen}
        onClose={() => setRawJsonOpen(false)}
        node={selectedNode}
      />
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
