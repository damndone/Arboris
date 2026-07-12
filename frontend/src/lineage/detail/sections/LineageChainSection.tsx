// frontend/src/lineage/detail/sections/LineageChainSection.tsx
//
// V1.5.2 P6 — clickable chip strip (Plan §9 Layer 2). Always renders
// (registry order 50). Subsumes V1.4.1 LineageTab's "Copy path".
//
// Each chip in the chain is interactive:
//   - left-click → open/activate the chip's tab via useLineage().select
//   - right-click → opens the workbench context menu (Pin upstream,
//     Focus upstream, Copy lineage path, Ask AI about path, ...)
//
// When the WorkbenchStateProvider is absent (legacy bare-mount tests),
// right-click degrades silently and chip click still falls through to
// `select(nodeKey)` so V1.5.0 behaviour is preserved.

import { useState } from "react";
import { useLineage } from "../../LineageContext";
import { buildRunSnapshot } from "../../../workbench/RunSnapshotAdapter";
import { useWorkbenchOptional } from "../../../workbench/WorkbenchStateProvider";
import { buildBranchPath } from "../../pathBuilder";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { formatUpstreamPath, separatorAfter } from "../../api/pathFormat";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";

interface ChainItem {
  nodeKey: string;
  title: string;
  summary?: string;
  /** v1.6.11 — same depth = parallel branch (rendered "+" not "→"). */
  depth?: number;
}

export function LineageChainSection({ node }: { node: GraphViewNode }) {
  const { model, select } = useLineage();
  const wb = useWorkbenchOptional();
  const resolvedContext = useResolvedNodeOperationContext();
  const [flash, setFlash] = useState(false);

  // Build the chip strip from RunSnapshotAdapter so semantics (parent
  // tie-break, depth cap) match canvas highlight + AI scope. Falls
  // back to "(no upstream)" when the node has no incoming edges.
  const snapshot = buildRunSnapshot(model);
  const contextChain: ChainItem[] | null = resolvedContext?.ok
    ? resolvedContext.context.lineage_context.upstream_path.map((pathNode) => ({
        nodeKey: pathNode.key,
        title: pathNode.label,
        summary: pathNode.label,
        depth: pathNode.depth,
      }))
    : resolvedContext
      ? []
      : null;
  const chain: ChainItem[] =
    contextChain ?? snapshot.lineagePathTo(node.nodeKey);
  // lineagePathTo always includes the target as the last element.
  // For visualisation we still want it (so the chip strip ends on
  // "you are here") but disable click on the active node.
  const hasUpstream = chain.length > 1;
  // Copy uses pathBuilder so the copied string matches V1.5.0's
  // "raw.csv → log_income [DP: …]" enriched format. Chip click uses
  // lineagePathTo's pure node-id chain.
  const copyTarget = hasUpstream
    ? contextChain
      ? formatUpstreamPath(
          contextChain.map((pathNode) => ({ label: pathNode.title, depth: pathNode.depth })),
        )
      : buildBranchPath(model, node.id)
    : "";

  const copy = async () => {
    if (!copyTarget) return;
    try {
      await navigator.clipboard.writeText(copyTarget);
      setFlash(true);
      setTimeout(() => setFlash(false), 1500);
    } catch {
      /* clipboard may throw in unfocused iframes — silent retry-friendly */
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
          disabled={!copyTarget}
          aria-label="Copy lineage path"
          style={{
            marginLeft: "auto",
            border: 0,
            background: "transparent",
            color: flash ? "var(--green)" : "var(--tint)",
            cursor: copyTarget ? "pointer" : "not-allowed",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            padding: "2px 6px",
          }}
        >
          {flash ? "✓ copied" : "copy"}
        </button>
      </div>
      {hasUpstream ? (
        <div
          data-testid="lineage-chain-chips"
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
          }}
        >
          {chain.map((n, i) => (
            <div
              key={n.nodeKey}
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <button
                type="button"
                data-testid={`lineage-chip-${n.nodeKey}`}
                data-active={n.nodeKey === node.nodeKey ? "true" : undefined}
                onClick={() => {
                  if (n.nodeKey === node.nodeKey) return;
                  select(n.nodeKey);
                }}
                onContextMenu={(e) => {
                  if (!wb) return;
                  e.preventDefault();
                  wb.dispatch.openContextMenu({
                    nodeKey: n.nodeKey,
                    x: e.clientX,
                    y: e.clientY,
                  });
                }}
                style={{
                  padding: "3px 8px",
                  borderRadius: 6,
                  border: "1px solid var(--separator)",
                  background:
                    n.nodeKey === node.nodeKey
                      ? "var(--tint-bg, rgba(10,132,255,0.12))"
                      : "var(--bg-card-2, transparent)",
                  color:
                    n.nodeKey === node.nodeKey
                      ? "var(--tint, #0a84ff)"
                      : "var(--label)",
                  cursor: n.nodeKey === node.nodeKey ? "default" : "pointer",
                  fontSize: 11,
                  fontFamily: "var(--font-mono)",
                  fontWeight: n.nodeKey === node.nodeKey ? 600 : 400,
                }}
                title={n.title}
              >
                {/* Display precedence matches pathBuilder.nodeDisplay:
                 *  summary first (richer), fallback to title. Keeps chip
                 *  labels aligned with what "Copy lineage path" writes. */}
                {n.summary && n.summary.trim() ? n.summary : n.title}
              </button>
              {i < chain.length - 1 && (
                <span
                  aria-hidden
                  data-testid={`lineage-sep-${i}`}
                  style={{ color: "var(--label-tertiary)", fontSize: 11 }}
                >
                  {/* v1.6.11 — "+" between parallel siblings (same depth),
                   *  "→" only for real dependency steps. */}
                  {separatorAfter(chain, i)}
                </span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div
          data-testid="lineage-chain-empty"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--label-tertiary)",
          }}
        >
          (no upstream nodes)
        </div>
      )}
    </section>
  );
}
