// The pack's seventeen chart artifacts, drawn.
//
// Grouped by the question each answers rather than by artifact id, so the
// gallery reads as an argument: is the series usable, is the mean adequate, is
// the volatility model adequate, and did it pay off out of sample.

import {
  CorrelogramChart,
  DualAxisChart,
  IntervalBandChart,
  QQChart,
  SeriesChart,
} from "./ArmaGarchCharts";
import type { ArmaGarchCharts } from "./useArmaGarchCharts";

type Row = Record<string, unknown>;

function rowsOf(payload: Record<string, unknown> | undefined): Row[] {
  const value = payload?.rows;
  return Array.isArray(value) ? (value as Row[]) : [];
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

export function ArmaGarchChartGallery({ charts }: { charts: ArmaGarchCharts | undefined }) {
  if (!charts) return null;

  const series = rowsOf(charts.seriesTransform);
  const residuals = rowsOf(charts.residualSeries);
  const rolling = rowsOf(charts.rollingInterval);
  const inSample = rowsOf(charts.inSampleIntervalComparison);
  const exceptions = rowsOf(charts.quantileExceptions);
  // The correlogram band scales with the series the correlations came from.
  const seriesN = series.length || null;
  const residualN = residuals.length || null;

  const anything =
    series.length ||
    residuals.length ||
    rolling.length ||
    inSample.length ||
    rowsOf(charts.acf).length;
  if (!anything) return null;

  return (
    <div data-testid="arma-garch-chart-gallery">
      <Group title="Series and transform">
        <SeriesChart title="Source series" rows={series} valueKey="source_value" />
        <SeriesChart
          title="Transformed series (the modelled quantity)"
          rows={series}
          valueKey="transformed_value"
          zeroLine
        />
        <CorrelogramChart title="ACF of the transformed series" rows={rowsOf(charts.acf)} observationCount={seriesN} />
        <CorrelogramChart title="PACF of the transformed series" rows={rowsOf(charts.pacf)} observationCount={seriesN} />
      </Group>

      <Group title="Mean model adequacy">
        <SeriesChart title="Mean-model residuals" rows={residuals} valueKey="value" zeroLine />
        <CorrelogramChart
          title="Residual ACF (should sit inside the band)"
          rows={rowsOf(charts.residualAcf)}
          observationCount={residualN}
        />
        <SeriesChart
          title="Squared mean-model residuals (volatility clustering, before GARCH)"
          rows={rowsOf(charts.squaredResidualSeries)}
          valueKey="value"
        />
        <CorrelogramChart
          title="Squared-residual ACF (spikes here motivate the volatility model)"
          rows={rowsOf(charts.squaredResidualAcf)}
          observationCount={residualN}
        />
      </Group>

      <Group title="Volatility model adequacy">
        <SeriesChart
          title="Conditional volatility (sd_t)"
          rows={rowsOf(charts.conditionalVolatility)}
          valueKey="conditional_volatility"
          color="#f55"
        />
        <SeriesChart
          title="Conditional variance (h_t)"
          rows={rowsOf(charts.conditionalVariance)}
          valueKey="conditional_variance"
          color="#f55"
        />
        <SeriesChart
          title="Standardized residuals (should look like white noise)"
          rows={rowsOf(charts.standardizedResidualSeries)}
          valueKey="standardized_residual"
          zeroLine
        />
        <SeriesChart
          title="Squared standardized residuals (clustering should be gone)"
          rows={rowsOf(charts.squaredStandardizedResidualSeries)}
          valueKey="squared_standardized_residual"
        />
        <DualAxisChart
          title="Absolute move against conditional volatility"
          rows={rowsOf(charts.absReturnVsVolatility)}
          leftKey="abs_value"
          rightKey="conditional_volatility"
          leftLabel="|observed|"
          rightLabel="conditional volatility"
        />
        <QQChart title="Standardized-residual QQ plot" rows={rowsOf(charts.qq)} />
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
        />
        <IntervalBandChart
          title="Rolling one-step validation intervals"
          rows={rolling}
          observedKey="observed_value"
          bands={[
            { lowerKey: "lower_bound", upperKey: "upper_bound", color: "#4a6cf7", label: "plug-in conditional" },
          ]}
          markKey="quantile_exception"
        />
        <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
          {exceptions.length} of {rolling.length} validation origins fell below the lower
          conditional quantile. This is a conditional quantile, not a Value-at-Risk figure.
          Intervals are plug-in and exclude parameter uncertainty.
        </p>
      </Group>
    </div>
  );
}
