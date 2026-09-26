import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const exportDataset = vi.fn();

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  exportDataset: (...args: unknown[]) => exportDataset(...args),
}));

import { DatasetExportPanel } from "./DatasetExportPanel";

describe("DatasetExportPanel", () => {
  beforeEach(() => {
    exportDataset.mockReset();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  it("exports the chosen dataset and lists what Stata could not hold", async () => {
    exportDataset.mockResolvedValue({
      artifact_id: "data_export_dta_abc",
      filename: "stage-raw-abc.dta",
      download_url: "/runs/r1/artifacts/data_export_dta_abc",
      report: {
        format: "dta",
        rows: 220,
        columns: 3,
        renamed: {},
        notes: [
          { column: "educ", field: "user_missing_values", message: "10 value(s) matching [-99] written as system missing" },
        ],
      },
    });
    render(<DatasetExportPanel projectRoot="/p" runId="r1" />);

    fireEvent.change(screen.getByLabelText("Dataset to export"), { target: { value: "stage:cleaned" } });
    fireEvent.click(screen.getByRole("button", { name: "Stata (.dta)" }));

    await waitFor(() => expect(screen.getByTestId("dataset-export-report")).toBeTruthy());
    expect(exportDataset).toHaveBeenCalledWith("/p", "r1", "stage:cleaned", "dta");
    expect(screen.getByText(/written as system missing/)).toBeTruthy();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });

  it("says so when everything was written", async () => {
    exportDataset.mockResolvedValue({
      artifact_id: "a",
      filename: "stage-raw-a.sav",
      download_url: "/x",
      report: { format: "sav", rows: 5, columns: 2, renamed: {}, notes: [] },
    });
    render(<DatasetExportPanel projectRoot="/p" runId="r1" />);
    fireEvent.click(screen.getByRole("button", { name: "SPSS (.sav)" }));
    await waitFor(() =>
      expect(screen.getByText(/All labels, measurement levels and missing codes were written/)).toBeTruthy(),
    );
  });

  it("shows the server's refusal", async () => {
    exportDataset.mockRejectedValue(new Error("model:ols_1 is not a dataset node"));
    render(<DatasetExportPanel projectRoot="/p" runId="r1" />);
    fireEvent.click(screen.getByRole("button", { name: "SPSS (.sav)" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("not a dataset node"));
  });
});
