import { describe, expect, it } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import {
  buildFactTable,
  buildFigureFacts,
  buildPostEstimationFacts,
  buildTimeSeriesFacts,
} from "./factTable";
import { reportCapabilityManifestForFacts } from "./reportEvidence";

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

  it("records truncation and malformed previews without inventing values", () => {
    const facts = buildFigureFacts([
      {
        artifact_id: "time_trend",
        chart_type: "time trend",
        source: { preview_json: "{not-json", preview_truncated: true },
      },
      {
        artifact_id: "bad_preview",
        chart_type: "bad preview",
        source: { preview_json: "{also-not-json", preview_truncated: false },
      },
    ]);

    expect(facts).toHaveLength(2);
    expect(facts[0]).toMatchObject({
      field: "figure:time_trend:preview_truncated",
      value: true,
    });
    expect(facts[1]).toMatchObject({
      field: "figure:bad_preview:preview_invalid",
      value: true,
    });
  });

  it("publishes a marker when the local numeric leaf bound drops later values", () => {
    const facts = buildFigureFacts([
      {
        artifact_id: "large_preview",
        chart_type: "large preview",
        source: {
          preview_json: JSON.stringify(
            Object.fromEntries(
              Array.from({ length: 81 }, (_, index) => [`metric_${index}`, index]),
            ),
          ),
          preview_truncated: false,
        },
      },
    ]);

    expect(facts).toHaveLength(81);
    expect(facts[facts.length - 1]).toMatchObject({
      field: "figure:large_preview:preview_truncated",
      value: true,
    });
  });
});

describe("buildPostEstimationFacts", () => {
  const result = {
    artifact_id: "workflow_model_quadratic_stationary_point_abc",
    artifact_type: "post_estimation",
    operation_id: "model.quadratic_stationary_point",
    run_id: "run-source",
    model_run_id: "run-child",
    workflow_id: "wf-1",
    workflow_step_id: "stationary_point",
    result: {
      schema_version: "workbench.model.quadratic-stationary-point/v1",
      column: "experience",
      stationary_point: 211.59338521178753,
      stationary_point_within_observed_range: false,
      curvature: "maximum",
    },
  };

  it("makes a declared post-estimation result citable", () => {
    const facts = buildPostEstimationFacts([result]);

    const point = facts.find((fact) => fact.field.endsWith("stationary_point"));
    expect(point?.value).toBe(211.59338521178753);
    expect(point?.node_key).toBe("post_estimation:stationary_point");
    expect(point?.node_label).toBe("Quadratic stationary point");
    // The qualifier travels with the number: citing one without the other is
    // how an extrapolated turning point gets reported as a finding.
    expect(
      facts.find((fact) =>
        fact.field.endsWith("stationary_point_within_observed_range"),
      )?.value,
    ).toBe(false);
  });

  it("omits schema tags and non-atomic values, and continues the id sequence", () => {
    const facts = buildPostEstimationFacts([result], 3);

    expect(facts.map((fact) => fact.id)).toEqual(["c4", "c5", "c6", "c7"]);
    expect(facts.some((fact) => fact.field.includes("schema_version"))).toBe(false);
  });

  it("preserves workflow provider identity and artifact provenance for P7 results", () => {
    const facts = buildPostEstimationFacts([
      {
        ...result,
        artifact_id: "workflow_p7_matching_att_abc",
        artifact_type: "p7_analysis",
        operation_id: "matching.att",
        pack_family: "matching",
        source_sha256: "sha256:source",
        result: {
          contract: "matching.result",
          contract_version: "1.0",
          operation_id: "matching.att",
          result: {
            effect_estimate: 0.42,
            balance: { standardized_mean_difference: 0.08 },
          },
        },
      },
    ]);

    const fact = facts.find((item) => item.field.endsWith("effect_estimate"));
    expect(fact).toBeDefined();
    expect(fact?.provider_id).toBe("evidence.workflow.p7.v1");
    expect(fact?.artifact_ids).toEqual(["workflow_p7_matching_att_abc"]);
    expect(fact?.value).toBe(0.42);
    expect(fact?.qualifiers).toMatchObject({
      artifact_type: "p7_analysis",
      operation_id: "matching.att",
      pack_family: "matching",
      source_sha256: "sha256:source",
    });
    expect(reportCapabilityManifestForFacts(facts)).toEqual([
      expect.objectContaining({
        capability_id: "post_estimation",
        provider_id: "evidence.workflow.p7.v1",
      }),
    ]);
  });

  it("keeps Hurdle approximation labels beside reportable p-values", () => {
    const manyCoefficients = Object.fromEntries(
      Array.from({ length: 120 }, (_, index) => [
        `x_${index}`,
        { estimate: index, standard_error: 0.1, p_value: 0.04 },
      ]),
    );
    const facts = buildPostEstimationFacts([
      {
        ...result,
        artifact_id: "workflow_p7_glm_hurdle_poisson_abc",
        artifact_type: "p7_analysis",
        operation_id: "glm.hurdle_poisson",
        pack_family: "glm_extensions",
        result: {
          contract: "glm_extensions.result",
          contract_version: "1.0",
          operation_id: "glm.hurdle_poisson",
          result: {
            coefficient_estimands: {
              positive_count: manyCoefficients,
            },
            inference: {
              positive_count: {
                standard_error_method: "bfgs_inverse_hessian_approximation",
                p_value_method: "normal_wald_approximation",
                p_value_status: "approximate",
              },
            },
          },
        },
      },
    ]);

    const byField = new Map(facts.map((fact) => [fact.field, fact.value]));
    expect(byField.get(
      "post_estimation:stationary_point:result:inference:positive_count:standard_error_method",
    )).toBe("bfgs_inverse_hessian_approximation");
    expect(byField.get(
      "post_estimation:stationary_point:result:inference:positive_count:p_value_status",
    )).toBe("approximate");
  });

  it("uses the generic workflow provider for non-P7 capability results", () => {
    const facts = buildPostEstimationFacts([
      {
        ...result,
        artifact_id: "workflow_capability_test_correlations_abc",
        artifact_type: "workflow_capability_result",
        operation_id: "test.correlations",
        result: {
          operation_id: "test.correlations",
          assumptions: ["declared columns"],
          result: { p_value: 0.04 },
        },
      },
    ]);

    const fact = facts.find((item) => item.field.endsWith("p_value"));
    expect(fact?.provider_id).toBe("evidence.workflow.capability.v1");
    expect(fact?.artifact_ids).toEqual(["workflow_capability_test_correlations_abc"]);
  });

  it("publishes an explicit truncation fact for oversized workflow results", () => {
    const resultFields = Object.fromEntries(
      Array.from({ length: 81 }, (_, index) => [`metric_${index}`, index]),
    );
    const facts = buildPostEstimationFacts([
      {
        ...result,
        result: resultFields,
      },
    ]);

    expect(facts).toHaveLength(80);
    expect(facts[facts.length - 1]).toMatchObject({
      field: "post_estimation:stationary_point:facts_truncated",
      value: true,
    });
  });

  it("returns nothing when no post-estimation step was declared", () => {
    expect(buildPostEstimationFacts([])).toEqual([]);
  });
});
