import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { formatScalar, ResultValue } from "./ResultValue";

it("reads a saved result as fields and tables, with the exact JSON one click away", () => {
  const value = { test_statistic: 12.3456789, p_value: 0.000123456, df: 2, groups: [{ level: "a", n: 10 }, { level: "b", n: 12 }], method: "kruskal_wallis" };
  render(<ResultValue value={value} />);
  expect(screen.getByText("Test statistic")).toBeInTheDocument();
  expect(screen.getByText("12.3457")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Level" })).toBeInTheDocument();
  expect(screen.getAllByRole("row")).toHaveLength(3);
  expect(screen.getByText(/"p_value": 0.000123456/)).not.toBeVisible();
});

it("formats scalars for reading", () => {
  expect(formatScalar(null)).toBe("—");
  expect(formatScalar(true)).toBe("Yes");
  expect(formatScalar(1234567)).toBe("1,234,567");
  expect(formatScalar(0.1234567891)).toBe("0.123457");
});

it("puts the result before its provenance and tabulates rows with one level of nesting", () => {
  const saved = {
    schema_version: "v1",
    request_fingerprint: "sha256:abc",
    result: { family: "correlations", result: { results: [
      { variables: ["a", "b"], nobs: 40, p_value: 2.4e-17, effect: { r: 0.923 }, warnings: [] },
      { variables: ["a", "c"], nobs: 40, p_value: 0.037, effect: { r: 0.331 }, warnings: [] },
    ] } },
  };
  render(<ResultValue value={saved} />);
  expect(screen.getByRole("columnheader", { name: "Effect r" })).toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "Warnings" })).toBeNull();
  expect(screen.getByText("a, b")).toBeInTheDocument();
  expect(screen.getByText("2.4E-17")).toBeInTheDocument();
  expect(screen.getByText("Request fingerprint")).not.toBeVisible();
});
