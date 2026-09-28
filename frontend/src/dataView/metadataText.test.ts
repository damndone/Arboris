import { describe, expect, it } from "vitest";

import {
  formatMissingCodes,
  formatValueLabels,
  matchesMissingCode,
  parseMissingCodes,
  parseValueLabels,
  valueLabelFor,
} from "./metadataText";

describe("metadata text", () => {
  it("round-trips value labels", () => {
    const labels = { "1": "北方", "2": "South side" };
    expect(parseValueLabels(formatValueLabels(labels))).toEqual(labels);
    expect(parseValueLabels("")).toEqual({});
  });

  it("refuses malformed value labels", () => {
    expect(() => parseValueLabels("1 North")).toThrow(/value = label/);
    expect(() => parseValueLabels("1 = ")).toThrow(/both/);
    expect(() => parseValueLabels("1 = a; 1 = b")).toThrow(/twice/);
  });

  it("parses codes, negative numbers and ranges", () => {
    expect(parseMissingCodes("-99, 999, 900..999, NA, -9..-1")).toEqual([
      -99, 999, { low: 900, high: 999 }, "NA", { low: -9, high: -1 },
    ]);
    expect(formatMissingCodes([-99, { low: 900, high: 999 }])).toBe("-99, 900..999");
    expect(() => parseMissingCodes("10..1")).toThrow(/backwards/);
  });

  it("matches values the way the server does", () => {
    const codes = parseMissingCodes("-99, 900..999, NA");
    expect([-99, 950, 12, "NA", null].map((value) => matchesMissingCode(value, codes))).toEqual([
      true, true, false, true, false,
    ]);
    expect(valueLabelFor(2, { "2": "South" })).toBe("South");
    expect(valueLabelFor("x", { "2": "South" })).toBeUndefined();
  });
});
