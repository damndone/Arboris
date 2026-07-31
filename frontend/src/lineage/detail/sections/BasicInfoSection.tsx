// frontend/src/lineage/detail/sections/BasicInfoSection.tsx
//
// V1.5.0 basic info K/V (Step 6, T6.6). Always renders (registry order 60).
// Three rows: Kind, Stage, Created. Locale-aware Created formatting per
// V1.4.1 P2.2 resolution (use new Date(...).toLocaleString()).

import type { GraphViewNode } from "../../api/graphViewTypes";

const STAGE_LABELS: Record<string, string> = {
  source: "Source",
  eda: "EDA",
  clean: "Clean",
  transform: "Transform",
  model: "Model",
  diag: "Diagnostics",
  viz: "Visualization",
  report: "Report",
  unknown: "Unknown stage",
};

function resultRuns(node: GraphViewNode): string[] {
  const runs = (node as GraphViewNode & { runs?: unknown }).runs;
  return Array.isArray(runs) ? runs.filter((run): run is string => typeof run === "string") : [];
}

function humaniseStage(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

function humaniseKind(kind: string): string {
  // Replace snake_case with spaces; keep lowercase to match the editorial
  // aesthetic (uppercase chrome lives only in section headings).
  return kind.replace(/_/g, " ");
}

function formatCreated(iso: string | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function BasicInfoSection({ node }: { node: GraphViewNode }) {
  const isResult = node.stage === "report" && node.title === "Result";
  const runs = resultRuns(node);
  return (
    <section
      aria-label="Basic info"
      data-testid="basic-info-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Basic info
      </div>
      <dl
        className="dp-kv"
        style={{
          display: "grid",
          gridTemplateColumns: "90px 1fr",
          rowGap: 4,
          columnGap: 12,
          fontSize: 12.5,
          margin: 0,
        }}
      >
        <KV label="Kind" value={isResult ? "Result" : humaniseKind(node.kind)} testid="kind" />
        <KV
          label="Stage"
          value={isResult ? "Result" : humaniseStage(node.stage)}
          testid="stage"
        />
        {isResult && <KV label="Run" value={runs.join(", ") || "—"} testid="run" />}
        <KV
          label="Created"
          value={formatCreated(node.createdAt)}
          testid="created"
        />
      </dl>
    </section>
  );
}

function KV({
  label,
  value,
  testid,
}: {
  label: string;
  value: string;
  testid: string;
}) {
  return (
    <>
      <dt
        style={{
          color: "var(--label-tertiary)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
      >
        {label}
      </dt>
      <dd
        data-testid={`basic-info-${testid}`}
        style={{ margin: 0, color: "var(--label)" }}
      >
        {value}
      </dd>
    </>
  );
}
