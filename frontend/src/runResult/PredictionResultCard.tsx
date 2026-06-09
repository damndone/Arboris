export interface PredictionResultData {
  schema_version: number;
  model_id: string;
  model_type: string;
  engine: string;
  status: string;
  nobs: number;
  input_columns: { y: string; x: string[] };
  cv_folds: number;
  sampling_method: string | null;
  metrics: { test_r2: number | null; test_rmse: number | null; cv_r2_mean: number | null };
  warnings: string[];
}

function fmt(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(3);
}

export function PredictionResultCard(props: { result: PredictionResultData | undefined }) {
  const r = props.result;
  if (!r) return null;
  return (
    <section className="ios-card prediction-result" aria-label="Prediction result">
      <div className="ios-card-title">🔮 预测 / ML — {r.model_type}</div>
      <ul className="ios-metric-list">
        <li><span>Test R²</span><strong>{fmt(r.metrics.test_r2)}</strong></li>
        <li><span>Test RMSE</span><strong>{fmt(r.metrics.test_rmse)}</strong></li>
        <li><span>CV R² (mean, {r.cv_folds}-fold)</span><strong>{fmt(r.metrics.cv_r2_mean)}</strong></li>
        {r.sampling_method && <li><span>Sampling</span><strong>{r.sampling_method}</strong></li>}
      </ul>
      {r.warnings.map((w) => <div key={w} className="ios-warning">⚠️ {w}</div>)}
    </section>
  );
}
