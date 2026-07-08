// frontend/src/workbench/views/TableView.tsx
//
// v1.6.6 ② — Table result-preview. Switching from the Graph view to Table
// shows a fast read-only preview of what the run PRODUCED:
//   1. model coefficient tables (fetchRunDetail),
//   2. a gallery of every generated figure rendered inline (fetchRunArtifacts
//      + the /runs/{id}/artifacts/{artifact_id} file endpoint),
//   3. download links for the remaining (non-figure) artifacts.
//
// Non-goals: in-table editing, variable-level DAG tabulation (future). The
// SET of figures shown is whatever the run's `visualization` step emitted —
// widening that coverage (violin/pairplot/…) is a backend concern (roadmap
// §3.5 V).

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useLineage } from "../../lineage/LineageContext";
import { useForest } from "../ForestContext";
import { useProjectRootOptional } from "../ProjectRootContext";
import {
  artifactDownloadUrl,
  fetchRunArtifacts,
  fetchRunDetail,
} from "../../api";
import type { ArtifactItem, ModelResult, RunDetail } from "../../api";

/** Run ids look like 20260703_065622_030010_92222fe1 — the last hex segment is
 *  the unique tail, matching the run-rail's short label so the two line up. */
function shortRunId(id: string): string {
  const tail = id.split("_").pop() ?? id;
  return tail.slice(0, 8);
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return String(Number(n.toPrecision(4)));
}

/** "correlation_heatmap" → "Correlation heatmap" for captions/alt text. */
function humanize(id: string): string {
  const s = id.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
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

function FigureCard({
  item,
  projectRoot,
  runId,
}: {
  item: ArtifactItem;
  projectRoot: string;
  runId: string;
}) {
  const label = humanize(item.artifact_id);
  return (
    <figure style={{ margin: 0 }}>
      <img
        src={artifactDownloadUrl(projectRoot, runId, item.artifact_id)}
        alt={`${item.artifact_id} figure`}
        loading="lazy"
        style={{
          width: "100%",
          height: "auto",
          borderRadius: 6,
          border: "1px solid var(--separator)",
          background: "var(--surface, #fff)",
        }}
      />
      <figcaption
        style={{ fontSize: 12, color: "var(--label-secondary)", marginTop: 4 }}
      >
        {label}
      </figcaption>
    </figure>
  );
}

const CONTAINER_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: 24,
  gap: 20,
  height: "100%",
  minHeight: 320,
  overflow: "auto",
};

const FIGURE_GRID: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
  gap: 16,
};

export function TableView({ projectRoot: projectRootProp }: { projectRoot?: string }) {
  const { model } = useLineage();
  const forest = useForest();
  // Follow the active head (the run the graph is highlighting) so the table
  // reflects a freshly forked/executed run and rail-selected runs — not just
  // the URL run. Falls back to the URL run in legacy (no forest context).
  const runId = forest?.activeRunId ?? model.runId;
  const [searchParams] = useSearchParams();
  const contextProjectRoot = useProjectRootOptional();
  const projectRoot = projectRootProp ?? contextProjectRoot ?? searchParams.get("project_root") ?? "";

  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchRunDetail(projectRoot, runId),
      fetchRunArtifacts(projectRoot, runId),
    ])
      .then(([d, a]) => {
        if (cancelled) return;
        setDetail(d);
        setArtifacts(a.groups.flatMap((g) => g.items));
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
  const figures = artifacts.filter((a) => a.artifact_type === "figure");
  const otherArtifacts = artifacts.filter((a) => a.artifact_type !== "figure");
  const isEmpty =
    !loading &&
    !error &&
    models.length === 0 &&
    figures.length === 0 &&
    otherArtifacts.length === 0;

  return (
    <div data-testid="view-table" data-view="table" style={CONTAINER_STYLE}>
      <header
        data-testid="table-view-run-header"
        title={runId}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          paddingBottom: 8,
          borderBottom: "1px solid var(--separator)",
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--label)" }}>
          Results
        </span>
        <span
          style={{
            fontSize: 12,
            fontFamily: "var(--font-mono, monospace)",
            color: "var(--label-secondary)",
          }}
        >
          run {shortRunId(runId)}
        </span>
      </header>

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

      {!loading && !error && figures.length > 0 && (
        <section data-testid="table-view-figures">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>
            Figures ({figures.length})
          </h3>
          <div style={FIGURE_GRID}>
            {figures.map((f) => (
              <FigureCard key={f.artifact_id} item={f} projectRoot={projectRoot} runId={runId} />
            ))}
          </div>
        </section>
      )}

      {!loading && !error && otherArtifacts.length > 0 && (
        <section data-testid="table-view-artifacts">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Artifacts</h3>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--label-secondary)" }}>
            {otherArtifacts.map((a) => (
              <li key={a.artifact_id} style={{ marginBottom: 2 }}>
                <a
                  href={artifactDownloadUrl(projectRoot, runId, a.artifact_id)}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "var(--tint, #0a84ff)" }}
                >
                  {a.artifact_id}
                </a>{" "}
                <span style={{ color: "var(--label-tertiary)" }}>· {a.artifact_type}</span>
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
