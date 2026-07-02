// frontend/src/workbench/views/TableView.tsx
//
// v1.6.6 ② — Table result-preview. Switching from the Graph view to Table
// shows a fast read-only preview of what the run PRODUCED: model coefficient
// tables + a summary of emitted artifacts (figures/tables/…). It reuses the
// existing run-detail API (fetchRunDetail) rather than the graph view model,
// because coefficients/artifacts live on the run result, not on graph nodes.
//
// Scope (spec §1②): coefficient tables + artifact summary. Non-goals: in-table
// editing, figure thumbnails, variable-level DAG tabulation (future).

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useLineage } from "../../lineage/LineageContext";
import { fetchRunDetail } from "../../api";
import type { ModelResult, RunDetail } from "../../api";

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // Trim to a readable precision without trailing-zero noise.
  return String(Number(n.toPrecision(4)));
}

function CoefficientTable({ model }: { model: ModelResult }) {
  const rows = Object.entries(model.coefficients ?? {});
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label)", marginBottom: 4 }}>
        {model.model_id}
        {model.model_type ? ` · ${model.model_type}` : ""}
      </div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
        {model.nobs !== undefined ? `n=${model.nobs}` : null}
        {model.r_squared != null ? ` · R²=${fmt(model.r_squared)}` : null}
      </div>
      <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
            <th style={{ padding: "2px 8px" }}>term</th>
            <th style={{ padding: "2px 8px" }}>estimate</th>
            <th style={{ padding: "2px 8px" }}>std. error</th>
            <th style={{ padding: "2px 8px" }}>p-value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([term, c]) => (
            <tr key={term} style={{ borderTop: "1px solid var(--separator)" }}>
              <td style={{ padding: "2px 8px", fontFamily: "var(--font-mono, monospace)" }}>{term}</td>
              <td style={{ padding: "2px 8px" }}>{fmt(c.estimate)}</td>
              <td style={{ padding: "2px 8px" }}>{fmt(c.std_error)}</td>
              <td style={{ padding: "2px 8px" }}>{c.p_value_display ?? fmt(c.p_value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CONTAINER_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: 24,
  gap: 16,
  height: "100%",
  minHeight: 320,
  overflow: "auto",
};

export function TableView() {
  const { model } = useLineage();
  const runId = model.runId;
  const [searchParams] = useSearchParams();
  const projectRoot = searchParams.get("project_root") ?? "";

  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRunDetail(projectRoot, runId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, projectRoot]);

  const models = detail?.model_results ?? [];
  const artifactCounts = Object.entries(detail?.artifact_counts ?? {}).filter(
    ([, count]) => count > 0,
  );
  const isEmpty = !loading && !error && models.length === 0 && artifactCounts.length === 0;

  return (
    <div data-testid="view-table" data-view="table" style={CONTAINER_STYLE}>
      {loading && (
        <div data-testid="table-view-loading" style={{ color: "var(--label-secondary)" }}>
          Loading results…
        </div>
      )}

      {error && (
        <div data-testid="table-view-error" style={{ color: "var(--red, #c00)" }}>
          Failed to load results: {error}
        </div>
      )}

      {!loading && !error && models.length > 0 && (
        <section data-testid="table-view-coefficients">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Coefficients</h3>
          {models.map((m) => (
            <CoefficientTable key={m.model_id} model={m} />
          ))}
        </section>
      )}

      {!loading && !error && artifactCounts.length > 0 && (
        <section data-testid="table-view-artifacts">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Artifacts</h3>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--label-secondary)" }}>
            {artifactCounts.map(([type, count]) => (
              <li key={type}>
                {type}: {count}
              </li>
            ))}
          </ul>
        </section>
      )}

      {isEmpty && (
        <div
          data-testid="table-view-empty"
          style={{ color: "var(--label-tertiary)", fontSize: 13 }}
        >
          This run produced no model results or artifacts yet.
        </div>
      )}
    </div>
  );
}
