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

import { useEffect, useMemo, useState } from "react";
import { useCompareOptional } from "../../lineage/compare/CompareContext";
import { GraphCanvas } from "../../lineage/graph/GraphCanvas";
import { useLayoutMode } from "../../lineage/graph/useLayoutMode";
import { useLineage } from "../../lineage/LineageContext";
import { useWorkbenchOptional } from "../WorkbenchStateProvider";
import { useForest } from "../ForestContext";
import { buildRunSnapshot } from "../RunSnapshotAdapter";

export function GraphView() {
  const { model, selectedKey, select } = useLineage();
  const forest = useForest();
  // useWorkbenchOptional() lets GraphView work both inside the new
  // WorkbenchRouteContainer AND inside V1.5.0/1.5.1 bare-mount tests.
  // When the provider is absent, focus/search overlay degrade to none
  // but selected/related/dim keeps working.
  const wb = useWorkbenchOptional();

  // V1.5.2 P6 — focus + upstream + search highlight derivation.
  const snapshot = useMemo(() => buildRunSnapshot(model), [model]);
  const focusKey = wb?.state.focusKey ?? null;
  const searchQuery = wb?.state.searchQuery ?? "";
  // F5: the current ⌘K cursor result, highlighted above the other hits.
  const searchCursorKey = wb?.state.searchCursorKey ?? null;
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

  // T6.12 legacy stage hint dismissal.
  //
  // F8 (V1.5.3): unify the sessionStorage namespace on `workbench:`.
  // V1.5.0 wrote `lineage:legacy-hint-dismissed:<runId>`; every other
  // key in the app already uses the `workbench:` prefix (see
  // useSessionByRunId / useLayoutMode / ThemeProvider). We read the new
  // key, and on first access migrate a pre-existing `lineage:` value
  // forward (then delete it) so a user who dismissed the hint under
  // V1.5.0/1.5.2 doesn't see it resurrected after upgrading.
  const dismissalKey = `workbench:legacy-hint-dismissed:${model.runId}`;
  const legacyDismissalKey = `lineage:legacy-hint-dismissed:${model.runId}`;
  const [legacyHintDismissed, setLegacyHintDismissed] = useState<boolean>(
    () => {
      try {
        if (sessionStorage.getItem(dismissalKey) === "1") return true;
        // One-time migration from the V1.5.0-era namespace.
        if (sessionStorage.getItem(legacyDismissalKey) === "1") {
          sessionStorage.setItem(dismissalKey, "1");
          sessionStorage.removeItem(legacyDismissalKey);
          return true;
        }
        return false;
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

  // v1.6.11 B-2 — compare pick mode: while picking, the next node click is the
  // comparison target (selection unchanged). Esc cancels.
  const compare = useCompareOptional();
  const picking = compare?.pickingFromKey ?? null;
  const handleSelect = (nodeKey: string) => {
    if (compare?.handleCanvasSelect(nodeKey)) return;
    select(nodeKey);
  };
  const handlePaneClick = () => {
    if (picking !== null) {
      compare?.cancelPick();
      return;
    }
    select(null);
  };
  useEffect(() => {
    if (picking === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") compare?.cancelPick();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [picking, compare]);

  const handleExpandGroup = (gid: string) => {
    setExpandedGroups((s) => {
      const next = new Set(s);
      if (next.has(gid)) next.delete(gid);
      else next.add(gid);
      return next;
    });
  };

  if (model.legacy) return <LegacyBanner />;

  // v1.6.1 — the lineage graph IS the forest. In forest mode `model` is already the
  // cross-run projection, so we render the SAME full-featured GraphCanvas (layout modes,
  // search, context menu, hover, variable folding all come for free) and only add a
  // head-chips bar on top for cross-run version switching / rollback. Picking a head
  // focuses its lineage (active-head highlight via the existing focus mechanism).
  const onPickHead = (runId: string, headNodeKey: string | null) => {
    if (!forest) return;
    forest.setActiveRunId(runId);
    if (headNodeKey && wb) wb.dispatch.setFocusOnly(headNodeKey);
  };

  return (
    <div
      className="lineage-root"
      data-testid="graph-workbench"
      data-view={forest ? "forest" : "graph"}
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
      }}
    >
      {showLegacyHint && <LegacyStageHint onDismiss={dismissLegacyHint} />}
      {forest && (
        <ForestHeadBar
          forest={forest.forest}
          activeRunId={forest.activeRunId}
          onPickHead={onPickHead}
        />
      )}
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {picking !== null && (
          <div
            data-testid="compare-pick-banner"
            role="status"
            style={{
              position: "absolute",
              top: 10,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 8,
              padding: "6px 14px",
              borderRadius: 999,
              fontSize: 12,
              background: "var(--fill-secondary, rgba(0,0,0,0.75))",
              color: "var(--label-primary, #fff)",
              boxShadow: "0 2px 10px rgba(0,0,0,0.25)",
              display: "flex",
              gap: 10,
              alignItems: "center",
            }}
          >
            <span>
              Compare mode — click the node to compare with{" "}
              <strong>{nodeIndex.get(picking)?.title ?? picking}</strong>
            </span>
            <button type="button" onClick={() => compare?.cancelPick()}>
              Cancel (Esc)
            </button>
          </div>
        )}
        <GraphCanvas
          model={model}
          selectedNodeId={effectiveSelectedKey}
          expandedGroups={expandedGroups}
          onSelect={handleSelect}
          onPaneClick={handlePaneClick}
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
          searchCursorKey={searchCursorKey}
        />
      </div>
    </div>
  );
}

function ForestHeadBar({
  forest,
  activeRunId,
  onPickHead,
}: {
  forest: import("../../lineage/api/graphViewTypes").ForestViewModel;
  activeRunId: string;
  onPickHead: (runId: string, headNodeKey: string | null) => void;
}) {
  if (forest.heads.length <= 1) return null; // no versions to switch between
  const keyForHead = (headNodeHash: string | null) =>
    forest.nodes.find((n) => n.nodeHash === headNodeHash)?.id ?? null;
  return (
    <div
      data-testid="forest-heads"
      role="group"
      aria-label="Run versions (active head)"
      style={{
        display: "flex",
        gap: 6,
        flexWrap: "wrap",
        alignItems: "center",
        padding: "6px 12px",
        borderBottom: "1px solid var(--separator, #2e2e30)",
      }}
    >
      <span style={{ fontSize: 11, color: "var(--label-tertiary)", marginRight: 4 }}>
        Versions:
      </span>
      {forest.heads.map((h) => {
        const isActive = h.runId === activeRunId;
        return (
          <button
            key={h.runId}
            type="button"
            data-testid={`forest-head-${h.runId}`}
            aria-pressed={isActive}
            title={h.rerunOf ? `rerun of ${h.rerunOf}` : "original run"}
            onClick={() => onPickHead(h.runId, keyForHead(h.headNodeHash))}
            style={{
              fontSize: 11,
              fontFamily: "var(--font-mono, monospace)",
              padding: "4px 9px",
              borderRadius: 6,
              cursor: "pointer",
              border: isActive
                ? "1px solid var(--tint, #0a84ff)"
                : "1px solid var(--separator, #2e2e30)",
              background: isActive ? "var(--tint, #0a84ff)" : "transparent",
              color: isActive ? "#fff" : "var(--label-secondary)",
            }}
          >
            {h.rerunOf ? "↳ " : ""}
            {h.runId.slice(-8)}
          </button>
        );
      })}
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
