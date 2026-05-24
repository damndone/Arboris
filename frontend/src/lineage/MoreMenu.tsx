import { useState } from "react";
import "./tokens/lineage.css";
import type { LineageNode } from "./types";

export interface MoreMenuProps {
  node: LineageNode;
  onShowJson: () => void;
}

export function MoreMenu({ node, onShowJson }: MoreMenuProps) {
  const [open, setOpen] = useState(false);

  const item = (label: string, onClick: () => void, shortcut?: string) => (
    <button
      key={label}
      onClick={() => {
        onClick();
        setOpen(false);
      }}
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
      <span>{label}</span>
      {shortcut && (
        <span
          style={{
            color: "var(--label-tertiary)",
            fontSize: 12,
            fontFamily: "ui-monospace, SF Mono, monospace",
          }}
        >
          {shortcut}
        </span>
      )}
    </button>
  );

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        className="ln-btn-secondary"
        onClick={() => setOpen((o) => !o)}
        aria-label="More"
      >
        More ⌄
      </button>
      {open && (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: 42,
            right: 0,
            background: "var(--bg-card-2)",
            borderRadius: 12,
            padding: 6,
            minWidth: 220,
            boxShadow:
              "0 16px 40px rgba(0,0,0,0.75), 0 0 0 1px var(--separator)",
            zIndex: 10,
          }}
        >
          {item("View raw JSON", onShowJson, "⌘J")}
          {item("Copy node ID", () =>
            navigator.clipboard.writeText(node.id),
          )}
          {item("Copy as JSON", () =>
            navigator.clipboard.writeText(JSON.stringify(node, null, 2)),
          )}
        </div>
      )}
    </div>
  );
}
