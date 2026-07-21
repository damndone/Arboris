// Loader for the pack's `ts.chart.*` artifacts.
//
// Kept separate from useArmaGarchArtifacts because the chart payloads are the
// bulky ones (thousands of rows each) and only the dashboard's chart gallery
// needs them. Splitting the fetch keeps the conclusion sections rendering
// immediately instead of waiting on series data.

import { useEffect, useState } from "react";
import { fetchArtifactJson, fetchRunArtifacts, type ArtifactGroup } from "../api";

export const ARMA_GARCH_CHART_IDS = {
  seriesTransform: "ts.chart.series_transform",
  acf: "ts.chart.acf",
  pacf: "ts.chart.pacf",
  residualSeries: "ts.chart.residual_series",
  residualAcf: "ts.chart.residual_acf",
  squaredResidualAcf: "ts.chart.squared_residual_acf",
  qq: "ts.chart.qq",
  conditionalVolatility: "ts.chart.conditional_volatility",
  rollingInterval: "ts.chart.rolling_interval",
  quantileExceptions: "ts.chart.quantile_exceptions",
  modelComparison: "ts.chart.model_comparison",
  absReturnVsVolatility: "ts.chart.abs_return_vs_volatility",
  inSampleIntervalComparison: "ts.chart.in_sample_interval_comparison",
} as const;

export type ArmaGarchChartKey = keyof typeof ARMA_GARCH_CHART_IDS;
export type ArmaGarchCharts = Partial<
  Record<ArmaGarchChartKey, Record<string, unknown> | undefined>
>;

export function useArmaGarchCharts(
  projectRoot: string | null | undefined,
  runId: string | null | undefined,
  /** Pass an already-loaded artifact list to avoid a second listing request. */
  knownGroups?: ArtifactGroup[],
): ArmaGarchCharts | undefined {
  const [charts, setCharts] = useState<ArmaGarchCharts | undefined>(undefined);

  useEffect(() => {
    if (!projectRoot || !runId) {
      setCharts(undefined);
      return;
    }
    let cancelled = false;

    const listing = knownGroups
      ? Promise.resolve({ groups: knownGroups })
      : fetchRunArtifacts(projectRoot, runId);
    listing
      .then(async (value) => {
        const artifactIds = new Set(
          value.groups.flatMap((group) => group.items.map((item) => item.artifact_id)),
        );
        const entries = await Promise.all(
          Object.entries(ARMA_GARCH_CHART_IDS).map(async ([key, artifactId]) => {
            if (!artifactIds.has(artifactId)) return [key, undefined] as const;
            try {
              const envelope = await fetchArtifactJson<{ payload?: Record<string, unknown> }>(
                projectRoot,
                runId,
                artifactId,
              );
              return [key, envelope?.payload] as const;
            } catch {
              return [key, undefined] as const;
            }
          }),
        );
        if (!cancelled) setCharts(Object.fromEntries(entries) as ArmaGarchCharts);
      })
      .catch(() => {
        if (!cancelled) setCharts(undefined);
      });

    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, knownGroups]);

  return charts;
}
