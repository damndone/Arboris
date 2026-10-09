import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject, type PointerEvent, type CSSProperties } from "react";
import { AgentRailIcon, FoldRightIcon } from "./icons";
import "./agentWindow.css";

export type AgentMode = "bubble" | "floating" | "docked";
type Point = { x: number; y: number };
const clamp = (n: number, low: number, high: number) => Math.max(low, Math.min(n, Math.max(low, high)));

/** A single mounted conversation follows the window through all presentation modes. */
export function AgentWindow({ mode, setMode, width, maxWidth, setWidth, shellRef, children }: {
  mode: AgentMode; setMode: (mode: AgentMode) => void;
  width: number; maxWidth: number; setWidth: (width: number) => void;
  shellRef: RefObject<HTMLDivElement>; children: ReactNode;
}) {
  const [bounds, setBounds] = useState({ width: 1024, height: 700, top: 96 });
  const [position, setPosition] = useState<Point | null>(null);
  const [compact, setCompact] = useState(false);
  const [moving, setMoving] = useState(false);
  const gesture = useRef<{ id: number; x: number; y: number; start: Point; width: number; resize: boolean; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const bubbleRef = useRef<HTMLButtonElement>(null);
  const titleRef = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    const el = shellRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setBounds({ width: rect.width || window.innerWidth, height: rect.height || window.innerHeight,
        top: el.querySelector(".ws-topbar")?.getBoundingClientRect().height || 96 });
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(el);
    const bar = el.querySelector(".ws-topbar");
    if (bar) observer?.observe(bar);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [shellRef]);
  const maximumWidth = Math.min(maxWidth, bounds.width - 24);
  const minimumWidth = Math.min(280, maximumWidth);
  const panelWidth = Math.min(width, Math.max(180, bounds.width - 24));
  const height = mode === "bubble" ? 48 : Math.min(compact ? 230 : 540, Math.max(100, (bounds.height - bounds.top - 24) * .82));
  const size = mode === "bubble" ? 48 : panelWidth;
  const limit = (point: Point) => ({ x: clamp(point.x, 12, bounds.width - size - 12), y: clamp(point.y, bounds.top + 12, bounds.height - height - 12) });
  const point = limit(position ?? { x: bounds.width - size - 20, y: bounds.height - height - 56 });
  const changeMode = (next: AgentMode) => {
    setMode(next);
    // The destination control is mounted after the mode update.
    requestAnimationFrame(() => (next === "bubble" ? bubbleRef : titleRef).current?.focus());
  };
  const start = (event: PointerEvent<HTMLElement>, resize = false) => {
    if (event.button !== 0) return;
    if (mode === "docked" && !resize) return;
    suppressClick.current = false;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, start: point, width: panelWidth, resize, moved: false };
    setMoving(true);
  };
  const move = (event: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g || event.pointerId !== g.id) return;
    const dx = event.clientX - g.x, dy = event.clientY - g.y;
    g.moved ||= Math.hypot(dx, dy) > 4;
    if (g.resize) {
      const next = clamp(g.width - dx, minimumWidth, maximumWidth);
      setWidth(next);
      if (mode !== "docked") setPosition({ ...g.start, x: g.start.x + g.width - next });
    } else setPosition(limit({ x: g.start.x + dx, y: g.start.y + dy }));
  };
  const end = (event: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g || event.pointerId !== g.id) return;
    suppressClick.current = g.moved;
    if (mode === "bubble" && g.moved) {
      const landing = limit({ x: g.start.x + event.clientX - g.x, y: g.start.y + event.clientY - g.y });
      if (landing.x < 60) landing.x = 12;
      else if (bounds.width - landing.x - size < 60) landing.x = bounds.width - size - 12;
      if (landing.y - bounds.top < 60) landing.y = bounds.top + 12;
      else if (bounds.height - landing.y - height < 60) landing.y = bounds.height - height - 12;
      setPosition(limit(landing));
    }
    gesture.current = null;
    setMoving(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };
  const dragProps = { onPointerDown: (e: PointerEvent<HTMLElement>) => start(e), onPointerMove: move, onPointerUp: end, onPointerCancel: end };
  const activate = (action: () => void) => { if (!suppressClick.current) action(); suppressClick.current = false; };
  const keyboardMove = (event: React.KeyboardEvent) => {
    const direction: Record<string, Point> = { ArrowLeft: { x: -20, y: 0 }, ArrowRight: { x: 20, y: 0 }, ArrowUp: { x: 0, y: -20 }, ArrowDown: { x: 0, y: 20 } };
    const d = direction[event.key];
    if (!d || mode === "docked") return;
    event.preventDefault(); setPosition(limit({ x: point.x + d.x, y: point.y + d.y }));
  };
  const style = mode === "docked" ? undefined : { left: point.x, top: point.y, width: size, height } as CSSProperties;
  return <aside className="ws-agent" aria-label="Agent" data-mode={mode} data-compact={compact} data-moving={moving} style={style}>
    {mode === "bubble" && <button ref={bubbleRef} type="button" className="ws-agent__bubble" aria-label="Show the Agent" title="Open Agent · drag to move" {...dragProps} onKeyDown={keyboardMove} onClick={() => activate(() => changeMode("floating"))}><AgentRailIcon /></button>}
    <div className="ws-agent__body" hidden={mode === "bubble"}>
      <div className="ws-agent__header">
        <button ref={titleRef} type="button" className="ws-agent__title" aria-label={compact ? "Show conversation history" : "Collapse conversation history"} aria-expanded={!compact} {...dragProps} onKeyDown={keyboardMove} onClick={() => activate(() => setCompact(!compact))}>Agent <span aria-hidden="true">{compact ? "⌄" : "⌃"}</span></button>
        <button type="button" className="ws-icon-button" aria-label={mode === "docked" ? "Float the Agent" : "Fully expand the Agent"} onClick={() => { setCompact(false); changeMode(mode === "docked" ? "floating" : "docked"); }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" /></svg></button>
        <button type="button" className="ws-icon-button" aria-label="Fold the Agent" title="Fold the Agent (⌘.)" onClick={() => changeMode("bubble")}><FoldRightIcon /></button>
      </div>
      <div className="ws-agent__content">{children}</div>
    </div>
    {mode !== "bubble" && <div className="ws-agent__resize" role="separator" tabIndex={0} aria-label="Agent width" aria-orientation="vertical" aria-valuenow={Math.round(panelWidth)} aria-valuemin={minimumWidth} aria-valuemax={maximumWidth} onPointerDown={(e) => start(e, true)} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onKeyDown={(e) => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); setWidth(clamp(width + (e.key === "ArrowLeft" ? 20 : -20), minimumWidth, maximumWidth)); } }} />}
  </aside>;
}
