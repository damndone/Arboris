// v1.9.0 — the Agent in three presentations: docked in the right column,
// floating over the workspace, or folded to a bubble. One conversation stays
// mounted through all three.
//
// Motion: between bubble and window the card itself morphs (left, top, width,
// height and radius ease on the spring) while the conversation keeps its final
// size and is revealed from the bubble's corner, so nothing reflows mid-flight.
// A released bubble travels where it was thrown and rests on the nearer side
// edge; a released window settles with a little momentum. Docking hands over to
// the column's own spring. Reduced motion turns all of it into plain cuts.

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";
import type { AgentMode } from "./layoutModel";
import {
  BUBBLE,
  MARGIN,
  clamp,
  defaultBubble,
  keepInside,
  projectRelease,
  restBubble,
  windowFromBubble,
  type Bounds,
  type Point,
} from "./agentWindowGeometry";
import { AgentRailIcon, ChevronIcon, DockIcon, FloatIcon, GripIcon, MinimizeIcon } from "./icons";
import "./agentWindow.css";

export type { AgentMode };

const FULL_HEIGHT = 540;
const COMPACT_HEIGHT = 232;
const KEY_STEP = 24;
/** A dropped window keeps a fraction of the throw; the bubble keeps all of it. */
const WINDOW_MOMENTUM = 0.5;

type Gesture = {
  id: number;
  kind: "move" | "resize";
  origin: Point;
  start: Point;
  width: number;
  moved: boolean;
  samples: Array<Point & { t: number }>;
};

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

function velocity(samples: Gesture["samples"]): Point {
  const last = samples[samples.length - 1];
  const first = samples.find((sample) => last.t - sample.t <= 100) ?? last;
  const dt = last.t - first.t;
  return dt > 0 ? { x: (last.x - first.x) / dt, y: (last.y - first.y) / dt } : { x: 0, y: 0 };
}

/** Capture is a nicety: a pointer the browser no longer tracks must not end the gesture. */
function capture(event: PointerEvent<HTMLElement>, on: boolean) {
  try {
    if (on) event.currentTarget.setPointerCapture?.(event.pointerId);
    else event.currentTarget.releasePointerCapture?.(event.pointerId);
  } catch {
    // ignore
  }
}

function useShellBounds(shellRef: RefObject<HTMLDivElement>): Bounds {
  const [bounds, setBounds] = useState<Bounds>({ width: 1024, height: 700, top: 96 });
  // The shell's ref is attached after this component's layout effects, so
  // measure after commit.
  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    const measure = () => {
      const rect = shell.getBoundingClientRect();
      setBounds({
        width: rect.width || window.innerWidth,
        height: rect.height || window.innerHeight,
        top: shell.querySelector(".ws-topbar")?.getBoundingClientRect().height || 96,
      });
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(shell);
    const bar = shell.querySelector(".ws-topbar");
    if (bar) observer?.observe(bar);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [shellRef]);
  return bounds;
}

