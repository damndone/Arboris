import { useMemo, useState } from "react";

export type JsonObject = Record<string, unknown>;

export type ArmaGarchArtifacts = {
  report?: JsonObject;
  contract?: JsonObject;
  dataAudit?: JsonObject;
  meanCandidates?: JsonObject;
  volatilityCandidates?: JsonObject;
  diagnostics?: JsonObject;
  metrics?: JsonObject;
  nextForecast?: JsonObject;
  comparison?: JsonObject;
  conditionalSeries?: JsonObject;
  artifactManifest?: JsonObject;
};

type Props = { artifacts: ArmaGarchArtifacts | undefined };

const TABS = [
  "Overview",
  "Data & Transformation",
  "Mean Model Selection",
  "Volatility Selection",
  "Diagnostics",
  "Forecast Validation",
  "Conditional Volatility",
  "ARMA vs ARMA-GARCH",
  "Reproducibility",
] as const;
type Tab = (typeof TABS)[number];

export function object(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : {};
}

export function rows(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter((item): item is JsonObject => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

export function numberText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "—";
}

export function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "—";
}

export function CandidateTable({ candidates, kind }: { candidates: JsonObject[]; kind: "mean" | "variance" }) {
  const [status, setStatus] = useState("all");
  const [sortKey, setSortKey] = useState("aicc");
  const visible = useMemo(() => candidates
    .filter((candidate) => status === "all" || (status === "failed") === Boolean(candidate.failure_code))
    .sort((left, right) => {
      const leftValue = typeof left[sortKey] === "number" ? left[sortKey] as number : Number.POSITIVE_INFINITY;
      const rightValue = typeof right[sortKey] === "number" ? right[sortKey] as number : Number.POSITIVE_INFINITY;
      return leftValue - rightValue || text(left.candidate_id).localeCompare(text(right.candidate_id));
    }), [candidates, sortKey, status]);
  return (
    <>
      <div className="control-grid">
        <label>Status <select aria-label={`${kind} candidate status`} value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All</option><option value="successful">Successful</option><option value="failed">Failed</option></select></label>
        <label>Sort <select aria-label={`${kind} candidate sort`} value={sortKey} onChange={(event) => setSortKey(event.target.value)}><option value="aicc">AICc</option><option value="bic">BIC</option><option value="parameter_count">Parameter count</option></select></label>
      </div>
      <div className="preview-table-wrap">
        <table className="preview-table">
          <thead><tr><th>Candidate</th><th>Order</th><th>AICc</th><th>BIC</th><th>Status</th></tr></thead>
          <tbody>{visible.map((candidate) => (
            <tr key={text(candidate.candidate_id)}>
              <td className="mono">{text(candidate.candidate_id)}</td>
              <td>{kind === "mean" ? `(${text(candidate.p)}, ${text(candidate.q)})` : text(candidate.display_name)}</td>
              <td>{numberText(candidate.aicc)}</td>
              <td>{numberText(candidate.bic)}</td>
              <td>{candidate.failure_code ? text(candidate.failure_code) : "eligible"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}

export function ArmaGarchResultCard({ artifacts }: Props) {
  const [tab, setTab] = useState<Tab>("Overview");
  if (!artifacts?.report) return null;
  const report = artifacts.report;
  const semantics = object(report.estimation_semantics);
  const sample = object(report.sample);
  const scale = object(report.scale);
  const acceptance = object(report.acceptance);
  const next = artifacts.nextForecast ?? {};
  const meanCandidates = rows(artifacts.meanCandidates?.candidates);
  const volatilityCandidates = rows(artifacts.volatilityCandidates?.searches)
    .flatMap((search) => rows(search.candidates));
  const comparison = artifacts.comparison ?? {};
  const comparisonAvailable = artifacts.comparison !== undefined;
  const comparisonMain = object(comparison.arma_garch);
  const comparisonBaseline = object(comparison.arma_only);
  const intervalLabel = next.predictive_interval === "plugin_conditional"
    ? "plug-in conditional"
    : text(next.predictive_interval).replace(/_/g, " ");
  const semanticsLabel = semantics.joint_likelihood === true
    ? "Joint likelihood"
    : semantics.joint_likelihood === false
      ? "Sequential two-stage likelihood"
      : "Estimation semantics unavailable";

  return (
    <section className="ios-group" aria-label="ARMA-GARCH result">
      <div className="panel-heading compact-heading">
        <h3 className="subhead">ARMA-GARCH Volatility Workbench</h3>
        <span className="badge badge-neutral">{text(acceptance.overall_status)}</span>
      </div>
      <div role="tablist" className="run-result-tabs">
        {TABS.map((name) => <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>{name}</button>)}
      </div>

      {tab === "Overview" && <div>
        <p><strong>{text(report.answer)}</strong></p>
        <p>{semanticsLabel} · {text(scale.transform)} · {text(scale.lag_unit)}</p>
        <dl className="summary-list">
          <div><dt>Source / train / validation</dt><dd>{text(sample.source_n)} / {text(sample.training_n)} / {text(sample.validation_n)}</dd></div>
          <div><dt>Next conditional mean</dt><dd>{numberText(next.conditional_mean)}</dd></div>
          <div><dt>Next conditional volatility</dt><dd>{numberText(next.conditional_volatility)}</dd></div>
        </dl>
        {artifacts.nextForecast === undefined
          ? <p className="ios-hint">Next-forecast artifact is unavailable.</p>
          : next.target_time == null && <p className="ios-hint">Next observation time is unknown because a future timestamp was not safely inferable.</p>}
        {artifacts.nextForecast !== undefined && <p className="ios-hint">Intervals are {intervalLabel} and exclude parameter uncertainty. No original-scale variance is claimed.</p>}
      </div>}

      {tab === "Data & Transformation" && <dl className="summary-list">
        <div><dt>Columns</dt><dd>{text(artifacts.contract?.time_column)} → {text(artifacts.contract?.value_column)}</dd></div>
        <div><dt>Time semantics</dt><dd>{text(artifacts.contract?.time_index_semantics)}</dd></div>
        <div><dt>Confirmed transform</dt><dd>{text(artifacts.contract?.transform)}</dd></div>
        <div><dt>Source unchanged</dt><dd>{artifacts.dataAudit?.source_unchanged === true ? "Yes" : "Not verified"}</dd></div>
      </dl>}

      {tab === "Mean Model Selection" && <CandidateTable candidates={meanCandidates} kind="mean" />}
      {tab === "Volatility Selection" && <CandidateTable candidates={volatilityCandidates} kind="variance" />}

      {tab === "Diagnostics" && <dl className="summary-list">
        <div><dt>Normality p-value</dt><dd>{numberText(object(artifacts.diagnostics?.normality).p_value)}</dd></div>
        <div><dt>ARCH-LM p-value</dt><dd>{numberText(object(artifacts.diagnostics?.arch_lm).p_value)}</dd></div>
        <div><dt>Warnings</dt><dd>{Array.isArray(report.warnings) ? report.warnings.map(text).join(", ") || "None" : "None"}</dd></div>
      </dl>}

      {tab === "Forecast Validation" && <dl className="summary-list">
        <div><dt>Successful origins</dt><dd>{text(artifacts.metrics?.successful_forecast_n)} / {text(artifacts.metrics?.validation_n)}</dd></div>
        <div><dt>RMSE</dt><dd>{numberText(artifacts.metrics?.rmse)}</dd></div>
        <div><dt>Pinball loss</dt><dd>{numberText(artifacts.metrics?.pinball_loss)}</dd></div>
        <div><dt>Interval coverage</dt><dd>{numberText(artifacts.metrics?.interval_coverage)}</dd></div>
      </dl>}

      {tab === "Conditional Volatility" && <p>
        {Array.isArray(artifacts.conditionalSeries?.volatility)
          ? `${artifacts.conditionalSeries.volatility.filter((value) => typeof value === "number").length} aligned finite volatility observations are available in the structured chart artifact.`
          : "Conditional volatility is unavailable."}
      </p>}

      {tab === "ARMA vs ARMA-GARCH" && <div>
        {comparisonAvailable ? <>
          <p>{text(comparison.comparison_validation_n)} common successful origins; transform, split, ARMA order, origins, and refit cadence are locked.</p>
          <table className="preview-table"><thead><tr><th>Metric</th><th>ARMA-GARCH</th><th>ARMA only</th></tr></thead><tbody><tr><td>RMSE</td><td>{numberText(comparisonMain.rmse)}</td><td>{numberText(comparisonBaseline.rmse)}</td></tr><tr><td>Pinball loss</td><td>{numberText(comparisonMain.pinball_loss)}</td><td>{numberText(comparisonBaseline.pinball_loss)}</td></tr></tbody></table>
        </> : <p>ARMA-only comparison artifact is unavailable; no locked-comparison claim is made.</p>}
      </div>}

      {tab === "Reproducibility" && <dl className="summary-list">
        <div><dt>Artifact manifest</dt><dd>{text(artifacts.artifactManifest?.status)}</dd></div>
        <div><dt>Structured artifacts before manifest</dt><dd>{text(artifacts.artifactManifest?.artifact_count_before_manifest)}</dd></div>
        <div><dt>Contract hash</dt><dd className="mono">Stored in every ts.* artifact</dd></div>
      </dl>}
    </section>
  );
}
