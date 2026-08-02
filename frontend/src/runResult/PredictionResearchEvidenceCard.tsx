import type { PredictionResearchEvidence } from "../api";

function fmt(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—";
}

export function PredictionResearchEvidenceCard(props: {
  evidence: PredictionResearchEvidence | null | undefined;
}) {
  const evidence = props.evidence;
  if (!evidence) return null;
  if (evidence.status !== "validated") {
    return (
      <section className="ios-card prediction-result" aria-label="Prediction research evidence unavailable">
        <div className="ios-card-title">🔒 Predictive research evidence</div>
        <p className="ios-warning">Evidence packets are unavailable or failed contract validation.</p>
      </section>
    );
  }
  const oosMetrics = evidence.oos?.metrics ?? {};
  const baselineMetrics = evidence.baseline?.metrics ?? {};
  const structure = evidence.structure?.kind ?? "unknown";
  const split = evidence.split_parameters ?? {};
  return (
    <section className="ios-card prediction-result" aria-label="Prediction research evidence">
      <div className="ios-card-title">🧪 Predictive research — {evidence.model_id ?? "model"}</div>
      <ul className="ios-metric-list">
        <li><span>Data structure</span><strong>{structure}</strong></li>
        <li><span>Final OOS R²</span><strong>{fmt(oosMetrics.r2)}</strong></li>
        <li><span>Final OOS RMSE</span><strong>{fmt(oosMetrics.rmse)}</strong></li>
        <li><span>Baseline R²</span><strong>{fmt(baselineMetrics.r2)}</strong></li>
        <li><span>Final holdout n</span><strong>{evidence.oos?.n ?? "—"}</strong></li>
        <li><span>Split seed</span><strong>{String(split.random_seed ?? "—")}</strong></li>
        <li><span>Controls</span><strong>{evidence.controls?.length ?? 0} receipt(s)</strong></li>
      </ul>
      {(evidence.limits ?? []).map((limit) => (
        <div key={limit} className="ios-warning">Limit: {limit}</div>
      ))}
    </section>
  );
}
