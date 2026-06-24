import { describe, it, expect } from "vitest";
import { forestViewEnabled } from "./forestFlag";

describe("forestViewEnabled", () => {
  it("is off by default (ship-dark)", () => {
    expect(forestViewEnabled("")).toBe(false);
    expect(forestViewEnabled("?foo=1")).toBe(false);
  });
  it("is on only for ?forest=1", () => {
    expect(forestViewEnabled("?forest=1")).toBe(true);
    expect(forestViewEnabled("?a=b&forest=1&c=d")).toBe(true);
    expect(forestViewEnabled("?forest=0")).toBe(false);
    expect(forestViewEnabled("?forest=true")).toBe(false);
  });
});
