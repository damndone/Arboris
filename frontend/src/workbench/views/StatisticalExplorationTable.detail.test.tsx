import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatisticalExplorationTable } from "./StatisticalExplorationTable";

describe("StatisticalExplorationTable summarize detail", () => {
  it("reads like Stata's output: rounded numbers, percentile columns, no raw JSON", () => {
    render(
      <StatisticalExplorationTable
        explorations={[
          {
            item: { artifact_id: "detail1" } as never,
            payload: {
              result: {
                operation: "summarize_detail",
                source_row_count: 4149,
                filtered_row_count: 4149,
                variables: {
                  age: {
                    obs: 3893,
                    mean: 48.24454148471616,
                    std_dev: 17.74693057509504,
                    smallest: [18, 18, 18, 18],
                    largest: [89, 89, 89, 89],
                    quantile_method: "stata_summarize_detail_v1",
                    percentiles: { p1: 19, p50: 47, p99: 86 },
                  },
                },
              },
            },
          },
        ]}
      />,
    );
    const table = screen.getByTestId("statistical-exploration-table-detail1");
    expect(within(table).getByText("Summarize detail")).toBeTruthy();
    expect(within(table).getByText(/percentiles as Stata's summarize, detail/)).toBeTruthy();
    expect(within(table).getByText("48.24454")).toBeTruthy();
    expect(within(table).getByText("Std. dev.")).toBeTruthy();
    expect(within(table).getByText("p50")).toBeTruthy();
    expect(within(table).getByText("18, 18, 18, 18")).toBeTruthy();
    expect(table.textContent).not.toContain("stata_summarize_detail_v1");
    expect(table.textContent).not.toContain("{");
  });
});
