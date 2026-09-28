import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const exportDataset = vi.fn();
const previewDatasetExport = vi.fn();

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  exportDataset: (...args: unknown[]) => exportDataset(...args),
  previewDatasetExport: (...args: unknown[]) => previewDatasetExport(...args),
}));

vi.mock("../../dataView/dataViewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../dataView/dataViewApi")>()),
  listDatasets: async () => [
    { node_id: "stage:raw", label: "Raw input data", stage: "source", parent_stage_id: null },
    { node_id: "stage:cleaned", label: "Cleaned data", stage: "clean", parent_stage_id: null },
  ],
  fetchDatasetVariables: async () => ({
    run_id: "r1", node_id: "stage:raw", artifact_id: "a", total_rows: 3,
    variables: ["wage", "educ", "region"].map((name, index) => ({ name, position: index + 1 })),
  }),
}));

import { DatasetExportPanel } from "./DatasetExportPanel";

const REPORT = {
  format: "dta", rows: 220, columns: 2, renamed: {},
  notes: [{ column: "educ", field: "user_missing_values", message: "10 value(s) matching [-99] written as missing" }],
};

describe("DatasetExportPanel", () => {
  beforeEach(() => {
    exportDataset.mockReset();
    previewDatasetExport.mockReset();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  it("previews exactly what the chosen options will write", async () => {
    previewDatasetExport.mockResolvedValue({
      ...REPORT, source_rows: 400, column_names: ["wage", "educ"], filename: "wages.dta",
      sample: [{ wage: 18.2, educ: 12 }],
    });
    render(<DatasetExportPanel projectRoot="/p" runId="r1" />);
    await screen.findByLabelText("Export region");

    fireEvent.click(screen.getByLabelText("Export region"));
    fireEvent.change(screen.getByLabelText("Stata version"), { target: { value: "13" } });
    fireEvent.change(screen.getByLabelText("Value labels"), { target: { value: "strings" } });
    fireEvent.change(screen.getByLabelText("File name"), { target: { value: "wages" } });
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    fireEvent.change(screen.getByLabelText("Row condition 1 variable"), { target: { value: "wage" } });
    fireEvent.change(screen.getByLabelText("Row condition 1 operator"), { target: { value: "ge" } });
    fireEvent.change(screen.getByLabelText("Row condition 1 value"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(screen.getByTestId("dataset-export-sample")).toBeTruthy());
    expect(previewDatasetExport).toHaveBeenCalledWith("/p", "r1", "stage:raw", {
      format: "dta", columns: ["wage", "educ"], filters: [{ column: "wage", op: "ge", value: 20 }],
      dta_version: 13, value_labels: "strings", missing_codes: "as_missing", filename: "wages",
    });
    const report = screen.getByTestId("dataset-export-report");
    expect(within(report).getByText(/Preview of wages.dta · 220 rows · 2 columns/)).toBeTruthy();
    expect(within(report).getByText(/written as missing/)).toBeTruthy();
    expect(exportDataset).not.toHaveBeenCalled();
  });

  it("exports with the same options and downloads the file", async () => {
    exportDataset.mockResolvedValue({ artifact_id: "x", filename: "stage-raw.sav", download_url: "/x", report: { ...REPORT, notes: [] } });
    render(<DatasetExportPanel projectRoot="/p" runId="r1" />);
    await screen.findByLabelText("Export region");
    fireEvent.change(screen.getByLabelText("Export format"), { target: { value: "sav" } });
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(screen.getByText(/All labels, measurement levels and missing codes are written/)).toBeTruthy());
    expect(exportDataset.mock.calls[0][3]).toMatchObject({ format: "sav", columns: null, filters: [] });
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });

  it("shows the server's refusal", async () => {
    previewDatasetExport.mockRejectedValue(new Error("Stata 13 cannot hold this dataset's non-ASCII names"));
    render(<DatasetExportPanel projectRoot="/p" runId="r1" />);
    await screen.findByLabelText("Export region");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("non-ASCII"));
  });
});
