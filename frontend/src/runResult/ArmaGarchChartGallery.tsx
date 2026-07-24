// The pack's seventeen chart artifacts, drawn.
//
// Grouped by the question each answers rather than by artifact id, so the
// gallery reads as an argument: is the series usable, is the mean adequate, is
// the volatility model adequate, and did it pay off out of sample.

import { useContext } from "react";
import {
  CorrelogramChart,
  DualAxisChart,
  IntervalBandChart,
  QQChart,
  SeriesChart,
} from "./ArmaGarchCharts";
import {
  ARMA_GARCH_CHART_IDS,
  type ArmaGarchCharts,
  type ArmaGarchChartKey,
} from "./useArmaGarchCharts";
import { LineageContext } from "../lineage/LineageContext";
import { useProjectRootOptional } from "../workbench/ProjectRootContext";

type Row = Record<string, unknown>;

function rowsOf(payload: Record<string, unknown> | undefined): Row[] {
  const value = payload?.rows;
  return Array.isArray(value) ? (value as Row[]) : [];
}

function rowsStatus(payload: Record<string, unknown> | undefined): "ok" | "unavailable" | "malformed" {
  if (payload === undefined) return "unavailable";
  return Array.isArray(payload.rows) ? "ok" : "malformed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function display(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toPrecision(4) : "—";
}

