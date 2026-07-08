// frontend/src/workbench/BottomPanel.tsx
//
// V1.5.2 P4 — bottom panel host. Plan §12.
//
// Tab strip + body. Active tab follows `state.bottomPanel.id`. The panel
// stays mounted in the bottom slot; the splitter height persists per-runId
// in sessionStorage (Tier 2).

import { useCallback, useRef, type PointerEvent } from "react";
import { useWorkbench } from "./WorkbenchStateProvider";
import {
  bottomPanelRegistry,
  panelById,
  type BottomPanelContext,
} from "./registry/bottomPanelRegistry";
import { useSessionByRunId } from "./state/useSessionByRunId";

interface BottomPanelProps {
  runId: string;
  projectRoot: string;
}

const MIN_PANEL_HEIGHT = 160;
const DEFAULT_PANEL_HEIGHT = 240;
const MAX_PANEL_HEIGHT = 520;

function clampHeight(height: number): number {
  if (!Number.isFinite(height)) return DEFAULT_PANEL_HEIGHT;
  return Math.min(MAX_PANEL_HEIGHT, Math.max(MIN_PANEL_HEIGHT, Math.round(height)));
}

function usePointerResize({
  height,
  setHeight,
  clampHeight: clamp,
}: {
  height: number;
  setHeight: (next: number) => void;
  clampHeight: (height: number) => number;
}) {
  const dragStart = useRef<{ y: number; height: number; pointerId: number } | null>(
    null,
  );

  const commitHeight = useCallback(
    (nextHeight: number) => {
      setHeight(clamp(nextHeight));
    },
    [clamp, setHeight],
  );

  const onPointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      dragStart.current = {
        y: event.clientY,
        height: clamp(height),
        pointerId: event.pointerId,
      };
      event.currentTarget.setPointerCapture?.(event.pointerId);
    },
    [clamp, height],
  );

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const start = dragStart.current;
      if (!start || start.pointerId !== event.pointerId) return;
      commitHeight(start.height + start.y - event.clientY);
    },
    [commitHeight],
  );

  const onPointerEnd = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const start = dragStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragStart.current = null;
  }, []);

  return { commitHeight, onPointerDown, onPointerMove, onPointerEnd };
}

export function BottomPanel({ runId, projectRoot }: BottomPanelProps) {
  const { state, dispatch } = useWorkbench();
  const [height, setHeight] = useSessionByRunId<number>(
    runId,
    "bottomPanelHeight",
    DEFAULT_PANEL_HEIGHT,
  );
  const resize = usePointerResize({
    height,
    setHeight,
    clampHeight,
  });

  const ctx: BottomPanelContext = { runId, projectRoot };
  const current = panelById(state.bottomPanel);
  const Body = current?.Component ?? null;

  return (
    <div
      data-testid="bottom-panel"
      data-open="true"
      style={{
        borderTop: "1px solid var(--separator, #2e2e30)",
        background: "var(--surface-elevated, transparent)",
        display: "flex",
        flexDirection: "column",
        flex: "0 0 auto",
        height: clampHeight(height),
        minHeight: MIN_PANEL_HEIGHT,
      }}
    >
      <div
        role="separator"
        aria-label="Resize bottom panel"
        aria-orientation="horizontal"
        data-testid="bottom-panel-resizer"
        tabIndex={0}
        onPointerDown={resize.onPointerDown}
        onPointerMove={resize.onPointerMove}
        onPointerUp={resize.onPointerEnd}
        onPointerCancel={resize.onPointerEnd}
        onKeyDown={(event) => {
          if (event.key === "ArrowUp") {
            event.preventDefault();
            resize.commitHeight(height + 24);
          }
          if (event.key === "ArrowDown") {
            event.preventDefault();
            resize.commitHeight(height - 24);
          }
        }}
        style={{
          height: 8,
          marginTop: -4,
          cursor: "ns-resize",
          flex: "0 0 auto",
          touchAction: "none",
        }}
      />
      <div
        role="tablist"
        aria-label="Bottom panels"
        data-testid="bottom-panel-tabs"
        style={{
          display: "flex",
          alignItems: "stretch",
          gap: 0,
          height: 32,
          borderBottom: "1px solid var(--separator, #2e2e30)",
          padding: "0 4px",
          flex: "0 0 auto",
        }}
      >
        {bottomPanelRegistry
          .filter((p) => p.shouldRender(ctx))
          .sort((a, b) => a.order - b.order)
          .map((panel) => {
            const isActive = panel.id === state.bottomPanel;
            const disabled = panel.disabled?.(ctx);
            return (
              <button
                key={panel.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                data-testid={`panel-tab-${panel.id}`}
                data-disabled={disabled ? "true" : undefined}
                title={disabled ? disabled.reason : undefined}
                onClick={() => {
                  dispatch.setBottomPanel(panel.id);
                }}
                style={{
                  padding: "0 12px",
                  border: 0,
                  background: isActive
                    ? "var(--tint-bg, rgba(10,132,255,0.12))"
                    : "transparent",
                  color: disabled
                    ? "var(--label-tertiary)"
                    : isActive
                      ? "var(--tint, #0a84ff)"
                      : "var(--label-secondary)",
                  cursor: disabled ? "help" : "pointer",
                  fontSize: 12,
                  fontWeight: isActive ? 600 : 400,
                  borderRadius: 4,
                  opacity: disabled ? 0.7 : 1,
                }}
              >
                {panel.label}
              </button>
            );
          })}
        <div style={{ flex: 1 }} />
      </div>
      {Body && (
        <div
          data-testid="bottom-panel-body"
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            overflow: "auto",
          }}
        >
          <Body {...ctx} />
        </div>
      )}
    </div>
  );
}
