// frontend/src/workbench/views/GraphView.tsx
//
// V1.5.2 P8 — slimmed to a true "view" per plan §2 layout.
//
// What GraphView owns now:
//   - the React Flow canvas (GraphCanvas)
//   - view-local layout choice (sessionStorage via useLayoutMode)
//   - expandedGroups (canvas-level fold/expand state)
//   - the legacy-banner branch + legacy stage hint
//   - focus / search-hit derivation (consumes useWorkbench)
//
// What MOVED OUT to WorkbenchRouteContainer (plan §2 final layout):
//   - RunHistoryRail        — shared across all views (Table / Pipeline too)
//   - DetailDrawer          — drawer follows `selected` regardless of view
//   - RawJsonModal + ⌘J     — modal is selection-scoped, not canvas-scoped
//   - Escape → select(null) — same reason
//
// useLineage() still drives selection because LineageContext is the
// V1.5.x source of truth for `selectedKey + select`; WorkbenchStateProvider
// reads URL params disjoint from the lineage tab params, so the two
// stay consistent.

import { useMemo, useState } from "react";
import { GraphCanvas } from "../../lineage/graph/GraphCanvas";
import { useLayoutMode } from "../../lineage/graph/useLayoutMode";
import { useLineage } from "../../lineage/LineageContext";
import { useWorkbenchOptional } from "../WorkbenchStateProvider";
import { buildRunSnapshot } from "../RunSnapshotAdapter";

export function GraphView() {
  const { model, selectedKey, select } = useLineage();
  // useWorkbenchOptional() lets GraphView work both inside the new
  // WorkbenchRouteContainer AND inside V1.5.0/1.5.1 bare-mount tests.
  // When the provider is absent, focus/search overlay degrade to none
  // but selected/related/dim keeps working.
  const wb = useWorkbenchOptional();

  // V1.5.2 P6 — focus + upstream + search highlight derivation.
  const snapshot = useMemo(() => buildRunSnapshot(model), [model]);
  const focusKey = wb?.state.focusKey ?? null;
  const searchQuery = wb?.state.searchQuery ?? "";
  const focusUpstreamKeys = useMemo<ReadonlySet<string> | undefined>(() => {
    if (focusKey === null) return undefined;
    return new Set(snapshot.upstreamOf(focusKey).map((n) => n.nodeKey));
  }, [snapshot, focusKey]);
  const searchHitKeys = useMemo<ReadonlySet<string> | undefined>(() => {
    if (!searchQuery) return undefined;
    const q = searchQuery.toLowerCase();
    const hits = new Set<string>();
    for (const item of snapshot.searchIndex) {
      if (item.haystack.includes(q)) hits.add(item.nodeKey);
    }
    return hits;
  }, [snapshot, searchQuery]);

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const { layout, setLayout } = useLayoutMode(model.runId);

  // T6.12 legacy stage hint — V1.5.0 behaviour preserved exactly.
  const dismissalKey = `lineage:legacy-hint-dismissed:${model.runId}`;
  const [legacyHintDismissed, setLegacyHintDismissed] = useState<boolean>(
    () => {
      try {
        return sessionStorage.getItem(dismissalKey) === "1";
      } catch {
        return false;
      }
    },
  );
  const dismissLegacyHint = () => {
    setLegacyHintDismissed(true);
    try {
      sessionStorage.setItem(dismissalKey, "1");
    } catch {
      /* fall back to per-mount dismissal */
    }
  };
  const unknownStageRatio = useMemo(() => {
    if (model.nodes.length === 0) return 0;
    const unknown = model.nodes.filter((n) => n.stage === "unknown").length;
    return unknown / model.nodes.length;
  }, [model.nodes]);
  const showLegacyHint = !legacyHintDismissed && unknownStageRatio >= 0.5;

  // Coerce selectedKey to null when it doesn't point at a real node.
  // [REV-3 #3] cross-run URL leak guard.
  const nodeIndex = useMemo(
    () => new Map(model.nodes.map((n) => [n.id, n])),
    [model.nodes],
  );
  const effectiveSelectedKey =
    selectedKey !== null && nodeIndex.has(selectedKey) ? selectedKey : null;

  const handleExpandGroup = (gid: string) => {
    setExpandedGroups((s) => {
      const next = new Set(s);
      if (next.has(gid)) next.delete(gid);
      else next.add(gid);
      return next;
    });
  };

  if (model.legacy) return <LegacyBanner />;

  return (
    <div
      className="lineage-root"
      data-testid="graph-workbench"
      data-view="graph"
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
      }}
    >
      {showLegacyHint && <LegacyStageHint onDismiss={dismissLegacyHint} />}
      <div style={{ flex: 1, minHeight: 0 }}>
        <GraphCanvas
          model={model}
          selectedNodeId={effectiveSelectedKey}
          expandedGroups={expandedGroups}
          onSelect={select}
          onExpandGroup={handleExpandGroup}
          layout={layout}
          onLayoutChange={setLayout}
          onNodeContextMenu={
            wb
              ? (nodeId, x, y) =>
                  wb.dispatch.openContextMenu({ nodeKey: nodeId, x, y })
              : undefined
          }
          focusNodeKey={focusKey}
          focusUpstreamKeys={focusUpstreamKeys}
          searchHitKeys={searchHitKeys}
        />
      </div>
    </div>
  );
}

function LegacyStageHint({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="legacy-stage-hint"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 14px",
        background: "var(--orange-bg)",
        borderBottom: "1px solid var(--separator)",
        fontSize: 12,
        color: "var(--label-secondary)",
      }}
    >
      <span>
        This run predates stage tagging. Re-run to populate stages.
      </span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss legacy stage hint"
        style={{
          marginLeft: "auto",
          border: 0,
          background: "transparent",
          color: "var(--label-tertiary)",
          cursor: "pointer",
          fontSize: 12,
          padding: "2px 6px",
        }}
      >
        Dismiss
      </button>
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