function ModelComparisonSummary({ payload }: { payload: Record<string, unknown> }) {
  const comparison = isRecord(payload.comparison) ? payload.comparison : {};
  const garch = isRecord(comparison.arma_garch) ? comparison.arma_garch : {};
  const arma = isRecord(comparison.arma_only) ? comparison.arma_only : {};
  return (
    <section aria-label="ARMA-GARCH vs ARMA-only validation summary" style={{ marginTop: 12 }}>
      <h6 style={{ margin: "0 0 4px", fontSize: 12 }}>ARMA-GARCH vs ARMA-only validation summary</h6>
      <table style={{ fontSize: 12, borderCollapse: "collapse" }}>
        <thead><tr><th>metric</th><th>ARMA-GARCH</th><th>ARMA-only</th></tr></thead>
        <tbody>
          {["rmse", "mae", "interval_coverage"].map((metric) => (
            <tr key={metric}>
              <td>{metric}</td><td>{display(garch[metric])}</td><td>{display(arma[metric])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>
        Comparable validation origins: {display(comparison.comparison_validation_n)}. Information
        criteria are not compared across the sequential ARMA-GARCH and ARMA-only strategies.
      </p>
    </section>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 10 }}>
      <h5 className="subhead" style={{ margin: 0, fontSize: 13 }}>
        {title}
      </h5>
      {children}
    </div>
  );
}

export function ArmaGarchChartGallery({
  charts,
  projectRoot: projectRootProp,
  runId: runIdProp,
}: {
  charts: ArmaGarchCharts | undefined;
  projectRoot?: string | null;
  runId?: string | null;
}) {
  const projectRoot = projectRootProp ?? useProjectRootOptional();
  const lineage = useContext(LineageContext);
  const runId = runIdProp ?? lineage?.model.runId ?? null;
  if (!charts) return null;

  const series = rowsOf(charts.seriesTransform);
  const residuals = rowsOf(charts.residualSeries);
  const rolling = rowsOf(charts.rollingInterval);
  const inSample = rowsOf(charts.inSampleIntervalComparison);
  const exceptions = rowsOf(charts.quantileExceptions);
  // The correlogram band scales with the series the correlations came from.
  const seriesN = series.length || null;
  const residualN = residuals.length || null;

  const loadedCount = Object.values(charts).filter((payload) => payload !== undefined).length;
  if (loadedCount === 0) return null;
  const rowArtifactKeys = (Object.keys(ARMA_GARCH_CHART_IDS) as ArmaGarchChartKey[])
    .filter((key) => key !== "modelComparison");
  const artifactIssues = rowArtifactKeys.flatMap((key) => {
    const status = rowsStatus(charts[key]);
    return status === "ok"
      ? []
      : [`${ARMA_GARCH_CHART_IDS[key]}: ${status === "unavailable" ? "artifact unavailable" : "malformed rows payload"}`];
  });
  const modelComparisonOk = isRecord(charts.modelComparison?.comparison);
  if (!modelComparisonOk) {
    artifactIssues.push(
      `ts.chart.model_comparison: ${charts.modelComparison === undefined ? "artifact unavailable" : "malformed comparison payload"}`,
    );
  }
  const displayedPanels = loadedCount + (charts.seriesTransform ? 1 : 0);
  const ai = (key: ArmaGarchChartKey) => ({
    artifactId: ARMA_GARCH_CHART_IDS[key],
    payload: charts[key] ?? {},
    projectRoot,
    runId,
  });

  return (
    <div data-testid="arma-garch-chart-gallery">
      <p className="muted" style={{ fontSize: 12, margin: "6px 0" }}>
        {loadedCount} chart artifacts loaded · {displayedPanels} displayed panels
      </p>
      {artifactIssues.length ? (
        <div role="status" style={{ fontSize: 12 }}>
          {artifactIssues.map((issue) => <div key={issue}>{issue}</div>)}
        </div>
      ) : null}
      <Group title="Series and transform">
        <SeriesChart title="Source series" rows={series} valueKey="source_value" ai={ai("seriesTransform")} />
        <SeriesChart
          title="Transformed series (the modelled quantity)"
          rows={series}
          valueKey="transformed_value"
          zeroLine
          ai={ai("seriesTransform")}
        />
        <CorrelogramChart title="ACF of the transformed series" rows={rowsOf(charts.acf)} observationCount={seriesN} ai={ai("acf")} />
        <CorrelogramChart title="PACF of the transformed series" rows={rowsOf(charts.pacf)} observationCount={seriesN} ai={ai("pacf")} />
      </Group>

      <Group title="Mean model adequacy">
        <SeriesChart title="Mean-model residuals" rows={residuals} valueKey="value" zeroLine ai={ai("residualSeries")} />
        <CorrelogramChart
          title="Residual ACF (should sit inside the band)"
          rows={rowsOf(charts.residualAcf)}
          observationCount={residualN}
          ai={ai("residualAcf")}
        />
        <CorrelogramChart
          title="Residual PACF (should sit inside the band)"
          rows={rowsOf(charts.residualPacf)}
          observationCount={residualN}
          ai={ai("residualPacf")}
        />
        <SeriesChart
          title="Squared mean-model residuals (volatility clustering, before GARCH)"
          rows={rowsOf(charts.squaredResidualSeries)}
          valueKey="value"
          ai={ai("squaredResidualSeries")}
        />
        <CorrelogramChart
          title="Squared-residual ACF (spikes here motivate the volatility model)"
          rows={rowsOf(charts.squaredResidualAcf)}
          observationCount={residualN}
          ai={ai("squaredResidualAcf")}
        />
      </Group>

      <Group title="Volatility model adequacy">
        <SeriesChart
          title="Conditional volatility (sd_t)"
          rows={rowsOf(charts.conditionalVolatility)}
          valueKey="conditional_volatility"
          color="#f55"
          ai={ai("conditionalVolatility")}
        />
        <SeriesChart
          title="Conditional variance (h_t)"
          rows={rowsOf(charts.conditionalVariance)}
          valueKey="conditional_variance"
          color="#f55"
          ai={ai("conditionalVariance")}
        />
        <SeriesChart
          title="Standardized residuals (should look like white noise)"
          rows={rowsOf(charts.standardizedResidualSeries)}
          valueKey="standardized_residual"
          zeroLine
          ai={ai("standardizedResidualSeries")}
        />
        <SeriesChart
          title="Squared standardized residuals (clustering should be gone)"
          rows={rowsOf(charts.squaredStandardizedResidualSeries)}
          valueKey="squared_standardized_residual"
          ai={ai("squaredStandardizedResidualSeries")}
        />
        <DualAxisChart
          title="Absolute move against conditional volatility"
          rows={rowsOf(charts.absReturnVsVolatility)}
          leftKey="abs_value"
          rightKey="conditional_volatility"
          leftLabel="|observed|"
          rightLabel="conditional volatility"
          ai={ai("absReturnVsVolatility")}
        />
        <QQChart title="Standardized-residual QQ plot" rows={rowsOf(charts.qq)} ai={ai("qq")} />
      </Group>

      <Group title="Interval behaviour">
        <IntervalBandChart
          title="In-sample 95% intervals: ARMA-GARCH vs ARMA-only"
          rows={inSample}
          observedKey="observed"
          bands={[
            { lowerKey: "garch_lower", upperKey: "garch_upper", color: "#4a6cf7", label: "ARMA-GARCH" },
            { lowerKey: "arma_lower", upperKey: "arma_upper", color: "#8e8e93", label: "ARMA-only" },
          ]}
          ai={ai("inSampleIntervalComparison")}
        />
        <IntervalBandChart
          title="Rolling one-step validation intervals"
          rows={rolling}
          observedKey="observed_value"
          bands={[
            { lowerKey: "lower_bound", upperKey: "upper_bound", color: "#4a6cf7", label: "plug-in conditional" },
          ]}
          markKey="quantile_exception"
          ai={ai("rollingInterval")}
        />
        <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
          {rowsStatus(charts.quantileExceptions) === "ok"
            ? exceptions.length === 0
              ? `No lower-quantile exceptions were observed across ${rolling.length} validation origins. `
              : `${exceptions.length} of ${rolling.length} validation origins fell below the lower conditional quantile. `
            : "Quantile-exception count unavailable. "}
          This is a conditional quantile, not a Value-at-Risk figure. Intervals are plug-in and
          exclude parameter uncertainty.
        </p>
        {modelComparisonOk ? <ModelComparisonSummary payload={charts.modelComparison!} /> : null}
      </Group>
    </div>
  );
}
