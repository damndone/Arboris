// frontend/src/workbench/BottomPanel.tsx
//
// V1.5.2 P4 — bottom panel host. Plan §12.
//
// Tab strip + body. Active tab follows `state.bottomPanel.id`; open/
// close follows `state.bottomPanel.open` (URL-backed). Splitter
// height persists per-runId in sessionStorage (Tier 2).
//
// V1.5.2 doesn't implement an actual draggable splitter; height is a
// fixed 240px to keep the surface honest. A real drag handle lands
// in V1.5.3 alongside the Shell panel that needs the vertical room.

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

export function BottomPanel({ runId, projectRoot }: BottomPanelProps) {
  const { state, dispatch } = useWorkbench();
  // V1.5.2 fixed 240px; height is Tier 2 so a future drag handle can
  // wire in here without changing the URL contract.
  const [height] = useSessionByRunId<number>(runId, "bottomPanelHeight", 240);

  const ctx: BottomPanelContext = { runId, projectRoot };
  const current = panelById(state.bottomPanel.id);
  const Body = current?.Component ?? null;

  return (
    <div
      data-testid="bottom-panel"
      data-open={state.bottomPanel.open ? "true" : "false"}
      style={{
        borderTop: "1px solid var(--separator, #2e2e30)",
        background: "var(--surface-elevated, transparent)",
        display: "flex",
        flexDirection: "column",
        flex: "0 0 auto",
        height: state.bottomPanel.open ? height : 32,
        minHeight: 32,
      }}
    >
      <div
        role="tablist"
        aria-label="Bottom panels"
        data-testid="bottom-panel-tabs"
        style={{
          display: "flex",
          alignItems: "stretch",
          gap: 0,
          height: 32,
          borderBottom: state.bottomPanel.open
            ? "1px solid var(--separator, #2e2e30)"
            : "0",
          padding: "0 4px",
          flex: "0 0 auto",
        }}
      >
        {bottomPanelRegistry
          .filter((p) => p.shouldRender(ctx))
          .sort((a, b) => a.order - b.order)
          .map((panel) => {
            const isActive =
              panel.id === state.bottomPanel.id && state.bottomPanel.open;
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
                  // Tab click semantics:
                  //   - clicking a different tab: switch + open
                  //   - clicking the active tab: toggle open/closed
                  if (panel.id === state.bottomPanel.id) {
                    dispatch.togglePanel();
                  } else {
                    dispatch.setBottomPanel({ id: panel.id, open: true });
                  }
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
        {state.bottomPanel.open && (
          <button
            type="button"
            data-testid="bottom-panel-close"
            onClick={() => dispatch.togglePanel()}
            aria-label="Close panel"
            style={{
              padding: "0 10px",
              border: 0,
              background: "transparent",
              color: "var(--label-tertiary)",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            ×
          </button>
        )}
      </div>
      {state.bottomPanel.open && Body && (
        <div
          data-testid="bottom-panel-body"
          style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
        >
          <Body {...ctx} />
        </div>
      )}
    </div>
  );
}
