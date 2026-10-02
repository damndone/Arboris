import { describe, expect, it } from "vitest";

import { formatEstimate, formatInterval, formatPValue } from "./numbers";

describe("formatEstimate", () => {
  it("keeps about four significant digits", () => {
    expect(formatEstimate(0.9928945017762245)).toBe("0.9929");
    expect(formatEstimate(0.048964733752123804)).toBe("0.04896");
    expect(formatEstimate(-12.3456)).toBe("-12.35");
  });

  it("does not round away the digits of a large number", () => {
    expect(formatEstimate(33762.3)).toBe("33,762");
    expect(formatEstimate(-1234.56)).toBe("-1,235");
  });

  it("uses scientific notation for tiny non-zero values", () => {
    expect(formatEstimate(0.0000321)).toBe("3.21e-5");
    expect(formatEstimate(0)).toBe("0");
  });

  it("shows a dash for missing or non-finite values", () => {
    expect(formatEstimate(null)).toBe("—");
    expect(formatEstimate(undefined)).toBe("—");
    expect(formatEstimate(Number.NaN)).toBe("—");
    expect(formatEstimate(Number.POSITIVE_INFINITY)).toBe("—");
  });
});

describe("formatPValue", () => {
  it("never shows a p-value of zero", () => {
    expect(formatPValue(0)).toBe("< 0.001");
    expect(formatPValue(0.000046)).toBe("< 0.001");
  });

  it("shows three decimals otherwise", () => {
    expect(formatPValue(0.0123)).toBe("0.012");
    expect(formatPValue(0.7091)).toBe("0.709");
    expect(formatPValue(1)).toBe("1.000");
  });

  it("shows a dash for missing values", () => {
    expect(formatPValue(null)).toBe("—");
    expect(formatPValue(Number.NaN)).toBe("—");
  });
});

describe("formatInterval", () => {
  it("formats both ends with the estimate rule", () => {
    expect(formatInterval(0.8969253871094691, 1.08886361644298)).toBe("[0.8969, 1.089]");
  });

  it("shows a dash when either end is missing", () => {
    expect(formatInterval(null, 1)).toBe("—");
    expect(formatInterval(0.1, undefined)).toBe("—");
  });
});
