import { useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";

export type PanelHostActiveKind = "node" | "report-review" | null;

export interface PanelHostProps {
  activeKind: PanelHostActiveKind;
  tabs: ReactNode;
  nodePanel: ReactNode;
  reportPanel: ReactNode;
  projectRoot?: string;
  collapseLabel?: string;
  initialCollapsed?: boolean;
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
}

const MIN_PANEL_WIDTH = 320;
const DEFAULT_PANEL_WIDTH = 460;
const MAX_PANEL_WIDTH = 720;

function clampPanelWidth(width: number): number {
  if (!Number.isFinite(width)) return DEFAULT_PANEL_WIDTH;
  return Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, Math.round(width)));
}

function readPanelWidth(storageKey: string): number {
  if (typeof sessionStorage === "undefined") return DEFAULT_PANEL_WIDTH;
  const raw = sessionStorage.getItem(storageKey);
  return raw === null ? DEFAULT_PANEL_WIDTH : clampPanelWidth(Number(raw));
}

function PanelHostChevron({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      aria-hidden="true"
      width="12"
      height="12"
      viewBox="0 0 12 12"
      focusable="false"
      style={{ display: "block" }}
    >
      <path
        d="M4 2 10 6 4 10Z"
        fill="currentColor"
        transform={direction === "left" ? "rotate(180 7 6)" : undefined}
      />
    </svg>
  );
}

/**
 * Shared docked right-column chrome. The shell decides which workspace tab is
 * active; this component only owns the column's visibility and chooses the
 * already-constructed panel content. Float lifecycle is deliberately kept at
 * the Workbench shell so this host can remain a small, reusable primitive.
 */
export function PanelHost({
  activeKind,
  tabs,
  nodePanel,
  reportPanel,
  projectRoot,
  collapseLabel = "right panel",
  initialCollapsed = false,
  collapsed,
  onCollapsedChange,
}: PanelHostProps) {
  const [internalCollapsed, setInternalCollapsed] = useState(initialCollapsed);
  const isCollapsed = collapsed ?? internalCollapsed;
  const setCollapsed = useCallback((next: boolean) => {
    if (collapsed === undefined) setInternalCollapsed(next);
    onCollapsedChange?.(next);
  }, [collapsed, onCollapsedChange]);
  const isEmpty = activeKind === null;
  const widthStorageKey = `workbench:detailDrawerWidth:${projectRoot ?? "default"}`;
  const [panelWidth, setPanelWidth] = useState(() => readPanelWidth(widthStorageKey));
  const resizeStart = useRef<{ x: number; width: number; pointerId: number } | null>(null);

  useEffect(() => {
    setPanelWidth(readPanelWidth(widthStorageKey));
  }, [widthStorageKey]);

  const commitPanelWidth = useCallback((nextWidth: number) => {
    const clamped = clampPanelWidth(nextWidth);
    setPanelWidth(clamped);
    if (typeof sessionStorage !== "undefined") sessionStorage.setItem(widthStorageKey, String(clamped));
  }, [widthStorageKey]);

  const onResizeStart = useCallback((event: PointerEvent<HTMLDivElement>) => {
    resizeStart.current = { x: event.clientX, width: panelWidth, pointerId: event.pointerId };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }, [panelWidth]);

  const onResizeMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = resizeStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    commitPanelWidth(start.width + start.x - event.clientX);
  }, [commitPanelWidth]);

  const onResizeEnd = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = resizeStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    resizeStart.current = null;
  }, []);

  return (
    <aside
      data-testid="panel-host"
      data-collapsed={isCollapsed ? "true" : "false"}
      data-active-kind={activeKind ?? "none"}
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        width: isEmpty ? 0 : isCollapsed ? 28 : panelWidth,
        flex: isEmpty ? "0 0 0px" : isCollapsed ? "0 0 28px" : `0 0 ${panelWidth}px`,
        minWidth: isEmpty ? 0 : isCollapsed ? 28 : MIN_PANEL_WIDTH,
        maxWidth: isEmpty ? 0 : isCollapsed ? 28 : MAX_PANEL_WIDTH,
        minHeight: 0,
        overflow: "hidden",
        borderLeft: isEmpty ? 0 : "1px solid var(--separator)",
        background: "var(--bg-canvas)",
      }}
    >
      {isEmpty ? (
        <div data-testid="panel-host-empty" aria-hidden="true" />
      ) : isCollapsed ? (
        <button
          type="button"
          aria-label={`Expand ${collapseLabel}`}
          aria-expanded={false}
          data-icon="expand-left"
          onClick={() => setCollapsed(false)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            setCollapsed(false);
          }}
          style={{
            width: 28,
            minHeight: 72,
            padding: "8px 4px",
            border: 0,
            background: "transparent",
            color: "var(--label-secondary)",
            cursor: "pointer",
            writingMode: "vertical-rl",
            fontSize: 11,
          }}
        >
            <PanelHostChevron direction="left" />
        </button>
      ) : (
        <>
          <div
            role="separator"
            aria-label="Resize right panel"
            aria-orientation="vertical"
            aria-valuemin={MIN_PANEL_WIDTH}
            aria-valuemax={MAX_PANEL_WIDTH}
            aria-valuenow={panelWidth}
            data-testid="panel-host-resizer"
            tabIndex={0}
            onPointerDown={onResizeStart}
            onPointerMove={onResizeMove}
            onPointerUp={onResizeEnd}
            onPointerCancel={onResizeEnd}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                commitPanelWidth(panelWidth + 24);
              }
              if (event.key === "ArrowRight") {
                event.preventDefault();
                commitPanelWidth(panelWidth - 24);
              }
            }}
            style={{
              position: "absolute",
              left: -2,
              top: 0,
              bottom: 0,
              width: 5,
              cursor: "col-resize",
              zIndex: 3,
            }}
          />
          <div data-testid="panel-host-tabs" className="panel-host-tabs">{tabs}</div>
          {activeKind !== null && !onCollapsedChange && (
            <button
              type="button"
              aria-label={`Collapse ${collapseLabel}`}
              aria-expanded={true}
              data-icon="collapse-right"
              onClick={() => setCollapsed(true)}
              style={{
                position: "absolute",
                top: 7,
                right: 8,
                zIndex: 2,
                minHeight: 24,
                padding: "2px 6px",
                border: "1px solid var(--separator)",
                borderRadius: 6,
                background: "var(--bg-card-2)",
                color: "var(--label-secondary)",
                cursor: "pointer",
                fontSize: 11,
              }}
            >
              <PanelHostChevron direction="right" />
            </button>
          )}
          <div
            data-testid="panel-host-content"
            style={{ flex: 1, minHeight: 0, overflow: "hidden" }}
          >
            {activeKind === "report-review" && reportPanel}
            {activeKind === "node" && nodePanel}
          </div>
        </>
      )}
    </aside>
  );
}
