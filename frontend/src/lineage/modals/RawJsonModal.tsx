// frontend/src/lineage/modals/RawJsonModal.tsx
//
// V1.5.0 Raw JSON modal (Step 6, T6.8). Replaces V1.4.1's permanent
// inline Raw JSON footer with a power-user modal opened by:
//   - ⌘J keyboard shortcut (wired in GraphWorkbench at T6.11)
//   - "View Raw JSON" item in NodeActionMenu (T6.9)
//
// Modal is intentionally controlled (open/onClose props) so the wiring
// owner (GraphWorkbench, NodeActionMenu) decides when it appears. The
// modal itself listens for Escape to close — same pattern as V1.4.1
// MoreMenu — so the keyboard hook in the parent only owns the toggle.
//
// Spec §9: NO dangerouslySetInnerHTML (drop the prototype's hand-rolled
// highlighter); pretty-print via JSON.stringify.

import { useEffect, useState } from "react";
import type { GraphViewNode } from "../api/graphViewTypes";

export const RAW_JSON_TITLE_ID = "raw-json-title";

interface RawJsonModalProps {
  /** Controls visibility; modal renders null when false. */
  open: boolean;
  /** Called on Escape, close button, or backdrop click. */
  onClose: () => void;
  /**
   * Node whose .raw payload is shown. Null is tolerated (nothing renders)
   * so callers can pass `selectedNode ?? null` without guarding.
   */
  node: GraphViewNode | null;
}

export function RawJsonModal({ open, onClose, node }: RawJsonModalProps) {
  // Internal Escape listener (modal-scoped). Parent's useGraphKeyboard
  // already forwards Escape → context.select(null); this listener is
  // independent so closing the modal doesn't also clear node selection.
  //
  // REV-3 S1: stopPropagation() is unreliable when both listeners are
  // on the same target (window). Use stopImmediatePropagation() to
  // guarantee the parent's window listener doesn't also fire. The
  // parent (GraphWorkbench) also guards `if (rawJsonOpen) return` —
  // belt-and-braces, since the two parts ship in different commits and
  // could drift.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () =>
      window.removeEventListener("keydown", onKey, { capture: true });
  }, [open, onClose]);

  const [flash, setFlash] = useState(false);

  if (!open || node === null) return null;

  const text = JSON.stringify(node.raw, null, 2);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setFlash(true);
      setTimeout(() => setFlash(false), 1500);
    } catch {
      // Insecure context / unfocused iframe — swallow.
    }
  };

  return (
    <div
      role="dialog"
      aria-labelledby={RAW_JSON_TITLE_ID}
      data-testid="raw-json-modal"
      onClick={(e) => {
        // Backdrop click closes; click inside the card does not (stops
        // propagation in the inner div).
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      <div
        className="ln-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-card-2)",
          width: 640,
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          borderRadius: 14,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "14px 18px 10px",
            borderBottom: "1px solid var(--separator-faint)",
          }}
        >
          <h2
            id={RAW_JSON_TITLE_ID}
            style={{
              margin: 0,
              fontFamily: "var(--font-serif)",
              fontSize: 16,
              fontWeight: 600,
              color: "var(--label)",
            }}
          >
            Raw JSON
          </h2>
          <button
            type="button"
            onClick={copy}
            style={{
              marginLeft: "auto",
              border: 0,
              background: "transparent",
              color: flash ? "var(--green)" : "var(--tint)",
              cursor: "pointer",
              fontSize: 12,
              fontFamily: "var(--font-mono)",
              padding: "4px 8px",
            }}
            aria-label="Copy Raw JSON"
          >
            {flash ? "✓ copied" : "copy"}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              border: 0,
              background: "var(--bg-elev)",
              color: "var(--label-secondary)",
              width: 24,
              height: 24,
              borderRadius: 6,
              cursor: "pointer",
              marginLeft: 8,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ×
          </button>
        </div>
        <pre
          data-testid="raw-json-body"
          style={{
            margin: 0,
            padding: 18,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--label)",
            overflow: "auto",
            background: "var(--bg-canvas)",
          }}
        >
          {text}
        </pre>
      </div>
    </div>
  );
}
