import { expect, test } from "vitest";
import { niceTicks } from "./IntervalPlot";

test("axis ticks are round numbers covering the range, zero included when inside", () => {
  expect(niceTicks(-130, 2900)).toEqual([0, 1000, 2000]);
  expect(niceTicks(-0.42, 0.9)).toEqual([-0.25, 0, 0.25, 0.5, 0.75]);
});
