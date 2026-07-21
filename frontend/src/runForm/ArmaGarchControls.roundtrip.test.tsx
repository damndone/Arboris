import { describe, expect, test } from "vitest";
import {
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
  armaGarchValueFromModelOptions,
} from "./ArmaGarchControls";

describe("armaGarchValueFromModelOptions", () => {
  test("round-trips a manual GARCH config through model_options", () => {
    const original = {
      ...createDefaultArmaGarchValue(),
      timeColumn: "observation_date",
      valueColumn: "vixcls",
      timeIndexSemantics: "business_or_trading_observations" as const,
      transform: "log_return_pct" as const,
      transformConfirmed: true,
      selectionMode: "manual" as const,
      armaP: 1,
      armaQ: 1,
      constantMode: "exclude" as const,
      varianceModel: "garch" as const,
      garchP: 1,
      garchQ: 1,
      estimationStrategy: "sequential" as const,
      innovationDistribution: "normal" as const,
      validationN: 250,
      refitEvery: 1,
      randomSeed: 0,
    };
    const ref = "dataset:vix:1";
    const options = buildArmaGarchModelOptions(original, ref);
    const restored = armaGarchValueFromModelOptions(options, createDefaultArmaGarchValue());
    expect(buildArmaGarchModelOptions(restored, ref)).toEqual(options);
  });

  test("round-trips a manual ARCH config through model_options", () => {
    const original = {
      ...createDefaultArmaGarchValue(),
      timeColumn: "t",
      valueColumn: "y",
      transform: "diff_1" as const,
      transformConfirmed: true,
      selectionMode: "manual" as const,
      armaP: 2,
      armaQ: 0,
      constantMode: "include" as const,
      varianceModel: "arch" as const,
      archP: 5,
      estimationStrategy: "joint" as const,
      innovationDistribution: "student_t" as const,
      validationN: 40,
      refitEvery: 2,
      randomSeed: 7,
    };
    const ref = "dataset:x:1";
    const options = buildArmaGarchModelOptions(original, ref);
    const restored = armaGarchValueFromModelOptions(options, createDefaultArmaGarchValue());
    expect(buildArmaGarchModelOptions(restored, ref)).toEqual(options);
  });

  test("falls back to defaults for absent fields", () => {
    const base = createDefaultArmaGarchValue();
    const restored = armaGarchValueFromModelOptions({}, base);
    expect(restored.transform).toBe(base.transform);
    expect(restored.selectionMode).toBe(base.selectionMode);
    expect(restored.validationN).toBe(base.validationN);
  });
});
