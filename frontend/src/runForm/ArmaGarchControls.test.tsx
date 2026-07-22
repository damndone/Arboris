import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FilePreview } from "../api";
import {
  ArmaGarchControls,
  armaGarchValidationErrors,
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
} from "./ArmaGarchControls";

const preview: FilePreview = {
  fileName: "vix.csv",
  sheetNames: [],
  selectedSheet: "",
  rowCount: 120,
  columnCount: 2,
  columns: [
    { name: "date", dtype: "datetime", missingRate: 0, uniqueCount: 120, suggestedRole: "time" },
    { name: "vix", dtype: "numeric", missingRate: 0, uniqueCount: 115, suggestedRole: "x" },
  ],
  previewRows: [
    { date: "2025-01-02", vix: 12.1 },
    { date: "2025-01-03", vix: 13.4 },
    { date: "2025-01-06", vix: 35.2 },
  ],
  suggestedY: "vix",
  suggestedX: [],
  excludedColumns: [],
};

describe("ArmaGarchControls", () => {
  it("shows the five review steps and immutable-source boundary", () => {
    render(
      <ArmaGarchControls
        columns={["date", "vix"]}
        preview={preview}
        value={createDefaultArmaGarchValue()}
        onChange={() => {}}
      />,
    );

    expect(screen.getByText(/1\. Select time and value/i)).toBeInTheDocument();
    expect(screen.getByText(/2\. Review time index and data quality/i)).toBeInTheDocument();
    expect(screen.getByText(/3\. Review and confirm transform/i)).toBeInTheDocument();
    expect(screen.getByText(/4\. Configure bounded search/i)).toBeInTheDocument();
    expect(screen.getByText(/5\. Review execution graph/i)).toBeInTheDocument();
    expect(screen.getByText(/source table will not be modified/i)).toBeInTheDocument();
    expect(screen.getByLabelText("time column")).toContainHTML("date");
    expect(screen.getByLabelText("value column")).not.toContainHTML("date");
  });

  it("requires a user action to confirm the selected transform", () => {
    const onChange = vi.fn();
    const value = {
      ...createDefaultArmaGarchValue(),
      timeColumn: "date",
      valueColumn: "vix",
    };
    const { rerender } = render(
      <ArmaGarchControls
        columns={["date", "vix"]}
        preview={preview}
        value={value}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("transform"), {
      target: { value: "log_level" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      ...value,
      transform: "log_level",
      transformConfirmed: false,
    });

    const changed = {
      ...value,
      transform: "log_level" as const,
      transformConfirmed: false,
    };
    rerender(
      <ArmaGarchControls
        columns={["date", "vix"]}
        preview={preview}
        value={changed}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByLabelText(/confirm transform/i));
    expect(onChange).toHaveBeenLastCalledWith({
      ...changed,
      transformConfirmed: true,
    });
  });

  it("requires an explicit user choice before dropping missing values", () => {
    const onChange = vi.fn();
    const value = {
      ...createDefaultArmaGarchValue(),
      timeColumn: "date",
      valueColumn: "vix",
      transformConfirmed: true,
    };
    render(
      <ArmaGarchControls
        columns={["date", "vix"]}
        preview={preview}
        value={value}
        onChange={onChange}
      />,
    );

    expect(screen.getByLabelText("block missing values")).toBeChecked();
    fireEvent.click(screen.getByLabelText("confirm drop missing values"));

    expect(onChange).toHaveBeenLastCalledWith({
      ...value,
      missingValuePolicy: "drop_missing_confirmed",
      transformConfirmed: false,
    });
  });

  it("shows the full-data backend recommendation instead of inferring from preview rows", () => {
    render(
      <ArmaGarchControls
        columns={["date", "vix"]}
        preview={preview}
        transformPreflight={{
          schema_version: 1,
          source_row_count: 2610,
          analysis_row_count: 2542,
          diagnostics: [],
          transform_profiles: {},
          recommendation: {
            transform_id: "log_return_pct",
            score: 4.2,
            reason: "Full-series stationarity evidence favors changes.",
          },
          transform_confirmation_required: true,
        }}
        transformPreflightError={null}
        value={{
          ...createDefaultArmaGarchValue(),
          timeColumn: "date",
          valueColumn: "vix",
        }}
        onChange={() => {}}
      />,
    );

    expect(screen.getByText(/System suggestion: Log difference/)).toBeInTheDocument();
    expect(screen.getByText(/Full-series stationarity evidence/)).toBeInTheDocument();
    expect(screen.getByText(/2,542 of 2,610 source rows/)).toBeInTheDocument();
  });

  it("builds the exact backend contract for manual ARMA-GARCH", () => {
    const value = {
      ...createDefaultArmaGarchValue(),
      timeColumn: "date",
      valueColumn: "vix",
      transform: "log_return_pct" as const,
      transformConfirmed: true,
      missingValuePolicy: "drop_missing_confirmed" as const,
      selectionMode: "manual" as const,
      armaP: 2,
      armaQ: 1,
      constantMode: "include" as const,
      varianceModel: "garch" as const,
      garchP: 1,
      garchQ: 1,
      estimationStrategy: "sequential" as const,
      innovationDistribution: "student_t" as const,
      validationN: 24,
      refitEvery: 3,
    };

    expect(buildArmaGarchModelOptions(value, "upload:vix.csv")).toMatchObject({
      dataset_ref: "upload:vix.csv",
      time_column: "date",
      value_column: "vix",
      transform: "log_return_pct",
      transform_confirmed: true,
      missing_value_policy: "drop_missing_confirmed",
      selection_mode: "manual",
      arma: { p: 2, q: 1, constant_mode: "include" },
      variance: { model: "garch", garch_p: 1, garch_q: 1 },
      estimation_strategy: "sequential",
      innovation_distribution: "student_t",
      validation: { validation_n: 24, refit_every: 3 },
    });
  });

  it("blocks non-integer and out-of-range execution controls before submit", () => {
    const errors = armaGarchValidationErrors({
      ...createDefaultArmaGarchValue(),
      timeColumn: "date",
      valueColumn: "vix",
      transformConfirmed: true,
      selectionMode: "manual",
      armaP: 11,
      garchQ: 0,
      validationN: 0,
      refitEvery: 1.5,
      randomSeed: -1,
    });

    expect(errors).toEqual(expect.arrayContaining([
      expect.stringMatching(/AR order/),
      expect.stringMatching(/GARCH q/),
      expect.stringMatching(/Validation observations/),
      expect.stringMatching(/Refit frequency/),
      expect.stringMatching(/Random seed/),
    ]));
  });
});
