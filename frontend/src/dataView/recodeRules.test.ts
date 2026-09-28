import { describe, expect, it } from "vitest";

import { parseRecodeRules } from "./recodeRules";

describe("parseRecodeRules", () => {
  it("parses ranges, values, missing, else and copy", () => {
    expect(parseRecodeRules("18..29 = 1\n30..49=2\n-9..-1 = missing\nbj = north\nmissing = 9\nelse = copy")).toEqual([
      { from: { low: 18, high: 29 }, to: 1 },
      { from: { low: 30, high: 49 }, to: 2 },
      { from: { low: -9, high: -1 }, to: null },
      { from: "bj", to: "north" },
      { from: "missing", to: 9 },
      { from: "else", to: "copy" },
    ]);
  });

  it("refuses unusable text", () => {
    expect(() => parseRecodeRules("")).toThrow(/at least one/);
    expect(() => parseRecodeRules("18..29")).toThrow(/from = to/);
    expect(() => parseRecodeRules("29..18 = 1")).toThrow(/backwards/);
    expect(() => parseRecodeRules("5 = ")).toThrow(/both sides/);
  });
});
