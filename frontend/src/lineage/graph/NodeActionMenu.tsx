// frontend/src/lineage/graph/NodeActionMenu.tsx
//
// V1.5.0 NodeActionMenu (Step 6, T6.9). Renamed and relocated from
// V1.4.1's MoreMenu. Now exposes 4 actionable items per spec §10.2;
// reserved-future items (Ask AI, Rerun, Mark bad decision, Pin to
// compare) are documented in spec §10.3 and intentionally NOT rendered
// — no placeholders, no disabled rows, no "Coming soon" tooltips.
//
// Closes on outside click + Escape (V1.4.1 MoreMenu pattern hardened).

import { useEffect, useRef, useState } from "react";
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

export function NodeActionMenu({ node, model, onShowJson }: NodeActionMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Outside-click + Escape close (V1.5.0 hardening of V1.4.1 pattern).
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDocClick, true);
      document.removeEventListener("keydown", onKey, true);
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

  return (
    <div
      ref={rootRef}
      style={{ position: "relative", display: "inline-block" }}
      data-testid="node-action-menu"
    >
      <button
        type="button"
        className="ln-btn-secondary"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Node actions"
      >
        Actions ⌄
      </button>
      {open && (
        <div
          role="menu"
          data-testid="node-action-menu-popup"
          style={{
            position: "absolute",
            top: 42,
            right: 0,
            background: "var(--bg-card-2)",
            borderRadius: 12,
            padding: 6,
            minWidth: 240,
            boxShadow:
              "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
            zIndex: 10,
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
      )}
    </div>
  );
}
