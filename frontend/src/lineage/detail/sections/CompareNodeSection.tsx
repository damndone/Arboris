// The drawer for a stored comparison node.
//
// This reads the packet the backend computed when the node was created, not a
// fresh diff: the node exists precisely so the conclusion stays what it was.
// Its two endpoints are named explicitly, because a comparison is only
// meaningful if you can see which runs it read.

import { useState } from "react";
import { ApiError, deleteCompareNode } from "../../../api";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import { useForest } from "../../../workbench/ForestContext";
import type { GraphViewNode } from "../../api/graphViewTypes";

type Endpoint = { run_id?: string; node_id?: string };
type ComparePayload = {
  compare_id?: string;
  relation?: string;
  left?: Endpoint;
  right?: Endpoint;
  packet?: Record<string, unknown>;
};

function comparePayload(node: GraphViewNode): ComparePayload | null {
  const raw = node.raw;
  if (!raw || typeof raw !== "object") return null;
  const compare = (raw as { compare?: unknown }).compare;
  return compare && typeof compare === "object" ? (compare as ComparePayload) : null;
}

export function isCompareNode(node: GraphViewNode): boolean {
  return node.kind === "compare";
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function Findings({ findings }: { findings: unknown }) {
  const items = Array.isArray(findings) ? findings.map(String) : [];
  if (items.length === 0) {
    return <p style={{ fontSize: 12, margin: "4px 0 0" }}>No integrity findings.</p>;
  }
  return (
    <ul style={{ fontSize: 12, margin: "4px 0 0", paddingLeft: 18 }}>
      {items.map((item) => (
        <li key={item} className="mono">
          {item}
        </li>
      ))}
    </ul>
  );
}

function ComparePresentation({ presentation }: { presentation: unknown }) {
  const value = object(presentation);
  if (Object.keys(value).length === 0) return null;
  const sample = object(value.sample_identity);
  const metrics = Array.isArray(value.forecast_metrics) ? value.forecast_metrics : [];
  const specifications = Array.isArray(value.specification_changes)
    ? value.specification_changes
    : [];
  const acceptance = object(value.acceptance);
  return (
    <div data-testid="compare-presentation" style={{ marginTop: 10, fontSize: 12 }}>
      <div className="ln-section-label">Compare summary</div>
      {typeof sample.message === "string" && <p>{sample.message}</p>}
      {specifications.map((item) => <p key={String(item)}>{String(item)}</p>)}
      {metrics.map((item) => {
        const metric = object(item);
        return (
          <p key={String(metric.name)}>
            {String(metric.name)}: {String(metric.before)} → {String(metric.after)}
          </p>
        );
      })}
      {acceptance.before !== undefined && (
        <p>Acceptance: {String(acceptance.before)} → {String(acceptance.after)}</p>
      )}
      {typeof value.conclusion === "string" && <p>{value.conclusion}</p>}
    </div>
  );
}

export function CompareNodeSection({ node }: { node: GraphViewNode }) {
  const projectRoot = useProjectRootOptional();
  const forest = useForest();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);

  const compare = comparePayload(node);
  if (!compare) return null;
  const packet = object(compare.packet);
  // Field names come from ComparePacket.to_dict(); an earlier version of this
  // section guessed them, so a comparison the backend had marked
  // `blocked_by_integrity` rendered as though it had no findings at all.
  const conclusion = object(packet.conclusion_diff);
  const status = typeof packet.compare_status === "string" ? packet.compare_status : null;
  const blocked = status !== null && status !== "complete";
  const safeMessage =
    typeof packet.user_safe_message === "string" ? packet.user_safe_message : null;

  async function remove() {
    if (!projectRoot || !compare?.compare_id) return;
    setBusy(true);
    setError(null);
    try {
      await deleteCompareNode(projectRoot, compare.compare_id);
      forest?.refetch?.();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not remove this comparison.");
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Comparison"
      data-testid="compare-node-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Comparison
      </div>
      <dl className="summary-list">
        <div>
          <dt>Baseline</dt>
          <dd className="mono">{compare.left?.run_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Compared with</dt>
          <dd className="mono">{compare.right?.run_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Relation</dt>
          <dd>
            {compare.relation === "ancestor_descendant"
              ? "the baseline produced the other run"
              : "no lineage relation between these runs"}
          </dd>
        </div>
      </dl>

      {blocked && (
        <p
          className="field-error"
          role="status"
          data-testid="compare-node-blocked"
          style={{ fontSize: 12, marginTop: 8 }}
        >
          <strong>{status}</strong>
          {safeMessage ? ` — ${safeMessage}` : null}
        </p>
      )}

      {conclusion.classification != null ? (
        <p style={{ fontSize: 12, marginTop: 8 }}>
          <strong>{String(conclusion.classification)}</strong>
          {conclusion.reason ? ` — ${String(conclusion.reason)}` : null}
        </p>
      ) : (
        conclusion.reason != null && (
          <p style={{ fontSize: 12, marginTop: 8 }}>{String(conclusion.reason)}</p>
        )
      )}

      <ComparePresentation presentation={packet.presentation} />

      <div style={{ marginTop: 8 }}>
        <div className="ln-section-label">Integrity findings</div>
        <Findings findings={packet.integrity_findings} />
      </div>

      <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center" }}>
        <details onToggle={(event) => setRawOpen(event.currentTarget.open)}>
          <summary>View raw Compare JSON</summary>
          {rawOpen && (
            <pre style={{ maxWidth: 560, overflow: "auto", fontSize: 11 }}>
              {JSON.stringify(packet, null, 2)}
            </pre>
          )}
        </details>
        <button type="button" onClick={() => void remove()} disabled={busy}>
          {busy ? "Removing…" : "Remove comparison"}
        </button>
        {error && (
          <span role="alert" style={{ fontSize: 12, color: "var(--danger, #f55)" }}>
            {error}
          </span>
        )}
      </div>
    </section>
  );
}