export function AgentWindow({
  mode,
  setMode,
  width,
  maxWidth,
  setWidth,
  shellRef,
  children,
}: {
  mode: AgentMode;
  setMode: (mode: AgentMode) => void;
  width: number;
  maxWidth: number;
  setWidth: (width: number) => void;
  shellRef: RefObject<HTMLDivElement>;
  children: ReactNode;
}) {
  const bounds = useShellBounds(shellRef);
  const [bubbleAt, setBubbleAt] = useState<Point | null>(null);
  const [windowAt, setWindowAt] = useState<Point | null>(null);
  const [compact, setCompact] = useState(false);
  const [moving, setMoving] = useState(false);
  const gesture = useRef<Gesture | null>(null);
  // A drag ends with a click on the same element; that click is not a tap.
  const dragEndedAt = useRef(-Infinity);
  const asideRef = useRef<HTMLElement>(null);
  const bubbleRef = useRef<HTMLButtonElement>(null);
  const focusRef = useRef<HTMLButtonElement>(null);
  const previous = useRef<{ mode: AgentMode; rect: DOMRect | null }>({ mode, rect: null });

  const maximumWidth = Math.min(maxWidth, bounds.width - 2 * MARGIN);
  const minimumWidth = Math.min(280, maximumWidth);
  const panelWidth = Math.min(width, Math.max(180, bounds.width - 2 * MARGIN));
  const fullHeight = Math.min(FULL_HEIGHT, Math.max(120, (bounds.height - bounds.top - 2 * MARGIN) * 0.82));
  const windowSize = { width: panelWidth, height: compact ? Math.min(COMPACT_HEIGHT, fullHeight) : fullHeight };
  const bubble = keepInside(bubbleAt ?? defaultBubble(bounds), { width: BUBBLE, height: BUBBLE }, bounds);
  const win = keepInside(windowAt ?? windowFromBubble(bubble, windowSize, bounds), windowSize, bounds);
  const docked = mode === "docked";
  const floating = mode === "floating";
  // The conversation is revealed from the corner the bubble sits in.
  const corner = {
    x: bubble.x + BUBBLE / 2 >= bounds.width / 2 ? "right" : "left",
    y: bubble.y + BUBBLE / 2 >= (bounds.top + bounds.height) / 2 ? "bottom" : "top",
  };

  const changeMode = (next: AgentMode) => {
    if (next === mode) return;
    if (next === "floating" && mode === "bubble") setWindowAt(windowFromBubble(bubble, { width: panelWidth, height: fullHeight }, bounds));
    if (next === "floating" && mode === "docked") setWindowAt({ x: bounds.width - panelWidth - 2 * MARGIN, y: bounds.top + 2 * MARGIN });
    if (next !== "floating") setCompact(false);
    setMode(next);
  };

  // Hand-offs the CSS transition cannot carry: into and out of the column.
  useLayoutEffect(() => {
    const el = asideRef.current;
    const before = previous.current;
    previous.current = { mode, rect: el?.getBoundingClientRect() ?? null };
    if (!el || before.mode === mode) return;
    // Focus that was in the Agent follows it to the control that now stands for it.
    const active = document.activeElement;
    if (active === document.body || el.contains(active)) {
      // Opened from the bubble, the Agent is opened to be asked something.
      const input = before.mode === "bubble" ? el.querySelector<HTMLElement>("textarea:not([disabled])") : null;
      (input ?? (mode === "bubble" ? bubbleRef : focusRef).current)?.focus();
    }
    if (!before.rect || reducedMotion() || typeof el.animate !== "function") return;
    const easing = getComputedStyle(el).getPropertyValue("--ease-spring").trim() || "ease-out";
    const now = el.getBoundingClientRect();
    const dx = before.rect.left + before.rect.width / 2 - (now.left + now.width / 2);
    const dy = before.rect.top + before.rect.height / 2 - (now.top + now.height / 2);
    if (mode === "bubble" && before.mode === "docked") {
      el.animate([{ transform: `translate(${dx}px, ${dy}px) scale(0.6)`, opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 420, easing });
    } else if (mode === "floating" && before.mode === "docked") {
      const lift = `translate(${before.rect.left - now.left}px, ${before.rect.top - now.top}px)`;
      el.animate([{ transform: lift, opacity: 0.6 }, { transform: "none", opacity: 1 }], { duration: 380, easing });
    } else if (mode === "docked") {
      el.querySelector(".ws-agent__body")?.animate([{ transform: "translateX(24px)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 300, easing });
    }
  }, [mode]);

  const startGesture = (event: PointerEvent<HTMLElement>, kind: Gesture["kind"]) => {
    if (event.button !== 0) return;
    if (kind === "move" && (event.target as Element).closest("button:not(.ws-agent__grip, .ws-agent__bubble)")) return;
    capture(event, true);
    const sample = { x: event.clientX, y: event.clientY, t: event.timeStamp };
    gesture.current = { id: event.pointerId, kind, origin: sample, start: mode === "bubble" ? bubble : win, width: panelWidth, moved: false, samples: [sample] };
    setMoving(true);
  };
  const moveGesture = (event: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g || event.pointerId !== g.id) return;
    const dx = event.clientX - g.origin.x;
    const dy = event.clientY - g.origin.y;
    g.moved ||= Math.hypot(dx, dy) > 4;
    g.samples = [...g.samples.slice(-7), { x: event.clientX, y: event.clientY, t: event.timeStamp }];
    if (g.kind === "resize") {
      const next = clamp(g.width - dx, minimumWidth, maximumWidth);
      setWidth(next);
      if (!docked) setWindowAt({ ...g.start, x: g.start.x + g.width - next });
    } else if (mode === "bubble") {
      setBubbleAt(keepInside({ x: g.start.x + dx, y: g.start.y + dy }, { width: BUBBLE, height: BUBBLE }, bounds));
    } else {
      setWindowAt(keepInside({ x: g.start.x + dx, y: g.start.y + dy }, windowSize, bounds));
    }
  };
  const endGesture = (event: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g || event.pointerId !== g.id) return;
    capture(event, false);
    gesture.current = null;
    if (g.moved) dragEndedAt.current = performance.now();
    if (g.kind === "move" && g.moved) {
      const released = { x: g.start.x + event.clientX - g.origin.x, y: g.start.y + event.clientY - g.origin.y };
      const v = velocity(g.samples);
      // Released in the same render as `moving` clears, so the spring carries it.
      if (mode === "bubble") setBubbleAt(restBubble(projectRelease(released, v), bounds));
      else setWindowAt(keepInside(projectRelease(released, { x: v.x * WINDOW_MOMENTUM, y: v.y * WINDOW_MOMENTUM }), windowSize, bounds));
    }
    setMoving(false);
  };
  const gestureProps = (kind: Gesture["kind"]) => ({
    onPointerDown: (event: PointerEvent<HTMLElement>) => startGesture(event, kind),
    onPointerMove: moveGesture,
    onPointerUp: endGesture,
    onPointerCancel: endGesture,
  });

  const keyboardMove = (event: KeyboardEvent) => {
    const step: Record<string, Point> = {
      ArrowLeft: { x: -KEY_STEP, y: 0 },
      ArrowRight: { x: KEY_STEP, y: 0 },
      ArrowUp: { x: 0, y: -KEY_STEP },
      ArrowDown: { x: 0, y: KEY_STEP },
    };
    const d = step[event.key];
    if (!d || docked) return;
    event.preventDefault();
    if (mode === "bubble") setBubbleAt(keepInside({ x: bubble.x + d.x, y: bubble.y + d.y }, { width: BUBBLE, height: BUBBLE }, bounds));
    else setWindowAt(keepInside({ x: win.x + d.x, y: win.y + d.y }, windowSize, bounds));
  };

  const toggleHistory = () => {
    const next = !compact;
    const nextHeight = next ? Math.min(COMPACT_HEIGHT, fullHeight) : fullHeight;
    // A window in the lower half keeps its bottom edge where it is.
    if (win.y + windowSize.height / 2 > (bounds.top + bounds.height) / 2) setWindowAt({ x: win.x, y: win.y + windowSize.height - nextHeight });
    setCompact(next);
  };

  const box = mode === "bubble" ? { left: bubble.x, top: bubble.y, width: BUBBLE, height: BUBBLE } : { left: win.x, top: win.y, ...windowSize };
  const style = docked
    ? undefined
    : ({ ...box, "--agent-panel-width": `${panelWidth}px`, "--agent-panel-height": `${windowSize.height}px` } as CSSProperties);

  return (
    <aside
      ref={asideRef}
      className="ws-agent"
      aria-label="Agent"
      data-mode={mode}
      data-compact={compact}
      data-moving={moving}
      data-corner-x={corner.x}
      data-corner-y={corner.y}
      style={style}
    >
      {mode === "bubble" && (
        <button
          ref={bubbleRef}
          type="button"
          className="ws-agent__bubble"
          aria-label="Show the Agent"
          title="Open the Agent (⌘.) · drag to move"
          {...gestureProps("move")}
          onKeyDown={keyboardMove}
          onClick={() => {
            if (performance.now() - dragEndedAt.current > 50) changeMode("floating");
          }}
        >
          <AgentRailIcon />
        </button>
      )}
      <div className="ws-agent__body" hidden={mode === "bubble"}>
        <div className="ws-agent__header" {...(floating ? gestureProps("move") : {})}>
          {floating && (
            <button ref={focusRef} type="button" className="ws-agent__grip" aria-label="Move the Agent" title="Drag to move · arrow keys move it too" onKeyDown={keyboardMove}>
              <GripIcon />
            </button>
          )}
          <span className="ws-agent__title">Agent</span>
          {floating && (
            <button
              type="button"
              className="ws-icon-button"
              aria-label={compact ? "Show conversation history" : "Collapse conversation history"}
              aria-expanded={!compact}
              title={compact ? "Show the conversation" : "Keep only the input"}
              onClick={toggleHistory}
            >
              <ChevronIcon direction={compact ? "down" : "up"} />
            </button>
          )}
          <button
            ref={docked ? focusRef : undefined}
            type="button"
            className="ws-icon-button"
            aria-label={docked ? "Float the Agent" : "Dock the Agent"}
            title={docked ? "Float over the workspace" : "Dock to the right column"}
            onClick={() => changeMode(docked ? "floating" : "docked")}
          >
            {docked ? <FloatIcon /> : <DockIcon />}
          </button>
          <button type="button" className="ws-icon-button" aria-label="Fold the Agent" title="Fold to a bubble (⌘.)" onClick={() => changeMode("bubble")}>
            <MinimizeIcon />
          </button>
        </div>
        <div className="ws-agent__content">{children}</div>
      </div>
      {mode !== "bubble" && (
        <div
          className="ws-agent__resize"
          role="separator"
          tabIndex={0}
          aria-label="Agent width"
          aria-orientation="vertical"
          aria-valuenow={Math.round(panelWidth)}
          aria-valuemin={minimumWidth}
          aria-valuemax={maximumWidth}
          {...gestureProps("resize")}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            setWidth(clamp(width + (event.key === "ArrowLeft" ? 20 : -20), minimumWidth, maximumWidth));
          }}
        />
      )}
    </aside>
  );
}
