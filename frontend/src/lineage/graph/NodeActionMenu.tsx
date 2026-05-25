// frontend/src/lineage/graph/NodeActionMenu.tsx
//
// V1.5.0 NodeActionMenu (Step 6, T6.9). Renamed and relocated from
// V1.4.1's MoreMenu. Now exposes 4 actionable items per spec §10.2;
// reserved-future items (Ask AI, Rerun, Mark bad decision, Pin to
// compare) are documented in spec §10.3 and intentionally NOT rendered
// — no placeholders, no disabled rows, no "Coming soon" tooltips.
//
// Closes on outside click + Escape + scroll (V1.4.1 MoreMenu pattern
// hardened).
//
// Popup is rendered via createPortal into document.body and positioned
// against the trigger's getBoundingClientRect() with `position: fixed`.
// This survives ancestor stacking contexts and overflow:hidden — needed
// for Step 8, when the menu mounts on a React Flow node's ⋯ affordance.
// REV-3 F1+F2.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { buildBranchPath } from "../pathBuilder";
import type {
  GraphViewModel,
  GraphViewNode,
} from "../api/graphViewTypes";
import "../tokens/lineage.css";

export interface NodeActionMenuProps {
  node: GraphViewNode;
  /** Needed by "Copy lineage path"; pass the same model the workbench owns. */
  model: GraphViewModel;
  /** Caller wires this to open the RawJsonModal. */
  onShowJson: () => void;
}

interface PopupCoords {
  top: number;
  right: number;
}

const GAP_PX = 6;

export function NodeActionMenu({ node, model, onShowJson }: NodeActionMenuProps) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<PopupCoords | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);

  // Compute popup coords from the trigger's viewport rect. Runs on open
  // and on resize so the popup tracks layout changes without itself
  // being a layout container.
  useLayoutEffect(() => {
    if (!open) {
      setCoords(null);
      return undefined;
    }
    const compute = () => {
      const btn = triggerRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      setCoords({
        top: rect.bottom + GAP_PX,
        right: window.innerWidth - rect.right,
      });
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [open]);

  // Outside-click + Escape + scroll close.
  // Portal-aware: clicks inside the popup (which lives in document.body,
  // outside our wrapper) must NOT close. We check both refs explicitly
  // instead of the wrapper.contains(target) shortcut used pre-portal.
  useEffect(() => {
    if (!open) return undefined;
    const onDocMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (popupRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    // Native <select> closes on scroll; users find a stuck popup that no
    // longer aligns with its trigger more disorienting than auto-close.
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDocMouseDown, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  const run = (fn: () => void) => () => {
    fn();
    setOpen(false);
  };

  const items: Array<{ label: string; onClick: () => void; shortcut?: string }> = [
    {
      label: "Copy node ID",
      onClick: () => navigator.clipboard.writeText(node.nodeKey),
    },
    {
      label: "Copy as JSON",
      onClick: () =>
        navigator.clipboard.writeText(JSON.stringify(node.raw, null, 2)),
    },
    {
      label: "View Raw JSON",
      onClick: onShowJson,
      shortcut: "⌘J",
    },
    {
      label: "Copy lineage path",
      onClick: () =>
        navigator.clipboard.writeText(buildBranchPath(model, node.id)),
    },
  ];

  const popup =
    open && coords !== null ? (
      <div
        ref={popupRef}
        role="menu"
        data-testid="node-action-menu-popup"
        style={{
          position: "fixed",
          top: coords.top,
          right: coords.right,
          background: "var(--bg-card-2)",
          borderRadius: 12,
          padding: 6,
          minWidth: 240,
          boxShadow:
            "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
          zIndex: 1000,
        }}
      >
        {items.map((it) => (
          <button
            key={it.label}
            type="button"
            role="menuitem"
            onClick={run(it.onClick)}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "9px 12px",
              borderRadius: 8,
              background: "transparent",
              border: 0,
              color: "var(--label)",
              cursor: "pointer",
              textAlign: "left",
              font: "inherit",
              fontSize: 13.5,
              width: "100%",
            }}
          >
            <span>{it.label}</span>
            {it.shortcut && (
              <span
                style={{
                  color: "var(--label-tertiary)",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                }}
              >
                {it.shortcut}
              </span>
            )}
          </button>
        ))}
      </div>
    ) : null;

  return (
    <div
      style={{ display: "inline-block" }}
      data-testid="node-action-menu"
    >
      <button
        ref={triggerRef}
        type="button"
        className="ln-btn-secondary"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Node actions"
      >
        Actions ⌄
      </button>
      {popup !== null && createPortal(popup, document.body)}
    </div>
  );
}
