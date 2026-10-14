// v1.9.0 — right-click on selected text anywhere in the workspace (results,
// reports, data, the Agent's replies) offers to ask the Agent about it, to
// quote it into the message being written, or to copy it. Without a selection,
// in a text field, or where another menu already handled the click, the
// browser's own menu is left alone.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { quoteSelection, selectionQuestion, useAskAgent } from "./agent/askAgent";

const SHELL = '[data-testid="workspace-shell"]';
const BLOCK = "tr, li, p, dd, figure, .ws-result__number, section, article";

interface Open {
  x: number;
  y: number;
  text: string;
  context: string;
  where: string;
}

function editable(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
}

/** The row or paragraph the selection sits in, so the Agent sees it in context. */
function surrounding(range: Range): string {
  const start = range.startContainer;
  const element = start instanceof Element ? start : start.parentElement;
  const block = element?.closest(BLOCK);
  if (!block) return "";
  if (!block.matches("tr")) return (block.textContent ?? "").replace(/\s+/g, " ").trim();
  // A table row with its column names, so "946.1" arrives as "SE: 946.1".
  const headers = Array.from(block.closest("table")?.querySelectorAll("thead th") ?? []).map((th) => th.textContent?.trim() ?? "");
  return Array.from(block.children)
    .map((cell, index) => {
      const value = (cell.textContent ?? "").replace(/\s+/g, " ").trim();
      return headers[index] && value ? `${headers[index]}: ${value}` : value;
    })
    .filter(Boolean)
    .join(" | ");
}

/** Which part of the workspace the selection came from, in its own words. */
function whereFrom(range: Range): string {
  const start = range.startContainer;
  const element = start instanceof Element ? start : start.parentElement;
  const region = element?.closest("[aria-label]");
  return region?.getAttribute("aria-label") ?? "";
}

export function SelectionMenu() {
  const ask = useAskAgent();
  const [open, setOpen] = useState<Open | null>(null);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ask) return undefined;
    const onContextMenu = (event: MouseEvent) => {
      if (event.defaultPrevented || editable(event.target)) return;
      const target = event.target instanceof Element ? event.target : null;
      if (!target?.closest(SHELL)) return;
      const selection = window.getSelection();
      // Table cells arrive tab-separated; keep them apart readably.
      const text = (selection?.toString() ?? "").replace(/\t+/g, " | ").replace(/[ \u00a0]+/g, " ").trim();
      if (!selection || selection.isCollapsed || !text || selection.rangeCount === 0) return;
      const range = selection.getRangeAt(0);
      event.preventDefault();
      setOpen({ x: event.clientX, y: event.clientY, text, context: surrounding(range), where: whereFrom(range) });
    };
    document.addEventListener("contextmenu", onContextMenu);
    return () => document.removeEventListener("contextmenu", onContextMenu);
  }, [ask]);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(null);
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    const onPointer = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    window.addEventListener("scroll", close, true);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("blur", close);
    };
  }, [open]);

  // Placed at the pointer and kept inside the window.
  useLayoutEffect(() => {
    const element = menu.current;
    if (!open || !element) return;
    const { width, height } = element.getBoundingClientRect();
    element.style.left = `${Math.max(8, Math.min(open.x, window.innerWidth - width - 8))}px`;
    element.style.top = `${Math.max(8, Math.min(open.y, window.innerHeight - height - 8))}px`;
    element.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);

  if (!ask || !open) return null;
  const run = (action: () => void) => () => {
    action();
    setOpen(null);
  };
  return createPortal(
    <div ref={menu} className="ws-selection-menu" role="menu" aria-label="Selected text">
      <button type="button" role="menuitem" onClick={run(() => ask.put(selectionQuestion(open.text, open.context, open.where)))}>
        Ask Agent about this
      </button>
      <button type="button" role="menuitem" onClick={run(() => ask.put(quoteSelection(open.text)))}>
        Add to Agent message
      </button>
      <button type="button" role="menuitem" onClick={run(() => void navigator.clipboard?.writeText(open.text))}>
        Copy
      </button>
    </div>,
    document.body,
  );
}
