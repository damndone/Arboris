import { describe, expect, test } from "vitest";
import type { RunDetail } from "../../api";
import { checkSummary, coefficientRows, fitStats, inferenceLine, keyCoefficient, modelIdOf, pendingChoices, pickModelResult } from "./resultModel";

const result = {
  model_id: "ols_1",
  nobs: 40,
  r_squared: 0.984,
  r_squared_adj: 0.983,
  pseudo_r2: null,
  aic: 674.02,
  bic: 679.08,
  coefficients: {
    Intercept: { estimate: 19728.4, std_error: 941.9, p_value: 0, ci_lower: 17819.9, ci_upper: 21636.9, p_value_display: "< 0.001" },
    education: { estimate: 2564.3, std_error: 70.9, p_value: 0, ci_lower: 2420.7, ci_upper: 2708.0, p_value_display: "< 0.001" },
  },
  inference_config: { covariance: "unadjusted", inference_distribution: "t", effective_df: 37, inference_version: "workbench.inference.v2" },
};
const detail = {
  model_results: [{ ...result, model_id: "other" }, result],
  term_labels: { education: "Years of education" },
  diagnostic_summary_preview: { available: true, trust_counts: { blockers: 0, warnings: 1, cautions: 0 }, primary_reasons: [{ message: "Residuals look heteroskedastic." }] },
} as unknown as RunDetail;

describe("result model", () => {
  test("a model step maps to its result by id", () => {
    expect(modelIdOf({ raw: { id: "model:ols_1" }, id: "h1", stage: "model", kind: "model" })).toBe("ols_1");
    expect(modelIdOf({ raw: { id: "clean:1" }, id: "h2", stage: "clean", kind: "dataset_stage" })).toBeNull();
    expect(pickModelResult(detail, "ols_1")).toBe(result);
    expect(pickModelResult(detail, "missing")).toBeNull();
  });

  test("coefficients carry labels, intervals and the p shown to readers; the key one is the first slope", () => {
    const rows = coefficientRows(pickModelResult(detail, "ols_1"), detail.term_labels);
    expect(rows.map((r) => [r.term, r.label, r.intercept])).toEqual([
      ["Intercept", "Intercept", true],
      ["education", "Years of education", false],
    ]);
    expect(keyCoefficient(rows, result as never)?.term).toBe("education");
    expect(rows[1]).toMatchObject({ estimate: 2564.3, se: 70.9, ciLow: 2420.7, ciHigh: 2708.0, pDisplay: "< 0.001" });
  });

  test("fit statistics skip what the model does not have; inference reads the shared rule", () => {
    expect(fitStats(result as never).map((s) => s.label)).toEqual(["n", "R²", "Adjusted R²", "AIC", "BIC"]);
    expect(inferenceLine(result as never)).toBe("Standard errors: Conventional · Inference: t(37)");
  });

  test("checks: blockers fail, warnings ask for a look, otherwise ready", () => {
    expect(checkSummary(detail)).toEqual({ status: "caution", label: "1 to look at", reasons: ["Residuals look heteroskedastic."] });
    expect(checkSummary({ diagnostic_summary_preview: { available: true, trust_counts: { blockers: 2 } } } as unknown as RunDetail)?.status).toBe("fails");
    expect(checkSummary({ diagnostic_summary_preview: { available: true, trust_counts: {} } } as unknown as RunDetail)?.label).toBe("Ready to interpret");
  });

  test("pending choices are the decisions still waiting for the user", () => {
    expect(pendingChoices([
      { id: "a", question: "Model type", picked: "ols", alternatives: [], why: "", evidence: [], reviewStatus: "needed" },
      { id: "b", question: "Standard errors", picked: "HC1", alternatives: [], why: "", evidence: [], reviewStatus: "passed" },
    ])).toEqual(["Model type"]);
  });
});
