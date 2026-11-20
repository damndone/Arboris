import { describe, expect, it } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import {
  buildFactTable,
  buildFamilyEvidenceFacts,
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

  function nativeResult(operationId: string, stepId: string, payload: Record<string, unknown>) {
    return {
      ...result,
      artifact_id: `workflow_capability_${operationId.replace(/\./g, "_")}_${stepId}`,
      artifact_type: "workflow_capability_result",
      operation_id: operationId,
      model_run_id: "",
      workflow_id: "native-demo",
      workflow_step_id: stepId,
      source_sha256: "demo-source-sha256",
      result_sha256: `demo-result-${stepId}`,
      result: { operation_id: operationId, ...payload },
    };
  }

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

  it("binds distinct native findings to their original results and interpretation limits", () => {
    const acf = nativeResult("time_series.correlogram", "acf", {
      metrics: { lag_one_acf: 0.31, lag_one_pacf: 0.31 },
      policy: { max_lag: 8 },
      n_observations: 100,
    });
    const arima = nativeResult("time_series.native_arima", "arima", {
      fit: { aic: 47.1 },
      forecast: { steps: 5, last: { mean: 1.2, lower: -3, upper: 5.4 } },
      policy: { confidence_level: 0.95 },
    });
    const logistic = nativeResult("prediction.native_logistic", "binary", {
      metrics: { log_loss: 0.36, brier_score: 0.12, roc_auc: 0.71 },
      prevalence_baseline: { log_loss: 0.68 },
      split: { test_rows: 25 },
    });
    const facts = buildPostEstimationFacts([acf, arima, logistic]);
    expect(facts.find((fact) => fact.field.endsWith("metrics:lag_one_acf"))).toMatchObject({
      value: 0.31, artifact_ids: [acf.artifact_id], qualifiers: { scope: "descriptive" },
    });
    expect(facts.find((fact) => fact.field.endsWith("forecast:last:lower"))).toMatchObject({
      value: -3, artifact_ids: [arima.artifact_id], qualifiers: { interval: "conditional_prediction" },
    });
    expect(facts.find((fact) => fact.field.endsWith("metrics:roc_auc"))).toMatchObject({
      value: 0.71, artifact_ids: [logistic.artifact_id], qualifiers: { evaluation: "held_out" },
    });
  });

  it("cites held-out regression tree errors and structure without expanding the node table", () => {
    const tree = nativeResult("prediction.native_cart_regression", "regression-tree", {
      metrics: { mse: 2.5, rmse: 1.581, mae: 1.5 },
      mean_baseline: { prediction: 2, mse: 4.5, rmse: 2.121 },
      model_structure: { node_count: 3, root_predictor: "income" },
      split: { test_rows: 2 },
      prediction_basis: { nodes: [{ training_mean: 2 }] },
    });
    const facts = buildPostEstimationFacts([tree]);
    expect(facts.find(fact => fact.field.endsWith("metrics:mse"))).toMatchObject({
      value: 2.5, artifact_ids: [tree.artifact_id], qualifiers: { evaluation: "held_out" },
    });
    expect(facts.find(fact => fact.field.endsWith("mean_baseline:mse"))?.value).toBe(4.5);
    expect(facts.find(fact => fact.field.endsWith("model_structure:root_predictor"))?.value).toBe("income");
    expect(facts.some(fact => fact.field.includes("prediction_basis"))).toBe(false);
  });

  it("cites each computed Johansen hypothesis and keeps the rank criterion uncalibrated", () => {
    const johansen = nativeResult("time_series.johansen_rank", "rank-diagnostic", {
      n_effective: 78, policy: { difference_lags: 1 }, trace_statistics: [45.4, 16.9, 5.9],
      max_eigenvalue_statistics: [28.5, 11, 5.9],
    });
    const facts = buildPostEstimationFacts([johansen]);
    expect(facts.find(fact => fact.field.endsWith("trace_statistics:2"))).toMatchObject({
      value: 5.9, artifact_ids: [johansen.artifact_id],
      qualifiers: { evidence_scope: "statistics_only", rank_criterion: "uncalibrated" },
    });
    expect(facts.some(fact => fact.field.endsWith("trace_statistics:3"))).toBe(false);
  });

  it.each(["time_series.native_sarima", "time_series.native_sarimax"])("cites the saved season length for %s", operation => {
    const model = nativeResult(operation, "hourly", { policy: { seasonal_order: [0, 1, 0, 24] } });
    const facts = buildPostEstimationFacts([model]);
    expect(facts.find(fact => fact.field.endsWith("policy:seasonal_order:3"))).toMatchObject({
      value: 24, artifact_ids: [model.artifact_id],
    });
  });

  it("cites each forecast series and an asset name containing a separator without changing its lookup", () => {
    const varResult = nativeResult("time_series.native_var", "var", {
      fit: { n_effective: 100 }, forecast: { steps: 4, last_by_series: {
        "0": { series: "price", mean: 5, lower: 1, upper: 9 },
        "1": { series: "income", mean: 25, lower: 21, upper: 29 },
      } },
    });
    const portfolio = nativeResult("quant.min_variance", "portfolio", {
      metrics: { sample_variance: 0.004 }, allocation: { "market:bond": 0.7, stock: 0.3 },
    });
    const facts = buildPostEstimationFacts([varResult, portfolio]);
    expect(facts.find(fact => fact.label.includes("income marginal interval lower"))).toMatchObject({
      value: 21, artifact_ids: [varResult.artifact_id], qualifiers: { interval: "conditional_marginal_prediction" },
    });
    expect(facts.find(fact => fact.label.includes("market:bond portfolio weight"))).toMatchObject({
      value: 0.7, artifact_ids: [portfolio.artifact_id],
    });
  });

  it("makes key findings from the first six native methods citable on the same run", () => {
    const elasticNet = nativeResult("prediction.native_elastic_net", "elastic", {
      metrics: { rmse: 0.19904001118420492, mae: 0.1754549801378836, r2: 0.9702210580180151 },
      mean_baseline: { rmse: 9.709164342005081 },
      coefficients: { x: 1.45 },
    });
    const ridge = nativeResult("prediction.native_ridge", "ridge", {
      metrics: { rmse: 0.35440315112819853, mae: 0.3221103161449772 },
      split: { test_rows: 10, train_last_time: "2020-01-01" },
      native_build: { binary_sha256: "ridge-binary" },
    });
    const replay = nativeResult("quant.replay", "replay", {
      metrics: {
        cumulative_net_return: 0.48911330204225933, final_equity: 14891.133020422594,
        total_fees: 147.49548373253788, max_drawdown: 0.025130751259443137,
      },
      engine: { binary_sha256: "replay-binary" },
      series: { rows: [{ time: "2020-01-02", equity: 10100 }] },
    });
    const riskA = nativeResult("quant.rolling_risk", "risk8", {
      metrics: { window: 8, latest_max_volatility: 0.01933013520137597, maximum_volatility: 0.020092551645141073 },
      policy: { annualized: false, units: { volatility: "input_return_units" } },
    });
    const riskB = nativeResult("quant.rolling_risk", "risk12", {
      metrics: { window: 12, latest_max_volatility: 0.017994013974982934, maximum_volatility: 0.018118562544935518 },
      policy: { annualized: false },
      latest_covariance: { matrix: [[0.01]] },
    });
    const fixed = nativeResult("time_series.local_level", "fixed", {
      forecast: { steps: 6, last: { mean: 19.794874104542757, lower: 17.517079492793183, upper: 22.07266871629233 } },
      holdout: { metrics: { rmse: 1.857760432510804 }, origin_time: "2020-02-01" },
      policy: { confidence_level: 0.95 },
    });
    const fitted = nativeResult("time_series.local_level_fit", "fitted", {
      forecast: { steps: 6, last: { mean: 19.76499813648659, lower: 17.830211410434114, upper: 21.699784862539065 } },
      holdout: null,
      policy: { confidence_level: 0.95 },
    });
    const entries = [elasticNet, ridge, replay, riskA, riskB, fixed, fitted];
    const facts = buildPostEstimationFacts(entries);
    const checks = [
      [elasticNet, "metrics:rmse", 0.19904001118420492],
      [elasticNet, "mean_baseline:rmse", 9.709164342005081],
      [ridge, "metrics:rmse", 0.35440315112819853],
      [replay, "metrics:cumulative_net_return", 0.48911330204225933],
      [replay, "metrics:final_equity", 14891.133020422594],
      [replay, "metrics:total_fees", 147.49548373253788],
      [riskA, "metrics:latest_max_volatility", 0.01933013520137597],
      [riskA, "policy:annualized", false],
      [riskB, "metrics:latest_max_volatility", 0.017994013974982934],
      [riskB, "metrics:window", 12],
      [fixed, "forecast:last:mean", 19.794874104542757],
      [fitted, "forecast:last:lower", 17.830211410434114],
      [fitted, "forecast:last:upper", 21.699784862539065],
    ] as const;
    for (const [entry, field, value] of checks) {
      expect(facts).toContainEqual(expect.objectContaining({
        field: `post_estimation:${entry.workflow_step_id}:${field}`,
        value,
        artifact_ids: [entry.artifact_id],
        provider_id: "evidence.workflow.capability.v1",
        qualifiers: expect.objectContaining({
          operation_id: entry.operation_id,
          source_sha256: entry.source_sha256,
          result_sha256: entry.result_sha256,
        }),
      }));
    }
    for (const entry of entries) {
      expect(facts.filter((fact) => fact.artifact_ids?.includes(entry.artifact_id)).length).toBeLessThanOrEqual(6);
    }
    expect(facts.find((fact) => fact.field.endsWith("metrics:cumulative_net_return"))?.qualifiers)
      .toMatchObject({ scope: "offline_simulation" });
    expect(facts.find((fact) => fact.field.endsWith("metrics:latest_max_volatility"))?.qualifiers)
      .toMatchObject({ frequency: "per_observation", annualized: false });
    for (const entry of [elasticNet, ridge]) {
      expect(facts.find((fact) => fact.artifact_ids?.[0] === entry.artifact_id)?.qualifiers)
        .toMatchObject({ evaluation: "held_out" });
    }
    expect(facts.some((fact) => /sha256|coefficients|series|covariance|last_time|origin_time/.test(fact.field))).toBe(false);
  });

  it("shares the 80 positions with legacy evidence and gives every native result its first finding", () => {
    const replayResults = Array.from({ length: 19 }, (_, i) => nativeResult("quant.replay", `replay${i}`, {
      metrics: { cumulative_net_return: i / 100, total_fees: i, final_equity: 1000 + i, max_drawdown: 0.1 },
    }));
    const legacy = {
      ...result,
      result: Object.fromEntries(Array.from({ length: 81 }, (_, i) => [`metric_${i}`, i])),
    };
    const facts = buildPostEstimationFacts([...replayResults, legacy], 3);

    expect(facts.map((fact) => fact.id)).toEqual(Array.from({ length: 80 }, (_, i) => `c${i + 4}`));
    expect(facts.slice(0, 39).map((fact) => fact.artifact_ids?.[0])).toEqual(Array(39).fill(legacy.artifact_id));
    expect(facts.slice(0, 39).map((fact) => fact.value)).toEqual(Array.from({ length: 39 }, (_, i) => i));
    expect(facts.filter((fact) => fact.field.endsWith(":facts_truncated") && fact.value === true)).toHaveLength(2);
    expect(facts.slice(40, 59).map((fact) => [fact.artifact_ids?.[0], fact.field, fact.value])).toEqual(
      replayResults.map((entry, i) => [entry.artifact_id, `post_estimation:${entry.workflow_step_id}:metrics:cumulative_net_return`, i / 100]),
    );
  });

  it("allows a native-only run to use the full 80 positions", () => {
    const results = Array.from({ length: 20 }, (_, i) => nativeResult("time_series.local_level", `local${i}`, {
      forecast: { steps: 6, last: { mean: i, lower: i - 1, upper: i + 1 } },
      policy: { confidence_level: 0.95 },
    }));
    const facts = buildPostEstimationFacts(results);

    expect(facts).toHaveLength(80);
    expect(facts.slice(0, 20).map((fact) => fact.value)).toEqual(Array.from({ length: 20 }, (_, i) => i));
    expect(facts[79]).toMatchObject({ field: expect.stringMatching(/:facts_truncated$/), value: true });
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

describe("buildFamilyEvidenceFacts", () => {
  const provenance = { nodeKey: "hash::model:cs_did_1", nodeLabel: "cs_did (primary)" };
  const evidence = {
    contract: null,
    model_type: "cs_did",
    overall: { estimate: 2.0189, std_error: 0.125, ci: [1.7738, 2.2639] },
    event_study: {
      label_kind: "event_time",
      rows: [
        { label: -1, estimate: -0.0164, std_error: 0.1245, ci: [-0.2604, 0.2276] },
        { label: 0, estimate: 2.0012, std_error: 0.175, ci: [1.658, 2.344] },
      ],
    },
    honest_did: null,
  };

  it("makes every declared number citable, rows named by their label", () => {
    const facts = buildFamilyEvidenceFacts(evidence, 10, provenance);
    const byField = Object.fromEntries(facts.map((fact) => [fact.field, fact]));
    expect(byField["family:overall:estimate"].value).toBe(2.0189);
    expect(byField["family:overall:ci:lower"].value).toBe(1.7738);
    expect(byField["family:overall:ci:upper"].value).toBe(2.2639);
    expect(byField["family:event_study:rows:0:estimate"].value).toBe(2.0012);
    expect(byField["family:event_study:rows:-1:ci:upper"].value).toBe(0.2276);
    expect(byField["family:event_study:label_kind"].value).toBe("event_time");
    expect(facts[0].id).toBe("c11");
    expect(facts.every((fact) => fact.node_key === provenance.nodeKey)).toBe(true);
  });

  it("drops the envelope tags and absent sections rather than citing them", () => {
    const fields = buildFamilyEvidenceFacts(evidence, 0, provenance).map((fact) => fact.field);
    expect(fields.some((field) => field.includes("model_type") || field.includes("contract"))).toBe(false);
    expect(fields.some((field) => field.includes("honest_did"))).toBe(false);
  });

  it("says so when it stops early", () => {
    const rows = Array.from({ length: 300 }, (_, index) => ({ label: index, estimate: index }));
    const facts = buildFamilyEvidenceFacts({ event_study: { rows } }, 0, provenance);
    const last = facts[facts.length - 1];
    expect(last.field).toBe("family:facts_truncated");
    expect(last.value).toBe(true);
    expect(facts.length).toBeLessThanOrEqual(240);
  });

  it("is empty when the run declares no family evidence", () => {
    expect(buildFamilyEvidenceFacts(null, 0, provenance)).toEqual([]);
  });

  it("belongs to model and estimation evidence", () => {
    const manifest = reportCapabilityManifestForFacts(buildFamilyEvidenceFacts(evidence, 0, provenance));
    expect(manifest.map((entry) => entry.capability_id)).toEqual(["model.estimation"]);
  });
});

describe("figure facts from a summarized time trend", () => {
  it("cites the summary of every row and never the row sample", () => {
    const facts = buildFigureFacts([{
      artifact_id: "time_trend",
      chart_type: "time trend of numeric variables",
      source: {
        preview_truncated: false,
        preview_json: JSON.stringify({
          rows: { protocol_version: "figure-rows/v1", observations: { rows: [{ year: 2000, wage: 7654.321 }] } },
          summary: { protocol_version: "figure-series-summary/v1",
            observations: { series: { wage: { n: 36, mean: 12.5 } } } },
        }),
      },
    }]);
    expect(facts.map((fact) => fact.value)).toContain(12.5);
    expect(facts.map((fact) => fact.value)).not.toContain(7654.321);
    expect(facts.some((fact) => fact.field.includes(".rows."))).toBe(false);
  });
});
