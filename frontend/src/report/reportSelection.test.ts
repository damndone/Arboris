import { describe, expect, it } from "vitest";
import type { CitableFact, FigureFactInput } from "./factTable";
import {
  DEFAULT_REPORT_FIGURE_LIMIT,
  defaultExcludedFigureIds,
  includedReportFacts,
  includedReportFigures,
} from "./reportSelection";

const figures: FigureFactInput[] = [
  { artifact_id: "histograms", chart_type: "histogram", source: null },
  { artifact_id: "coef_plot", chart_type: "coefficient plot", source: null },
  { artifact_id: "residuals_fitted", chart_type: "residuals versus fitted", source: null },
  { artifact_id: "scatter_plots", chart_type: "scatter plot", source: null },
];

describe("report evidence selection", () => {
  it("selects a deterministic, bounded set of high-value figures while preserving the inventory", () => {
    expect(DEFAULT_REPORT_FIGURE_LIMIT).toBeGreaterThan(0);
    expect(defaultExcludedFigureIds(figures, 2)).toEqual([
      "histograms",
      "scatter_plots",
    ]);
    expect(includedReportFigures(figures, ["histograms", "scatter_plots"])).toEqual([
      figures[1],
      figures[2],
    ]);
    expect(figures).toHaveLength(4);
  });

  it("removes figure-derived facts from the model packet without removing lineage facts", () => {
    const facts: CitableFact[] = [
      {
        id: "c1",
        node_key: "model:ols",
        node_label: "OLS",
        field: "coef:age",
        label: "Age estimate",
        value: 1.2,
      },
      {
        id: "c2",
        node_key: "figure:histograms",
        node_label: "Histogram",
        field: "figure:histograms:source.mean",
        label: "Histogram mean",
        value: 2.1,
      },
    ];

    expect(includedReportFacts(facts, [], ["histograms"])).toEqual([facts[0]]);
    expect(includedReportFacts(facts, ["c1"], [])).toEqual([facts[1]]);
    expect(includedReportFacts(facts, ["c1"], ["histograms"])).toEqual([]);
  });
});
