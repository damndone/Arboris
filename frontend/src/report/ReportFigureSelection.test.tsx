import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReportFigure } from "./reportClient";
import { ReportFigureSelection } from "./ReportFigureSelection";

const figures: ReportFigure[] = [
  { artifact_id: "histograms", chart_type: "histogram", source: null },
  { artifact_id: "coef_plot", chart_type: "coefficient plot", source: null },
  { artifact_id: "residuals_fitted", chart_type: "residuals versus fitted", source: null },
  { artifact_id: "scatter_plots", chart_type: "scatter plot", source: null },
];

describe("ReportFigureSelection", () => {
  it("summarizes the bounded packet and lets the user inspect figure choices", () => {
    const onToggle = vi.fn();
    const onUseRecommended = vi.fn();
    const onIncludeAll = vi.fn();

    render(
      <ReportFigureSelection
        figures={figures}
        excludedFigureIds={new Set(["histograms", "scatter_plots"])}
        onToggle={onToggle}
        onUseRecommended={onUseRecommended}
        onIncludeAll={onIncludeAll}
      />,
    );

    expect(screen.getByTestId("report-figure-selection")).toHaveTextContent("Inventory: 4 in provenance · Next writer packet: 2 selected");
    expect(screen.getByText(/full figure inventory remains in report provenance/i)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Include figure coef_plot" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Choose figures" }));
    expect(screen.getByRole("checkbox", { name: "Include figure coef_plot" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Include figure histograms" })).not.toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: "Include figure coef_plot" }));
    expect(onToggle).toHaveBeenCalledWith("coef_plot");
    fireEvent.click(screen.getByRole("button", { name: "Use recommended" }));
    expect(onUseRecommended).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Include all figures" }));
    expect(onIncludeAll).toHaveBeenCalledTimes(1);
  });
});
