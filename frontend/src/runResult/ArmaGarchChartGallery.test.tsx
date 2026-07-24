// The chart gallery draws the pack's persisted `ts.chart.*` payloads.
//
// Row shapes here are copied from a real VIXCLS run's artifacts, not invented,
// so a rename on the backend fails these tests instead of silently producing
// blank charts.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
  residualPacf: { rows: correlogramRows() },
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
  modelComparison: {
    comparison: {
      comparison_validation_n: 250,
      arma_garch: { rmse: 1.2, mae: 0.8, interval_coverage: 0.96 },
      arma_only: { rmse: 1.6, mae: 1.1, interval_coverage: 0.91 },
      runtime_seconds: { arma_garch: 2.4, arma_only: 0.7 },
    },
  },
  absReturnVsVolatility: {
    dual_axis: true,
    rows: Array.from({ length: 300 }, (_, i) => ({
      abs_value: Math.abs(Math.sin(i)),
      conditional_volatility: 5 + (i % 7),
    })),
  },
  conditionalVariance: {
    rows: Array.from({ length: 300 }, (_, i) => ({
      row_id: `r${i}`,
      time: "2020-01-01",
      conditional_variance: (5 + (i % 7)) ** 2,
    })),
  },
  standardizedResidualSeries: {
    rows: Array.from({ length: 300 }, (_, i) => ({
      row_id: `r${i}`,
      time: "2020-01-01",
      standardized_residual: Math.sin(i),
    })),
  },
  squaredStandardizedResidualSeries: {
    rows: Array.from({ length: 300 }, (_, i) => ({
      row_id: `r${i}`,
      time: "2020-01-01",
      squared_standardized_residual: Math.sin(i) ** 2,
    })),
  },
  squaredResidualSeries: {
    rows: Array.from({ length: 300 }, (_, i) => ({ position: i, value: Math.sin(i) ** 2 })),
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
      "Conditional volatility (sd_t)",
      "Conditional variance (h_t)",
      "Standardized residuals (should look like white noise)",
      "Squared standardized residuals (clustering should be gone)",
      "Squared mean-model residuals (volatility clustering, before GARCH)",
      "Absolute move against conditional volatility",
      "Residual PACF (should sit inside the band)",
      "Standardized-residual QQ plot",
      "In-sample 95% intervals: ARMA-GARCH vs ARMA-only",
      "Rolling one-step validation intervals",
    ]) {
      expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText("ARMA-GARCH vs ARMA-only validation summary")).toBeInTheDocument();
    expect(screen.getByText(/18 chart artifacts loaded · 19 displayed panels/)).toBeInTheDocument();
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

  it("offers numeric-source Ask AI for the inline SVG charts in Table", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ text: "这张图显示了结构化序列证据。" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ArmaGarchChartGallery charts={CHARTS} projectRoot="/proj" runId="run-vix" />);
    fireEvent.click(screen.getByRole("button", { name: "Ask AI about Source series" }));

    expect(await screen.findByText("这张图显示了结构化序列证据。")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/llm/chat"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("workbench_figure_context_v1"),
      }),
    ));
    vi.unstubAllGlobals();
  });

  it("keeps the quantile-exception count honest and refuses the VaR label", () => {
    render(<ArmaGarchChartGallery charts={CHARTS} />);

    expect(screen.getByText(/10 of 250 validation origins/)).toBeInTheDocument();
    expect(screen.getByText(/not a Value-at-Risk figure/)).toBeInTheDocument();
  });

  it("distinguishes a valid zero-exception artifact from unavailable and malformed artifacts", () => {
    const { rerender } = render(
      <ArmaGarchChartGallery charts={{ ...CHARTS, quantileExceptions: { rows: [] } }} />,
    );
    expect(screen.getByText(/No lower-quantile exceptions were observed across 250/)).toBeInTheDocument();

    rerender(<ArmaGarchChartGallery charts={{ ...CHARTS, quantileExceptions: undefined }} />);
    expect(screen.getByText(/ts.chart.quantile_exceptions: artifact unavailable/)).toBeInTheDocument();

    rerender(<ArmaGarchChartGallery charts={{ ...CHARTS, quantileExceptions: { rows: "bad" } }} />);
    expect(screen.getByText(/ts.chart.quantile_exceptions: malformed rows payload/)).toBeInTheDocument();
  });

  it("downloads rendered SVG with an explicit displayed-data description", () => {
    vi.useFakeTimers();
    const createObjectUrl = vi.fn(() => "blob:chart");
    const revokeObjectUrl = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectUrl });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(this.isConnected).toBe(true);
    });
    render(<ArmaGarchChartGallery charts={CHARTS} />);

    fireEvent.click(screen.getByRole("button", { name: "Download Source series SVG" }));

    expect(createObjectUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalled();
    expect(revokeObjectUrl).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:chart");
    click.mockRestore();
    vi.useRealTimers();
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
