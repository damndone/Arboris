import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatisticalExplorationTable } from "./StatisticalExplorationTable";

describe("StatisticalExplorationTable frequency tables", () => {
  it("renders one row per value with missing labelled, and names skipped columns", () => {
    render(
      <StatisticalExplorationTable
        explorations={[
          {
            item: { artifact_id: "tab1" } as never,
            payload: {
              result: {
                operation: "tabulate",
                source_row_count: 5,
                rows: [
                  { variable: "region", value: "north", count: 2, percent: 40, valid_percent: 50 },
                  { variable: "region", value: null, count: 1, percent: 20, valid_percent: null },
                ],
              },
            },
          },
          {
            item: { artifact_id: "sum1" } as never,
            payload: {
              result: {
                operation: "summarize",
                variables: { wage: { obs: 4, mean: 14 } },
                non_numeric_columns: ["region"],
              },
            },
          },
        ]}
      />,
    );
    expect(screen.getByText("north")).toBeTruthy();
    expect(screen.getByText("(missing)")).toBeTruthy();
    expect(screen.getByText(/not summarised \(not numeric\): region/)).toBeTruthy();
  });
});
