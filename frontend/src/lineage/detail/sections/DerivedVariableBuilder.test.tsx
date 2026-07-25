import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DerivedVariableBuilder } from "./DerivedVariableBuilder";
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

const baseRequest: StatisticalExplorationRequest = {
  source_run_id: "run-1",
  source_node_id: "stage:raw",
  source_artifact_id: "source_data",
  operation: "derive_boolean",
  selected_columns: ["totreg"],
  filters: [],
};

describe("DerivedVariableBuilder", () => {
  it("previews and confirms a typed percentile definition", async () => {
    previewMock.mockResolvedValue({
      preview: {
        status: "ready",
        fingerprint: "derive-fp-1",
        source_sha256: "sha-1",
        source_artifact_id: "source_data",
        result: {
          filtered_row_count: 4,
          derived: {
            source_column: "totreg",
            percentile: 25,
            comparison: "lte",
            output_name: "small_school",
            threshold: 17.5,
            counts: { true: 1, false: 3, missing: 0 },
          },
        },
      },
    });
    confirmMock.mockResolvedValue({
      status: "completed",
      exploration: { artifact_id: "statistical_exploration_derive-fp-1" },
      derived: { child_node_id: "data-derive:derive-fp-1", threshold: 17.5 },
    });

    render(
      <DerivedVariableBuilder
        projectRoot="/tmp/project"
        request={baseRequest}
        numericColumns={["totreg", "pfl"]}
      />,
    );

    fireEvent.change(screen.getByTestId("derived-variable-source"), { target: { value: "totreg" } });
    fireEvent.change(screen.getByTestId("derived-variable-percentile"), { target: { value: "25" } });
    fireEvent.change(screen.getByTestId("derived-variable-output"), { target: { value: "small_school" } });
    fireEvent.click(screen.getByTestId("derived-variable-preview"));

    await waitFor(() => expect(screen.getByTestId("derived-variable-preview-result")).toBeInTheDocument());
    expect(previewMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({
      operation: "derive_boolean",
      options: expect.objectContaining({ source_column: "totreg", percentile: 25, comparison: "lte", output_name: "small_school" }),
    }));
    expect(screen.getByTestId("derived-variable-preview-result")).toHaveTextContent("Threshold: 17.5");

    fireEvent.click(screen.getByTestId("derived-variable-confirm"));
    await waitFor(() => expect(screen.getByTestId("derived-variable-complete")).toBeInTheDocument());
    expect(confirmMock).toHaveBeenCalledWith("/tmp/project", expect.objectContaining({ preview_fingerprint: "derive-fp-1" }));
  });
});
