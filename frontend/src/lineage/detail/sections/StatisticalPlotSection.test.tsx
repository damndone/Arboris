import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StatisticalPlotSection } from "./StatisticalPlotSection";
import type { StatisticalExplorationRequest } from "../../statisticalExploration";

const { previewMock, confirmMock } = vi.hoisted(() => ({
  previewMock: vi.fn(),
  confirmMock: vi.fn(),
}));

vi.mock("../../statisticalExploration", async () => {
  const actual = await vi.importActual<typeof import("../../statisticalExploration")>("../../statisticalExploration");
  return {
    ...actual,
    previewStatisticalExploration: (...args: unknown[]) => previewMock(...args),
    confirmStatisticalExploration: (...args: unknown[]) => confirmMock(...args),
  };
});

const request: StatisticalExplorationRequest = {
  source_run_id: "run-1",
  source_node_id: "stage:raw",
  source_artifact_id: "source_data",
  operation: "scatter",
  selected_columns: ["pfl", "spending"],
  filters: [],
};

describe("StatisticalPlotSection", () => {
  it("opens the plot editor in a spacious dialog instead of constraining it to the drawer", () => {
    render(<StatisticalPlotSection projectRoot="/tmp/project" request={request} numericColumns={["pfl", "spending"]} />);

    fireEvent.click(screen.getByTestId("statistical-plot-open-editor"));

    expect(screen.getByRole("dialog", { name: "Scatter plot editor" })).toBeInTheDocument();
    expect(screen.getByTestId("statistical-plot-editor-dialog")).toBeInTheDocument();
  });

  it("previews and saves a typed scatter plot", async () => {
    previewMock.mockResolvedValue({
      preview: {
        status: "ready",
        fingerprint: "plot-fp-1",
        source_sha256: "sha-1",
        source_artifact_id: "source_data",
        result: { filtered_row_count: 3, plot: { plotted_row_count: 3, x_column: "pfl", y_column: "spending" } },
      },
    });
    confirmMock.mockResolvedValue({
      status: "completed",
      exploration: { artifact_id: "statistical_exploration_plot-fp-1" },
      plot: { artifact_id: "statistical_scatter_plot-fp-1", plotted_row_count: 3 },
    });

    render(<StatisticalPlotSection projectRoot="/tmp/project" request={request} numericColumns={["pfl", "spending"]} />);
    fireEvent.click(screen.getByTestId("statistical-plot-open-editor"));
    fireEvent.click(screen.getByTestId("statistical-plot-preview"));
    await waitFor(() => expect(screen.getByTestId("statistical-plot-preview-result")).toBeInTheDocument());
    expect(previewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({ operation: "scatter" }));
    fireEvent.click(screen.getByTestId("statistical-plot-confirm"));
    await waitFor(() => expect(screen.getByTestId("statistical-plot-complete")).toBeInTheDocument());
  });
});
