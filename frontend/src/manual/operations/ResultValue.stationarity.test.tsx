import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { expect, it } from "vitest";
import { ResultValue } from "./ResultValue";

it.each([
  ["adf", "ADF (constant)", "Unit root", "Lagged differences", -3.8474176703230913, "-3.84742"],
  ["kpss", "KPSS (level)", "Level stationarity", "Bartlett truncation lag", 0.5627484194848492, "0.562748"],
] as const)("reads the %s null and fixed lag as statistic-only evidence", (method, diagnostic, nullLabel, lagLabel, statistic, formatted) => {
  render(<ResultValue value={{
    result: {
      operation_id: "time_series.stationarity_statistic",
      method, statistic, null_hypothesis: method === "adf" ? "unit_root" : "level_stationarity",
      n_effective: method === "adf" ? 175 : 180,
      policy: { lag: 4 }, evidence_scope: "statistic_only",
      ...(method === "adf" ? { adf_regression: { residual_df: 169 } } : {}),
    },
  }} />);
  expect(screen.getByText(diagnostic)).toBeVisible();
  expect(screen.getByText(nullLabel)).toBeVisible();
  expect(screen.getByText(lagLabel)).toBeVisible();
  expect(screen.getByText(formatted)).toBeVisible();
  expect(screen.getByText("Statistic only")).toBeVisible();
  expect(screen.queryByText("P value")).toBeNull();
  expect(screen.queryByText("Critical values")).toBeNull();
});
