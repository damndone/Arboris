// v1.9.0 — the bottom panel (design spec §8.3 #5). Runs, Logs and Activity
// sit below the map and stage; the Agent has its own column. Folded, the
// panel is a single row of tabs; open, it can be dragged taller. The open
// state and height are remembered per project for the session.

import { useCallback, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { ChevronIcon } from "./icons";
import "./workspaceBottom.css";

export interface BottomTab {
  id: string;
  label: string;
  render: () => ReactNode;
}

const MIN_HEIGHT = 160;
const DEFAULT_HEIGHT = 240;
const MAX_HEIGHT = 520;

const clamp = (height: number) => Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.round(height)));

function useSessionState<T>(key: string, fallback: T): [T, (next: T) => void] {
  const read = (): T => {
    try {
      const raw = sessionStorage.getItem(key);
      return raw === null ? fallback : (JSON.parse(raw) as T);
    } catch {
      return fallback;
    }
  };
  const [value, setValue] = useState<T>(read);
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        sessionStorage.setItem(key, JSON.stringify(next));
      } catch {
        // ignore
      }
    },
    [key],
  );
  return [value, set];
}

export function WorkspaceBottomPanel({ projectRoot, tabs }: { projectRoot: string; tabs: BottomTab[] }) {
  const [activeId, setActiveId] = useSessionState(`workbench:bottom:tab:${projectRoot}`, tabs[0]?.id ?? "");
  const [open, setOpen] = useSessionState(`workbench:bottom:open:${projectRoot}`, false);
  const [height, setHeight] = useSessionState(`workbench:bottom:height:${projectRoot}`, DEFAULT_HEIGHT);
  const drag = useRef<{ pointerId: number; y: number; height: number } | null>(null);
  const active = tabs.find((tab) => tab.id === activeId) ?? tabs[0];

  const choose = (id: string) => {
    setActiveId(id);
    if (!open) setOpen(true);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { pointerId: event.pointerId, y: event.clientY, height: clamp(height) };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start || start.pointerId !== event.pointerId) return;
    setHeight(clamp(start.height + start.y - event.clientY));
  };
  const onPointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    drag.current = null;
  };

  return (
    <div className="ws-bottom-panel" data-open={open ? "true" : "false"} style={open ? { height: clamp(height) } : undefined}>
      {open && (
        <div
          className="ws-bottom-panel__resizer"
          role="separator"
          tabIndex={0}
          aria-orientation="horizontal"
          aria-label="Bottom panel height"
          aria-valuemin={MIN_HEIGHT}
          aria-valuemax={MAX_HEIGHT}
          aria-valuenow={clamp(height)}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerEnd}
          onKeyDown={(event) => {
            if (event.key === "ArrowUp") setHeight(clamp(height + 24));
            else if (event.key === "ArrowDown") setHeight(clamp(height - 24));
            else return;
            event.preventDefault();
          }}
        />
      )}
      <div className="ws-bottom-panel__bar">
        <div className="ws-bottom-panel__tabs" role="tablist" aria-label="Bottom panel">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`ws-bottom-tab-${tab.id}`}
              aria-selected={open && tab.id === active?.id}
              aria-controls={open && tab.id === active?.id ? "ws-bottom-body" : undefined}
              className="ws-bottom-panel__tab"
              onClick={() => choose(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="ws-icon-button"
          aria-label={open ? "Fold the bottom panel" : "Open the bottom panel"}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <ChevronIcon direction={open ? "down" : "up"} />
        </button>
      </div>
      {open && active && (
        <div className="ws-bottom-panel__body" id="ws-bottom-body" role="tabpanel" aria-labelledby={`ws-bottom-tab-${active.id}`}>
          {active.render()}
        </div>
      )}
    </div>
  );
}
