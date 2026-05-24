// frontend/src/lineage/header/DetailHeader.tsx
//
// DetailDrawer chrome (Step 6, T6.3). Lives OUTSIDE the section registry
// per spec §8.2 — it hosts the dialog's aria-labelledby target and the
// close button, both of which are invariant across node kinds. Section
// changes must not be able to remove it.

import { useLineage } from "../LineageContext";
import type { GraphViewNode } from "../api/graphViewTypes";

interface DetailHeaderProps {
  node: GraphViewNode;
  onClose: () => void;
}

/** Element id consumed by `<aside aria-labelledby=...>` in DetailDrawer. */
export const DETAIL_HEADER_TITLE_ID = "detail-drawer-title";

export function DetailHeader({ node, onClose }: DetailHeaderProps) {
  const { model } = useLineage();

  return (
    <div className="dp-head">
      <div
        className="dp-kind"
        style={{
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          color: "var(--label-tertiary)",
          fontWeight: 600,
          marginBottom: 2,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>{node.kind}</span>
        <span
          className="id"
          style={{
            fontFamily: "var(--font-mono)",
            color: "var(--label-secondary)",
            textTransform: "none",
            letterSpacing: 0,
          }}
        >
          {model.runId} · {node.nodeKey}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          style={{
            marginLeft: "auto",
            border: "none",
            background: "var(--bg-elev)",
            color: "var(--label-secondary)",
            width: 24,
            height: 24,
            borderRadius: 6,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          ×
        </button>
      </div>
      <h2
        id={DETAIL_HEADER_TITLE_ID}
        className="dp-title"
        style={{
          fontFamily: "var(--font-serif)",
          fontSize: 26,
          fontWeight: 600,
          letterSpacing: "-0.015em",
          color: "var(--label)",
          margin: "0 0 0",
          lineHeight: 1.15,
        }}
      >
        {node.title}
      </h2>
      {node.summary && (
        <div
          className="dp-sub"
          style={{
            fontSize: 12,
            color: "var(--label-secondary)",
            marginTop: 4,
            fontFamily: "var(--font-mono)",
          }}
        >
          {node.summary}
        </div>
      )}
    </div>
  );
}
