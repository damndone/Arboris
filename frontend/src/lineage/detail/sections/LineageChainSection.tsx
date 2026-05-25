// frontend/src/lineage/detail/sections/LineageChainSection.tsx
//
// V1.5.0 lineage chain (Step 6, T6.5). Always renders (registry order 50).
// Subsumes V1.4.1 LineageTab's "Copy path" button. V1.5.0 simplification:
// the chain is rendered as a single mono-font line; richer node-strip
// visualisation is deferred to V1.5.1.

import { useState } from "react";
import { useLineage } from "../../LineageContext";
import { buildBranchPath } from "../../pathBuilder";
import type { GraphViewNode } from "../../api/graphViewTypes";

export function LineageChainSection({ node }: { node: GraphViewNode }) {
  const { model } = useLineage();
  // buildBranchPath always returns at least the target's own display for
  // any valid node — empty string only for unknown ids. "Isolated" means
  // no upstream edges; the chain would be just the target itself, which
  // is not really a path.
  const hasUpstream = model.edges.some((e) => e.target === node.id);
  const path = hasUpstream ? buildBranchPath(model, node.id) : "";
  const [flash, setFlash] = useState(false);

  const copy = async () => {
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      setFlash(true);
      setTimeout(() => setFlash(false), 1500);
    } catch {
      // Clipboard API can throw in unfocused iframes / insecure contexts.
      // Surface nothing — user can retry; no console spam.
    }
  };

  return (
    <section
      aria-label="Lineage path"
      data-testid="lineage-chain-section"
      style={{ marginTop: 18 }}
    >
      <div
        className="ln-section-label"
        style={{ marginBottom: 6, display: "flex", alignItems: "center" }}
      >
        <span>Lineage path</span>
        <button
          type="button"
          onClick={copy}
          disabled={!path}
          aria-label="Copy lineage path"
          style={{
            marginLeft: "auto",
            border: 0,
            background: "transparent",
            color: flash ? "var(--green)" : "var(--tint)",
            cursor: path ? "pointer" : "not-allowed",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            padding: "2px 6px",
          }}
        >
          {flash ? "✓ copied" : "copy"}
        </button>
      </div>
      <div
        data-testid="lineage-chain-path"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          color: "var(--label-secondary)",
          lineHeight: 1.5,
          wordBreak: "break-all",
        }}
      >
        {path || "(no upstream nodes)"}
      </div>
    </section>
  );
}
