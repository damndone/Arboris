// The chart gallery draws the pack's persisted `ts.chart.*` payloads.
//
// Row shapes here are copied from a real VIXCLS run's artifacts, not invented,
// so a rename on the backend fails these tests instead of silently producing
// blank charts.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArmaGarchChartGallery } from "./ArmaGarchChartGallery";
import type { ArmaGarchCharts } from "./useArmaGarchCharts";

function seriesRows(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    row_id: `source-row:${i}`,
    time: `2020-01-${(i % 28) + 1}`,
    source_value: 20 + Math.sin(i / 3),
    transformed_value: Math.cos(i / 3),
  }));
}

function correlogramRows() {
  return Array.from({ length: 10 }, (_, i) => ({ lag: i, value: 0.5 / (i + 1) }));
}

function rollingRows(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    forecast_origin: i,
    observed_value: Math.sin(i / 4),
    lower_bound: -2,
    upper_bound: 2,
    quantile_exception: i % 25 === 0,
  }));
}

const CHARTS: ArmaGarchCharts = {
  seriesTransform: { rows: seriesRows(2541) },
  acf: { rows: correlogramRows() },
  pacf: { rows: correlogramRows() },
  residualSeries: {
    rows: Array.from({ length: 300 }, (_, i) => ({ position: i, value: Math.sin(i) })),
  },
  residualAcf: { rows: correlogramRows() },
  squaredResidualAcf: { rows: correlogramRows() },
  qq: {
    rows: Array.from({ length: 300 }, (_, i) => ({
      theoretical_quantile: (i - 150) / 50,
      observed: (i - 150) / 45,
    })),
  },
  conditionalVolatility: {
    rows: Array.from({ length: 300 }, (_, i) => ({
      row_id: `r${i}`,
      time: "2020-01-01",
      conditional_volatility: 5 + (i % 7),
    })),
  },
  rollingInterval: { rows: rollingRows(250) },
  quantileExceptions: { rows: rollingRows(250).filter((row) => row.quantile_exception) },
  absReturnVsVolatility: {
    dual_axis: true,
    rows: Array.from({ length: 300 }, (_, i) => ({
      abs_value: Math.abs(Math.sin(i)),
      conditional_volatility: 5 + (i % 7),
    })),
  },
  inSampleIntervalComparison: {
    rows: Array.from({ length: 300 }, (_, i) => ({
      observed: Math.sin(i),
      conditional_mean: 0,
      garch_lower: -2,
      garch_upper: 2,
      arma_lower: -2.5,
      arma_upper: 2.5,
    })),
  },
};

describe("ArmaGarchChartGallery", () => {
  it("draws every persisted chart family", () => {
    render(<ArmaGarchChartGallery charts={CHARTS} />);

    for (const label of [
      "Source series",
      "Transformed series (the modelled quantity)",
      "ACF of the transformed series",
      "PACF of the transformed series",
      "Mean-model residuals",
      "Residual ACF (should sit inside the band)",
      "Squared-residual ACF (spikes here motivate the volatility model)",
      "Conditional volatility",
      "Absolute move against conditional volatility",
      "Standardized-residual QQ plot",
      "In-sample 95% intervals: ARMA-GARCH vs ARMA-only",
      "Rolling one-step validation intervals",
    ]) {
      expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
    }
  });

  it("says so when a long series is thinned rather than showing it as complete", () => {
    render(<ArmaGarchChartGallery charts={CHARTS} />);

    // 2541 source observations exceed the point budget.
    expect(screen.getAllByText(/2541 observations, drawn every/).length).toBeGreaterThan(0);
  });

  it("reports the correlogram significance band it drew", () => {
    render(<ArmaGarchChartGallery charts={CHARTS} />);

    expect(screen.getAllByText(/95% band/).length).toBeGreaterThan(0);
  });

  it("keeps the quantile-exception count honest and refuses the VaR label", () => {
    render(<ArmaGarchChartGallery charts={CHARTS} />);

    expect(screen.getByText(/10 of 250 validation origins/)).toBeInTheDocument();
    expect(screen.getByText(/not a Value-at-Risk figure/)).toBeInTheDocument();
  });

  it("degrades to a stated reason instead of an empty frame", () => {
    render(<ArmaGarchChartGallery charts={{ ...CHARTS, qq: { rows: [] } }} />);

    expect(screen.getByText("Not enough quantile pairs to plot.")).toBeInTheDocument();
  });

  it("renders nothing when the run persisted no chart payloads", () => {
    const { container } = render(<ArmaGarchChartGallery charts={{}} />);

    expect(container).toBeEmptyDOMElement();
  });
});
