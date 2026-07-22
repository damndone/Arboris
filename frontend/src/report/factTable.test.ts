import { describe, expect, it } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import { buildFactTable, buildFigureFacts, buildTimeSeriesFacts } from "./factTable";

function fixtureWithValues() {
  const seed = makeOwnerResolutionSeedFixture();
  const model = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
  model.editableSchema = [
    { key: "model_type", kind: "select", label: "Model", value: "ols" },
    { key: "covariance", kind: "select", label: "Covariance", value: "HC1" },
    { key: "alpha", kind: "text", label: "Alpha", value: "" }, // empty → skipped
  ] as never;
  model.stats = { r_squared: 0.86, n_obs: 60 } as never;
  return seed;
}

describe("buildFactTable", () => {
  it("extracts params (from schema values) and scalar metrics with node provenance", () => {
    const seed = fixtureWithValues();
    const { facts, scope, fingerprints } = buildFactTable(seed.forest, "run_c");

    const byField = new Map(facts.map((f) => [f.field, f]));
    expect(byField.get("param:covariance")?.value).toBe("HC1");
    expect(byField.get("param:model_type")?.value).toBe("ols");
    expect(byField.get("param:alpha")).toBeUndefined(); // empty value skipped
    expect(byField.get("metric:r_squared")?.value).toBe(0.86);
    expect(byField.get("param:covariance")?.node_key).toBe(seed.sharedNodeKey);

    // ids unique + sequential-ish
    expect(new Set(facts.map((f) => f.id)).size).toBe(facts.length);
    // scope covers exactly the active run's path nodes
    expect(scope.run_id).toBe("run_c");
    expect(scope.node_keys).toContain(seed.sharedNodeKey);
    expect(fingerprints.length).toBeGreaterThan(0);
  });

  it("expands model coefficient rows into per-term estimate/se/p facts (C-2)", () => {
    const seed = fixtureWithValues();
    const model = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
    model.stats = {
      r_squared: 0.86,
      coefficients: [
        {
          variable: "education",
          estimate: 0.5527,
          std_error: 0.081,
          p_value: 0.0001,
          significance_label: "significant at the 1% level",
        },
        { variable: "exper", estimate: 0.021 }, // no se/p → only estimate fact
        { variable: "broken" }, // no estimate → skipped entirely
      ],
    } as never;
    const { facts } = buildFactTable(seed.forest, "run_c");
    const byField = new Map(facts.map((f) => [f.field, f]));

    expect(byField.get("coef:education")?.value).toBe(0.5527);
    expect(byField.get("coef:education")?.label).toBe("coefficient (education)");
    expect(byField.get("coef_se:education")?.value).toBe(0.081);
    expect(byField.get("coef_p:education")?.value).toBe(0.0001);
    expect(byField.get("coef:exper")?.value).toBe(0.021);
    expect(byField.get("coef_se:exper")).toBeUndefined();
    expect(byField.get("coef:broken")).toBeUndefined();
    // the raw coefficients array itself never becomes a (non-atomic) fact
    expect(byField.get("metric:coefficients")).toBeUndefined();
    // scalar metrics still flow alongside
    expect(byField.get("metric:r_squared")?.value).toBe(0.86);
    expect(byField.get("coef:education")?.node_key).toBe(seed.sharedNodeKey);
  });

  it("bare fixture yields only the fixture's own schema facts, scoped to the run", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const { facts, scope } = buildFactTable(seed.forest, "run_a");
    // the seed model node ships a `formula` param; nothing else carries values
    expect(facts.map((f) => f.field)).toEqual(["param:formula"]);
    // run_a's path excludes run_c-only nodes (the report node)
    expect(scope.node_keys).not.toContain("hash_report_c");
  });

  it("skips structured params instead of rendering object coercions", () => {
    const seed = fixtureWithValues();
    const model = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
    model.editableSchema = [
      { key: "model_options", kind: "textarea", label: "Options", value: { arma: { p: 1 } } },
    ] as never;

    const { facts } = buildFactTable(seed.forest, "run_c");

    expect(facts.some((fact) => fact.field === "param:model_options")).toBe(false);
  });
});

