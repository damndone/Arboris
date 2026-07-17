// frontend/src/lineage/detail/DetailDrawer.tsx
//
// V1.5.0 DetailDrawer (Step 6, T6.2).
//
// Renders the dialog chrome (DetailHeader — always, per spec §8.2) followed
// by the registered sections in `order` after each one's `shouldRender(node)`
// filter. The dialog's accessibility skeleton (role + aria-labelledby) is
// invariant — section changes never touch it.
//
// Node resolution:
//   - If `node` prop is provided, use it directly.
//   - Otherwise, read selectedKey from LineageContext and look up the
//     matching GraphViewNode in model.nodes. If neither yields a node,
//     the drawer renders nothing (caller is expected to gate the mount).
//
// Spec §8.2.

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { DetailHeader, DETAIL_HEADER_TITLE_ID } from "../header/DetailHeader";
import { useLineage } from "../LineageContext";
import type { GraphViewNode } from "../api/graphViewTypes";
import { DetailDrawerTabs } from "./DetailDrawerTabs";
import { NodeOperationContextProvider } from "./NodeOperationContextProvider";
import { sectionRegistry } from "./sections/sectionRegistry";

interface DetailDrawerProps {
  /** Optional explicit node; falls back to LineageContext's selectedKey. */
  node?: GraphViewNode;
  onClose: () => void;
  /** Explicit project root for actions that create drafts from slug routes. */
  projectRoot?: string;
  /**
   * Forwarded to DetailHeader. When set, the header mounts NodeActionMenu
   * and uses this callback for the "View Raw JSON" item. Wired by
   * GraphWorkbench to open RawJsonModal.
   */
  onShowJson?: () => void;
}

const MIN_DRAWER_WIDTH = 320;
const DEFAULT_DRAWER_WIDTH = 460;
const MAX_DRAWER_WIDTH = 720;

function clampDrawerWidth(width: number): number {
  if (!Number.isFinite(width)) return DEFAULT_DRAWER_WIDTH;
  return Math.min(MAX_DRAWER_WIDTH, Math.max(MIN_DRAWER_WIDTH, Math.round(width)));
}

function readDrawerWidth(storageKey: string): number {
  const raw = sessionStorage.getItem(storageKey);
  return raw === null ? DEFAULT_DRAWER_WIDTH : clampDrawerWidth(Number(raw));
}

export function DetailDrawer({
  node: nodeProp,
  onClose,
  projectRoot,
  onShowJson,
}: DetailDrawerProps) {
  const {
    model,
    selectedKey,
    tabs = [],
    activeTabId = selectedKey,
    setActiveTab,
    closeTab,
    lastEvictedTabId,
  } = useLineage();

  // Either the caller passes a node, or we resolve it from context.
  const resolved: GraphViewNode | null = useMemo(() => {
    if (nodeProp) return nodeProp;
    if (selectedKey === null) return null;
    return model.nodes.find((n) => n.id === selectedKey) ?? null;
  }, [nodeProp, model.nodes, selectedKey]);

  // Pre-sort once so registry insertion order doesn't matter at runtime.
  const visibleSections = useMemo(() => {
    if (resolved === null) return [];
    return sectionRegistry
      .filter((s) => s.shouldRender(resolved))
      .sort((a, b) => a.order - b.order);
  }, [resolved]);

  const widthStorageKey = `workbench:detailDrawerWidth:${projectRoot ?? "default"}`;
  const [drawerWidth, setDrawerWidth] = useState(() => readDrawerWidth(widthStorageKey));
  const dragStart = useRef<{ x: number; width: number; pointerId: number } | null>(null);

  useEffect(() => {
    setDrawerWidth(readDrawerWidth(widthStorageKey));
  }, [widthStorageKey]);

  const commitDrawerWidth = useCallback((nextWidth: number) => {
    const clamped = clampDrawerWidth(nextWidth);
    setDrawerWidth(clamped);
    sessionStorage.setItem(widthStorageKey, String(clamped));
  }, [widthStorageKey]);

  const onDrawerResizeStart = useCallback((event: PointerEvent<HTMLDivElement>) => {
    dragStart.current = {
      x: event.clientX,
      width: drawerWidth,
      pointerId: event.pointerId,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }, [drawerWidth]);

  const onDrawerResizeMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = dragStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    commitDrawerWidth(start.width + start.x - event.clientX);
  }, [commitDrawerWidth]);

  const onDrawerResizeEnd = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = dragStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragStart.current = null;
  }, []);

  if (resolved === null) return null;

  return (
    <aside
      role="dialog"
      aria-labelledby={DETAIL_HEADER_TITLE_ID}
      data-testid="detail-drawer"
      style={{
        width: drawerWidth,
        flex: `0 0 ${drawerWidth}px`,
        minWidth: 0,
        position: "relative",
        borderLeft: "1px solid var(--separator)",
        padding: 22,
        overflowY: "auto",
        background: "var(--bg-canvas)",
      }}
    >
      <div
        role="separator"
        aria-label="Resize detail drawer"
        aria-orientation="vertical"
        aria-valuemin={MIN_DRAWER_WIDTH}
        aria-valuemax={MAX_DRAWER_WIDTH}
        aria-valuenow={drawerWidth}
        data-testid="detail-drawer-resizer"
        tabIndex={0}
        onPointerDown={onDrawerResizeStart}
        onPointerMove={onDrawerResizeMove}
        onPointerUp={onDrawerResizeEnd}
        onPointerCancel={onDrawerResizeEnd}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            commitDrawerWidth(drawerWidth + 24);
          }
          if (event.key === "ArrowRight") {
            event.preventDefault();
            commitDrawerWidth(drawerWidth - 24);
          }
        }}
        className="detail-drawer__resizer"
      />
      {tabs.length > 0 && setActiveTab && closeTab && (
        <DetailDrawerTabs
          tabs={tabs}
          nodes={model.nodes}
          activeTabId={activeTabId}
          onActive={setActiveTab}
          onClose={closeTab}
          lastEvictedTabId={lastEvictedTabId}
        />
      )}
      <NodeOperationContextProvider node={resolved}>
        <DetailHeader
          node={resolved}
          onClose={onClose}
          onShowJson={onShowJson}
          projectRoot={projectRoot}
        />
        {visibleSections.map((s) => (
          <s.Component key={s.id} node={resolved} />
        ))}
      </NodeOperationContextProvider>
    </aside>
  );
}
