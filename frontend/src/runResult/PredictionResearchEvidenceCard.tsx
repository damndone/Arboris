import type { PredictionResearchEvidence } from "../api";

function fmt(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—";
}

export function PredictionResearchEvidenceCard(props: {
  evidence: PredictionResearchEvidence | null | undefined;
}) {
  const evidence = props.evidence;
  if (!evidence) return null;
  if (evidence.status === "legacy") {
    const legacy = evidence.legacy_artifacts?.[0];
    return (
      <section className="ios-card prediction-result" aria-label="Legacy prediction research evidence">
        <div className="ios-card-title">📜 Legacy predictive research — {evidence.model_id ?? legacy?.model_id ?? "model"}</div>
        <p className="ios-warning">
          {evidence.message ?? "Legacy evaluation — split protocol was not persisted. The result remains readable but is not comparable with v1.8.6 predictive-research results."}
        </p>
        <ul className="ios-metric-list">
          <li><span>Protocol</span><strong>{evidence.protocol ?? "legacy_random_split_v0"}</strong></li>
          <li><span>Validation</span><strong>{evidence.validation ?? "payload_not_evaluated"}</strong></li>
          <li><span>Comparability</span><strong>{evidence.comparability ?? "legacy_only"}</strong></li>
          {legacy?.metrics?.test_r2 !== undefined && (
            <li><span>Historical test R²</span><strong>{fmt(legacy.metrics.test_r2)}</strong></li>
          )}
          {legacy?.metrics?.test_rmse !== undefined && (
            <li><span>Historical test RMSE</span><strong>{fmt(legacy.metrics.test_rmse)}</strong></li>
          )}
        </ul>
      </section>
    );
  }
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
  const controls = evidence.controls ?? [];
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
        <li><span>Controls</span><strong>{controls.length} receipt(s)</strong></li>
      </ul>
      {controls.length > 0 && (
        <ul className="ios-metric-list" data-testid="prediction-control-metrics">
          {controls.map((control, index) => (
            <li key={`${control.control ?? "control"}-${index}`}>
              <span>{control.control ?? "control"}</span>
              <strong>
                {control.status ?? "receipt"}
                {control.metrics?.rmse !== undefined ? ` · RMSE ${fmt(control.metrics.rmse)}` : ""}
              </strong>
            </li>
          ))}
        </ul>
      )}
      {(evidence.limits ?? []).map((limit) => (
        <div key={limit} className="ios-warning">Limit: {limit}</div>
      ))}
    </section>
  );
}
