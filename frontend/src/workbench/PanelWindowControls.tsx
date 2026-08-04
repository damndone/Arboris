import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import "./panelWindowControls.css";

export type PanelWindowSurface = "report review" | "node panel";

export interface PanelWindowControlsProps {
  surface: PanelWindowSurface;
  floating: boolean;
  pinned: boolean;
  collapsed: boolean;
  onFloat?: () => void;
  onDock?: () => void;
  onPin?: () => void;
  onUnpin?: () => void;
  onCollapse?: () => void;
  onExpand?: () => void;
}

export interface PanelWindowDragHandleProps {
  surface: PanelWindowSurface;
  floating: boolean;
  pinned: boolean;
  dragging?: boolean;
  onPointerDown?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onKeyDown?: (event: ReactKeyboardEvent<HTMLButtonElement>) => void;
}

export function PanelWindowDragHandle({
  surface,
  floating,
  pinned,
  dragging = false,
  onPointerDown,
  onKeyDown,
}: PanelWindowDragHandleProps) {
  if (!floating) return null;
  return (
    <button
      type="button"
      className="panel-window-drag-handle"
      aria-label={`Drag ${surface}`}
      aria-disabled={pinned ? "true" : undefined}
      aria-pressed={dragging}
      aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight"
      title={pinned ? `Unpin ${surface} to move it` : `Drag ${surface}`}
      onPointerDown={pinned ? undefined : onPointerDown}
      onKeyDown={pinned ? undefined : onKeyDown}
    >
      <span aria-hidden="true">⋮⋮</span>
    </button>
  );
}

export function PanelWindowControls({
  surface,
  floating,
  pinned,
  collapsed,
  onFloat,
  onDock,
  onPin,
  onUnpin,
  onCollapse,
  onExpand,
}: PanelWindowControlsProps) {
  return (
    <div className="panel-window-controls" role="group" aria-label={`${surface} window controls`}>
      <button
        type="button"
        className="panel-window-controls__icon-button"
        data-icon={floating ? "dock" : "float"}
        aria-label={`${floating ? "Dock" : "Float"} ${surface}`}
        title={`${floating ? "Dock" : "Float"} ${surface}`}
        onClick={floating ? onDock : onFloat}
      >
        <PanelWindowIcon name={floating ? "dock" : "float"} />
      </button>
      <button
        type="button"
        className={`panel-window-controls__icon-button${pinned ? " panel-window-controls__icon-button--active" : ""}`}
        data-icon="pin"
        aria-label={`${pinned ? "Unpin" : "Pin"} ${surface}`}
        title={`${pinned ? "Unpin" : "Pin"} ${surface}`}
        aria-pressed={pinned}
        onClick={pinned ? onUnpin : onPin}
      >
        <PanelWindowIcon name="pin" filled={pinned} />
      </button>
      <button
        type="button"
        className="panel-window-controls__icon-button"
        data-icon={collapsed ? "collapse-left" : "collapse-right"}
        aria-label={`${collapsed ? "Expand" : "Collapse"} ${surface}`}
        title={`${collapsed ? "Expand" : "Collapse"} ${surface}`}
        onClick={collapsed ? onExpand : onCollapse}
      >
        <PanelWindowIcon name="collapse" direction={collapsed ? "left" : "right"} />
      </button>
    </div>
  );
}

function PanelWindowIcon({
  name,
  filled = false,
  direction,
}: {
  name: "float" | "dock" | "pin" | "collapse";
  filled?: boolean;
  direction?: "left" | "right";
}) {
  if (name === "pin") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path
          d="M14.2 3.5 20.5 9.8l-2.1 2.1-2.3-2.3-4.3 4.3 3.1 3.1-1.4 1.4-4.3-2.9-4.1 4.1-1.1-1.1 4.1-4.1-2.9-4.3 1.4-1.4 3.1 3.1 4.3-4.3-2.3-2.3 2.1-2.1Z"
          fill={filled ? "currentColor" : "none"}
          stroke="currentColor"
          strokeLinejoin="round"
          strokeWidth="1.5"
        />
        <path d="m10.2 13.8-5.7 5.7" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
      </svg>
    );
  }

  if (name === "collapse") {
    return (
      <svg
        width="14"
        height="14"
        viewBox="0 0 14 14"
        aria-hidden="true"
        focusable="false"
        style={{ transform: direction === "left" ? "rotate(180deg)" : undefined }}
      >
        <path d="M4 2.5 10 7l-6 4.5Z" fill="currentColor" />
      </svg>
    );
  }

  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d={name === "float" ? "M14 4h6v6M20 4l-9 9M5 7v12h12v-5" : "M10 20H4V14M4 20l9-9M19 17V5H7"}
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
    </svg>
  );
}