describe("buildTimeSeriesFacts", () => {
  it("extracts bounded atomic model, diagnostic, validation, persistence, and forecast facts", () => {
    const facts = buildTimeSeriesFacts({
      "ts.analysis_contract": { payload: {
        time_column: "observation_date",
        value_column: "VIXCLS",
        time_index_semantics: "business_or_trading_observations",
        transform: "log_return_pct",
        transform_confirmed: true,
        selection_mode: "manual",
        estimation_strategy: "sequential",
        innovation_distribution: "normal",
        missing_value_policy: "drop_missing_confirmed",
      } },
      "ts.data_audit": { payload: {
        data_quality: { finite_value_count: 2542 },
        diagnostics: [{
          code: "MISSING_OBSERVATIONS_EXCLUDED",
          evidence: { excluded_missing_count: 68 },
        }],
      } },
      "ts.arma_selection": { payload: { final_selected_candidate_id: "arma-p1-q1-n" } },
      "ts.volatility_selection": { payload: { selected_candidate_id: "variance-garch-p1-q1-normal" } },
      "ts.final_model": { payload: { validation_fit: {
        mean_stage: { aicc: 100.5, bic: 110.5 },
        variance_stage: { aicc: 90.5, bic: 99.5 },
      } } },
      "ts.parameters": { payload: {
        mean_candidate: { "ar.L1": 0.9, "ma.L1": -0.8 },
        selected_variance_candidate: { "alpha[1]": 0.2, "beta[1]": 0.6 },
      } },
      "ts.final_diagnostics": { payload: {
        arch_lm: { p_value: 0.97 },
        normality: { p_value: 0.001, skew: 1.5, kurtosis: 10 },
        qq_data: Array.from({ length: 1000 }, () => ({ observed: 9 })),
      } },
      "ts.forecast_metrics": { payload: { rmse: 7.4, interval_coverage: 1 } },
      "ts.next_forecast": { payload: { conditional_mean: 0.6, conditional_volatility: 6.9 } },
    });

    const byField = new Map(facts.map((fact) => [fact.field, fact.value]));
    expect(byField.get("ts:contract:transform")).toBe("log_return_pct");
    expect(byField.get("ts:contract:missing_value_policy")).toBe("drop_missing_confirmed");
    expect(byField.get("ts:data:analysis_observations")).toBe(2542);
    expect(byField.get("ts:data:excluded_missing_observations")).toBe(68);
    expect(byField.get("ts:arma:selected_candidate")).toBe("arma-p1-q1-n");
    expect(byField.get("ts:mean:aicc")).toBe(100.5);
    expect(byField.get("ts:variance:aicc")).toBe(90.5);
    expect(byField.get("ts:diagnostic:arch_lm_p_value")).toBe(0.97);
    expect(byField.get("ts:validation:rmse")).toBe(7.4);
    expect(byField.get("ts:volatility:persistence")).toBeCloseTo(0.8);
    expect(byField.get("ts:volatility:half_life_observations")).toBeCloseTo(
      Math.log(0.5) / Math.log(0.8),
    );
    expect(facts.some((fact) => fact.field.includes("qq_data"))).toBe(false);
    expect(facts.every((fact) => typeof fact.value !== "object")).toBe(true);
  });
});

describe("buildFigureFacts", () => {
  it("extracts bounded numeric leaves with figure provenance", () => {
    const facts = buildFigureFacts(
      [
        {
          artifact_id: "event_study",
          chart_type: "event study",
          source: {
            preview_json: JSON.stringify({
              event_time: [-2, 0],
              estimate: [0.12, 2.001],
              se: [0.1, 0.3],
            }),
            preview_truncated: false,
          },
        },
      ],
      3,
    );

    expect(facts.map((fact) => fact.id)).toEqual(["c4", "c5", "c6", "c7", "c8", "c9"]);
    expect(facts.find((fact) => fact.field.endsWith("estimate[1]"))?.value).toBe(2.001);
    expect(facts[0].node_key).toBe("figure:event_study");
  });

  it("records truncation without inventing values and ignores malformed source", () => {
    const facts = buildFigureFacts([
      {
        artifact_id: "time_trend",
        chart_type: "time trend",
        source: { preview_json: "{not-json", preview_truncated: true },
      },
    ]);

    expect(facts).toHaveLength(1);
    expect(facts[0].field).toBe("figure:time_trend:preview_truncated");
    expect(facts[0].value).toBe(true);
  });
});
