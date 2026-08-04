// frontend/src/lineage/header/DetailHeader.tsx
//
// DetailDrawer chrome (Step 6, T6.3). Lives OUTSIDE the section registry
// per spec §8.2 — it hosts the dialog's aria-labelledby target and the
// persistent header toolbar. Workspace tabs own node closing, so the header
// does not add a second close affordance beside Actions.
//
// When `onShowJson` is provided the header also mounts NodeActionMenu
// next to the shared window controls — this is the V1.5.0 Step-6 reachability
// path for the 4 actionable items (Step 8 will additionally mount the
// menu on RF node ⋯ affordances). REV-3 F2.

import { useLineage } from "../LineageContext";
import type { ReactNode } from "react";
import type { GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import { resolveOwnerRun } from "../api/graphViewTypes";
import { ResolverFailureState } from "../detail/ResolverFailureState";
import { useResolvedNodeOperationContext } from "../detail/NodeOperationContextProvider";
import { useRerun } from "../detail/RerunContext";
import { NodeActionMenu } from "../graph/NodeActionMenu";

interface DetailHeaderProps {
  node: GraphViewNode;
  /** Legacy callback retained for drawer callers; the tab strip owns closing. */
  onClose: () => void;
  /** When set, the header renders NodeActionMenu and forwards "View Raw JSON". */
  onShowJson?: () => void;
  /** Explicit project root for slug routes that no longer carry ?project_root=. */
  projectRoot?: string;
  /** Shared window controls supplied by the Workbench shell for node panels. */
  windowControls?: ReactNode;
  /** Optional drag handle supplied by a floating panel shell. */
  windowDragHandle?: ReactNode;
}

/** Element id consumed by `<aside aria-labelledby=...>` in DetailDrawer. */
export const DETAIL_HEADER_TITLE_ID = "detail-drawer-title";

export function DetailHeader({
  node,
  onClose: _onClose,
  onShowJson,
  projectRoot,
  windowControls,
  windowDragHandle,
}: DetailHeaderProps) {
  const { model } = useLineage();
  // In the forest, `model.runId` is the URL run, not the run that owns the selected
  // node. Attribute the node to the run a rerun would fork from (active head if it
  // owns the node, else an owning run); fall back to model.runId per-run / legacy.
  const rerun = useRerun();
  const resolvedContext = useResolvedNodeOperationContext();
  const context = resolvedContext?.ok ? resolvedContext.context : null;
  const legacyDisplayRunId =
    resolveOwnerRun((node as HeadSetNode).runs, rerun?.activeRunId) ?? model.runId;
  const displayRunId = context?.ownership.owner_run_id ?? legacyDisplayRunId;
  const ownerResolution = context?.ownership.owner_resolution;
  const warnings = context?.context_diagnostics.warnings ?? [];

  return (
    <div className="dp-head">
      {/* v1.6.7 — persistent action toolbar row: never shares a row with the
          long id, so Actions + window controls are always reachable. */}
      <div
        data-testid="detail-header-toolbar"
        className="detail-header-toolbar"
        style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}
      >
        {windowDragHandle}
        {node.isDraft && node.lifecycleState && (
          <span
            data-testid="detail-header-state-chip"
            data-state={node.lifecycleState}
            style={{
              fontSize: 10,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              fontWeight: 600,
              padding: "2px 7px",
              borderRadius: 6,
              border: "1px solid var(--separator)",
              color: "var(--label-secondary)",
            }}
          >
            {node.lifecycleState}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {onShowJson && (
          <NodeActionMenu
            node={node}
            model={model}
            onShowJson={onShowJson}
            projectRoot={projectRoot}
          />
        )}
        {windowControls}
      </div>

      {/* meta row: kind + id/resolver + owner + warnings, truncates instead of
          pushing the toolbar. */}
      <div
        data-testid="detail-header-meta"
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
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          maxWidth: "100%",
        }}
      >
        <span>{node.kind}</span>
        {resolvedContext && !resolvedContext.ok ? (
          <ResolverFailureState result={resolvedContext} />
        ) : (
          <span
            className="id"
            style={{
              fontFamily: "var(--font-mono)",
              color: "var(--label-secondary)",
              textTransform: "none",
              letterSpacing: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {displayRunId} · {node.nodeKey}
          </span>
        )}
        {ownerResolution && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              color: "var(--label-tertiary)",
              textTransform: "none",
              letterSpacing: 0,
            }}
          >
            {ownerResolution}
          </span>
        )}
        {warnings.map((warning) => (
          <span
            key={warning}
            style={{
              fontFamily: "var(--font-mono)",
              color: "var(--label-tertiary)",
              textTransform: "none",
              letterSpacing: 0,
            }}
          >
            {warning}
          </span>
        ))}
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
