// One-view ARMA-GARCH result dashboard.
//
// Replaces the nine-tab pill strip of ArmaGarchResultCard: every section is
// rendered at once as a stacked, scannable dashboard so the whole result reads
// in a single pass inside the graph node drawer. Statistical labelling
// invariants are preserved verbatim (sequential is never called joint, the 5%
// quantile is never called VaR, no composite IC, plug-in intervals disclaimed).

import {
  CandidateTable,
  numberText,
  object,
  rows,
  text,
  type ArmaGarchArtifacts,
  type JsonObject,
} from "./ArmaGarchResultCard";

import { ArmaGarchChartGallery } from "./ArmaGarchChartGallery";
import type { ArmaGarchCharts } from "./useArmaGarchCharts";

type Props = { artifacts: ArmaGarchArtifacts | undefined; charts?: ArmaGarchCharts };

const DIMENSION_LABELS: Record<string, string> = {
  data_readiness: "Data readiness",
  mean_adequacy: "Mean adequacy",
  volatility_adequacy: "Volatility adequacy",
  distribution_adequacy: "Distribution adequacy",
  forecast_validation: "Forecast validation",
  volatility_value_added: "Volatility value added",
};

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="ios-group" aria-label={title} style={{ marginTop: 14 }}>
      <div className="panel-heading compact-heading">
        <h4 className="subhead">{title}</h4>
      </div>
      {children}
    </section>
  );
}

function AcceptanceChips({ dimensions }: { dimensions: JsonObject }) {
  const entries = Object.entries(dimensions);
  if (entries.length === 0) return null;
  return (
    <div
      data-testid="arma-garch-acceptance-chips"
      style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}
    >
      {entries.map(([key, value]) => {
        const status = text(object(value).status);
        return (
          <span key={key} className="badge badge-neutral" title={status}>
            {DIMENSION_LABELS[key] ?? key.replace(/_/g, " ")}: {status}
          </span>
        );
      })}
    </div>
  );
}

