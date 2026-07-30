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
import { AgentComposer } from "./agent/AgentComposer";

interface BottomPanelProps {
  runId: string;
  projectRoot: string;
}

// Keep a modest safety bound, but let the user choose the working height with
// the splitter. The panel is no longer forced into a 480px default or a
// separate Focus mode.
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
  const [open, setOpen] = useSessionByRunId<boolean>(
    runId,
    "bottomPanelOpen",
    true,
  );
  const resize = usePointerResize({
    height,
    setHeight,
    clampHeight,
  });

  const ctx: BottomPanelContext = { runId, projectRoot };
  const current = panelById(state.bottomPanel);
  const Body = current?.Component ?? null;
  const showsCompactAgentComposer = !open && state.bottomPanel === "agent";
  const expandAgentPanel = useCallback(() => {
    setOpen(true);
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLTextAreaElement>(
        '[data-testid="agent-composer"] textarea',
      )?.focus();
    });
  }, [setOpen]);

  return (
    <div
      className={`bottom-panel${showsCompactAgentComposer ? " bottom-panel--agent-compact" : ""}`}
      data-testid="bottom-panel"
      data-open={open ? "true" : "false"}
      style={{
        borderTop: "1px solid var(--separator, #2e2e30)",
        display: "flex",
        flexDirection: "column",
        flex: "0 0 auto",
        height: open ? clampHeight(height) : showsCompactAgentComposer ? "auto" : 34,
        minHeight: open ? MIN_PANEL_HEIGHT : showsCompactAgentComposer ? 0 : 34,
      }}
    >
      {open ? (
        <>
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
            className="bottom-panel__tabs"
            role="tablist"
            aria-label="Bottom panels"
            data-testid="bottom-panel-tabs"
            style={{
              display: "flex",
              alignItems: "stretch",
              gap: 0,
              height: 32,
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
                    className="bottom-panel__tab"
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
            <button
              className="bottom-panel__collapse"
              type="button"
              aria-label="Close bottom panel"
              title="Close bottom panel"
              data-testid="bottom-panel-toggle"
              onClick={() => setOpen(false)}
              style={{
                border: 0,
                background: "transparent",
                color: "var(--label-secondary)",
                cursor: "pointer",
                fontSize: 11,
                lineHeight: 1,
                padding: "0 8px",
              }}
            >
              <span aria-hidden="true">▼</span>
            </button>
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
        </>
      ) : showsCompactAgentComposer ? (
        <div className="bottom-panel__compact-agent" data-testid="bottom-panel-compact-agent">
          <AgentComposer variant="compact" onExpand={expandAgentPanel} />
        </div>
      ) : (
        <button
          type="button"
          aria-label="Open bottom panel"
          title="Open bottom panel"
          data-testid="bottom-panel-toggle"
          onClick={() => setOpen(true)}
          style={{
            alignSelf: "flex-end",
            height: 32,
            border: 0,
            background: "transparent",
            color: "var(--label-secondary)",
            cursor: "pointer",
            fontSize: 12,
            padding: "0 12px",
          }}
        >
          Open panel ^
        </button>
      )}
    </div>
  );
}