export function ArmaGarchDashboard({ artifacts, charts }: Props) {
  if (!artifacts?.report) return null;
  const report = artifacts.report;
  const semantics = object(report.estimation_semantics);
  const sample = object(report.sample);
  const scale = object(report.scale);
  const acceptance = object(report.acceptance);
  const dimensions = object(acceptance.dimensions);
  const next = artifacts.nextForecast ?? {};
  const meanCandidates = rows(artifacts.meanCandidates?.candidates);
  const volatilityCandidates = rows(artifacts.volatilityCandidates?.searches).flatMap((search) =>
    rows(search.candidates),
  );
  const comparison = artifacts.comparison ?? {};
  const comparisonAvailable = artifacts.comparison !== undefined;
  const comparisonMain = object(comparison.arma_garch);
  const comparisonBaseline = object(comparison.arma_only);
  const intervalLabel =
    next.predictive_interval === "plugin_conditional"
      ? "plug-in conditional"
      : text(next.predictive_interval).replace(/_/g, " ");
  const semanticsLabel =
    semantics.joint_likelihood === true
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

      <Block title="Overview">
        <p>
          <strong>{text(report.answer)}</strong>
        </p>
        <p>
          {semanticsLabel} · {text(scale.transform)} · {text(scale.lag_unit)}
        </p>
        <AcceptanceChips dimensions={dimensions} />
        <dl className="summary-list">
          <div>
            <dt>Source / train / validation</dt>
            <dd>
              {text(sample.source_n)} / {text(sample.training_n)} / {text(sample.validation_n)}
            </dd>
          </div>
          <div>
            <dt>Next conditional mean</dt>
            <dd>{numberText(next.conditional_mean)}</dd>
          </div>
          <div>
            <dt>Next conditional volatility</dt>
            <dd>{numberText(next.conditional_volatility)}</dd>
          </div>
        </dl>
        {artifacts.nextForecast === undefined ? (
          <p className="ios-hint">Next-forecast artifact is unavailable.</p>
        ) : (
          next.target_time == null && (
            <p className="ios-hint">
              Next observation time is unknown because a future timestamp was not safely inferable.
            </p>
          )
        )}
        {artifacts.nextForecast !== undefined && (
          <p className="ios-hint">
            Intervals are {intervalLabel} and exclude parameter uncertainty. No original-scale
            variance is claimed.
          </p>
        )}
      </Block>

      <Block title="Data &amp; Transformation">
        <dl className="summary-list">
          <div>
            <dt>Columns</dt>
            <dd>
              {text(artifacts.contract?.time_column)} → {text(artifacts.contract?.value_column)}
            </dd>
          </div>
          <div>
            <dt>Time semantics</dt>
            <dd>{text(artifacts.contract?.time_index_semantics)}</dd>
          </div>
          <div>
            <dt>Confirmed transform</dt>
            <dd>{text(artifacts.contract?.transform)}</dd>
          </div>
          <div>
            <dt>Source unchanged</dt>
            <dd>{artifacts.dataAudit?.source_unchanged === true ? "Yes" : "Not verified"}</dd>
          </div>
        </dl>
      </Block>

      <Block title="Mean Model Selection">
        <CandidateTable candidates={meanCandidates} kind="mean" />
      </Block>

      <Block title="Volatility Selection">
        <CandidateTable candidates={volatilityCandidates} kind="variance" />
      </Block>

      <Block title="Diagnostics">
        <dl className="summary-list">
          <div>
            <dt>Normality p-value</dt>
            <dd>{numberText(object(artifacts.diagnostics?.normality).p_value)}</dd>
          </div>
          <div>
            <dt>ARCH-LM p-value</dt>
            <dd>{numberText(object(artifacts.diagnostics?.arch_lm).p_value)}</dd>
          </div>
          <div>
            <dt>Warnings</dt>
            <dd>
              {Array.isArray(report.warnings)
                ? report.warnings.map(text).join(", ") || "None"
                : "None"}
            </dd>
          </div>
        </dl>
      </Block>

      <Block title="Forecast Validation">
        <dl className="summary-list">
          <div>
            <dt>Successful origins</dt>
            <dd>
              {text(artifacts.metrics?.successful_forecast_n)} /{" "}
              {text(artifacts.metrics?.validation_n)}
            </dd>
          </div>
          <div>
            <dt>RMSE</dt>
            <dd>{numberText(artifacts.metrics?.rmse)}</dd>
          </div>
          <div>
            <dt>Pinball loss</dt>
            <dd>{numberText(artifacts.metrics?.pinball_loss)}</dd>
          </div>
          <div>
            <dt>Interval coverage</dt>
            <dd>{numberText(artifacts.metrics?.interval_coverage)}</dd>
          </div>
        </dl>
      </Block>

      <Block title="Conditional Volatility">
        <p>
          {Array.isArray(artifacts.conditionalSeries?.volatility)
            ? `${artifacts.conditionalSeries.volatility.filter((value) => typeof value === "number").length} aligned finite volatility observations are available in the structured chart artifact.`
            : "Conditional volatility is unavailable."}
        </p>
      </Block>

      <Block title="ARMA vs ARMA-GARCH">
        {comparisonAvailable ? (
          <>
            <p>
              {text(comparison.comparison_validation_n)} common successful origins; transform,
              split, ARMA order, origins, and refit cadence are locked.
            </p>
            <table className="preview-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>ARMA-GARCH</th>
                  <th>ARMA only</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>RMSE</td>
                  <td>{numberText(comparisonMain.rmse)}</td>
                  <td>{numberText(comparisonBaseline.rmse)}</td>
                </tr>
                <tr>
                  <td>Pinball loss</td>
                  <td>{numberText(comparisonMain.pinball_loss)}</td>
                  <td>{numberText(comparisonBaseline.pinball_loss)}</td>
                </tr>
              </tbody>
            </table>
          </>
        ) : (
          <p>ARMA-only comparison artifact is unavailable; no locked-comparison claim is made.</p>
        )}
      </Block>

      {charts && (
        <Block title="Evidence charts">
          <ArmaGarchChartGallery charts={charts} />
        </Block>
      )}

      <Block title="Reproducibility">
        <dl className="summary-list">
          <div>
            <dt>Artifact manifest</dt>
            <dd>{text(artifacts.artifactManifest?.status)}</dd>
          </div>
          <div>
            <dt>Structured artifacts before manifest</dt>
            <dd>{text(artifacts.artifactManifest?.artifact_count_before_manifest)}</dd>
          </div>
          <div>
            <dt>Contract hash</dt>
            <dd className="mono">Stored in every ts.* artifact</dd>
          </div>
        </dl>
      </Block>
    </section>
  );
}
