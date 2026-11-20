// v1.6.11 slice C — deterministic citable-fact extraction.
//
// The fact table is the anti-hallucination contract: it is built HERE, from
// the same pure context resolver the drawer uses, and sent to the model as the
// only permitted source of numbers. Chips later render from this local table
// (never from model output), so an invented number can never become a chip.
import type { PostEstimationResult } from "../api";
import type { ForestViewModel } from "../lineage/api/graphViewTypes";
import { resolveNodeOperationContext } from "../lineage/api/nodeOperationContext";

export interface CitableFact {
  id: string;
  node_key: string;
  node_label: string;
  /** e.g. "param:covariance", "metric:r_squared", "decision:standard_errors" */
  field: string;
  label: string;
  value: unknown;
  /** Optional provider metadata; old facts remain valid without it. */
  provider_id?: string;
  kind?: "estimate" | "diagnostic" | "sample" | "decision" | "metadata" | string;
  unit?: string | null;
  artifact_ids?: string[];
  claim_types?: string[];
  validation_level?: "external_oracle" | "internal_only" | "unverified" | string;
  qualifiers?: Record<string, unknown>;
}

export interface ReportScope {
  run_id: string;
  node_count: number;
  node_keys: string[];
}

export interface FigureFactInput {
  artifact_id: string;
  chart_type: string;
  source?: {
    preview_json?: string;
    preview_truncated?: boolean;
    [key: string]: unknown;
  } | null;
}

const MAX_FIGURE_FACTS = 80;
const FIGURE_ROWS_PROTOCOL = "figure-rows/v1";
const MAX_POST_ESTIMATION_FACTS = 80;

/** Extract only bounded numeric leaves from the serve-time figure source. */
export function buildFigureFacts(
  figures: FigureFactInput[],
  startAt = 0,
): CitableFact[] {
  const facts: CitableFact[] = [];
  let counter = startAt;
  const nextId = () => `c${++counter}`;

  for (const figure of figures) {
    const source = figure.source;
    const previewWasTruncated = source?.preview_truncated === true;
    if (previewWasTruncated) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:preview_truncated`,
        label: `${figure.chart_type} numeric preview truncated`,
        value: true,
      });
    }
    if (!source?.preview_json) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(source.preview_json) as unknown;
    } catch {
      if (!previewWasTruncated) {
        facts.push({
          id: nextId(),
          node_key: `figure:${figure.artifact_id}`,
          node_label: figure.chart_type,
          field: `figure:${figure.artifact_id}:preview_invalid`,
          label: `${figure.chart_type} numeric preview unavailable`,
          value: true,
        });
      }
      continue;
    }
    const leaves: Array<{ path: string; value: number }> = [];
    const locallyTruncated = collectNumericLeaves(
      parsed,
      "source",
      leaves,
      MAX_FIGURE_FACTS,
    );
    for (const leaf of leaves) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:${leaf.path}`,
        label: `${figure.chart_type} · ${leaf.path}`,
        value: leaf.value,
      });
    }
    if (locallyTruncated && !previewWasTruncated) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:preview_truncated`,
        label: `${figure.chart_type} numeric preview truncated`,
        value: true,
      });
    }
  }
  return facts;
}

type TimeSeriesArtifactMap = Record<string, unknown>;

function artifactPayload(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const record = value as Record<string, unknown>;
  const payload = record.payload;
  return payload && typeof payload === "object" && !Array.isArray(payload)
    ? payload as Record<string, unknown>
    : record;
}

function valueAt(root: Record<string, unknown>, path: string[]): unknown {
  let value: unknown = root;
  for (const key of path) {
    if (!value || typeof value !== "object") return undefined;
    value = Array.isArray(value) ? (/^(0|[1-9]\d*)$/.test(key) ? value[Number(key)] : undefined)
      : (value as Record<string, unknown>)[key];
  }
  return value;
}

function isAtomicFact(value: unknown): value is string | number | boolean {
  return (
    (typeof value === "string" && value !== "")
    || (typeof value === "number" && Number.isFinite(value))
    || typeof value === "boolean"
  );
}

/** Reader-facing names for declared post-estimation operations. */
const POST_ESTIMATION_FACT_LABELS: Record<string, string> = {
  "model.quadratic_stationary_point": "Quadratic stationary point",
  "model.joint_f_test": "Joint F test",
  "model.white_test": "White test",
};

type NativeReportFields = readonly (readonly [path: string | string[], label: string])[];
type NativeReportQualifiers = Readonly<Record<string, string | boolean>>;

const PREDICTION_REPORT_FIELDS: NativeReportFields = [
  ["metrics:rmse", "Holdout RMSE"],
  ["mean_baseline:rmse", "Training-mean baseline RMSE"],
  ["metrics:mae", "Holdout MAE"],
  ["split:test_rows", "Holdout observations"],
  ["metrics:r2", "Holdout R²"],
];

const LOCAL_LEVEL_REPORT_FIELDS: NativeReportFields = [
  ["forecast:last:mean", "Forecast mean at horizon"],
  ["forecast:last:lower", "Forecast interval lower bound at horizon"],
  ["forecast:last:upper", "Forecast interval upper bound at horizon"],
  ["forecast:steps", "Forecast horizon (periods)"],
  ["policy:confidence_level", "Forecast interval confidence level"],
  ["holdout:metrics:rmse", "Holdout RMSE"],
];

const HELD_OUT_QUALIFIERS = { evaluation: "held_out" };
const CLASSIFICATION_REPORT_FIELDS: NativeReportFields = [
  ["metrics:log_loss", "Holdout log loss"],
  ["metrics:brier_score", "Holdout Brier score"],
  ["metrics:roc_auc", "Holdout ROC AUC"],
  ["metrics:accuracy", "Holdout accuracy at 0.5"],
  ["prevalence_baseline:log_loss", "Training-prevalence baseline log loss"],
  ["split:test_rows", "Holdout rows"],
];

const NATIVE_REPORT_FIELDS = new Map<string, {
  label: string;
  fields: NativeReportFields;
  qualifiers?: NativeReportQualifiers;
}>([
  ["prediction.native_elastic_net", {
    label: "Elastic net prediction", fields: PREDICTION_REPORT_FIELDS, qualifiers: HELD_OUT_QUALIFIERS,
  }],
  ["prediction.native_ridge", {
    label: "Ridge prediction", fields: PREDICTION_REPORT_FIELDS, qualifiers: HELD_OUT_QUALIFIERS,
  }],
  ["prediction.native_ridge_selection", {
    label: "Ridge with validation and holdout", qualifiers: HELD_OUT_QUALIFIERS,
    fields: [...PREDICTION_REPORT_FIELDS, ["selection:selected_alpha", "Validation-selected ridge penalty"],
      ["selection:selected_validation_rmse", "Validation RMSE"], ["selection:fit_rows", "Initial fit rows"],
      ["selection:validation_rows", "Validation rows"], ["selection:refit_rows", "Refit rows"]],
  }],
  ["prediction.native_logistic", {
    label: "Logistic classification", fields: CLASSIFICATION_REPORT_FIELDS, qualifiers: HELD_OUT_QUALIFIERS,
  }],
  ["prediction.native_cart", {
    label: "Classification tree", qualifiers: HELD_OUT_QUALIFIERS,
    fields: [...CLASSIFICATION_REPORT_FIELDS, ["model_structure:node_count", "Tree nodes"],
      ["model_structure:root_predictor", "Root split predictor"]],
  }],
  ["prediction.native_cart_regression", {
    label: "Regression tree", qualifiers: HELD_OUT_QUALIFIERS,
    fields: [
      ["metrics:mse", "Holdout MSE"],
      ["mean_baseline:mse", "Training-mean baseline MSE"],
      ["metrics:rmse", "Holdout RMSE"],
      ["metrics:mae", "Holdout MAE"],
      ["split:test_rows", "Holdout observations"],
      ["model_structure:node_count", "Tree nodes"],
      ["model_structure:root_predictor", "Root split predictor"],
    ],
  }],
  ["prediction.native_random_forest_regression", {
    label: "Random forest regression", qualifiers: HELD_OUT_QUALIFIERS,
    fields: [["metrics:mse", "Holdout MSE"], ["metrics:rmse", "Holdout RMSE"], ["metrics:mae", "Holdout MAE"],
      ["mean_baseline:rmse", "Training-mean baseline RMSE"], ["split:test_rows", "Holdout rows"],
      ["model_structure:tree_count", "Trees"], ["options:max_features", "Predictors per split"], ["options:seed", "Seed"]],
  }],
  ["prediction.native_random_forest_classification", {
    label: "Random forest classification", qualifiers: HELD_OUT_QUALIFIERS,
    fields: [...CLASSIFICATION_REPORT_FIELDS, ["model_structure:tree_count", "Trees"],
      ["options:max_features", "Predictors per split"], ["options:seed", "Seed"]],
  }],
  ["time_series.correlogram", {
    label: "Correlogram", qualifiers: { scope: "descriptive" },
    fields: [
      ["metrics:lag_one_acf", "Lag-1 autocorrelation"],
      ["metrics:lag_one_pacf", "Lag-1 partial autocorrelation"],
      ["policy:max_lag", "Maximum lag"],
      ["n_observations", "Observed periods"],
    ],
  }],
  ["time_series.stationarity_statistic", {
    label: "Fixed-lag stationarity statistic", qualifiers: { evidence_scope: "statistic_only" },
    fields: [["statistic", "Diagnostic statistic"], ["null_hypothesis", "Null hypothesis"],
      ["method", "Diagnostic method"], ["n_effective", "Effective observations"], ["policy:lag", "Fixed lag"]],
  }],
  ["time_series.johansen_rank", {
    label: "Johansen rank diagnostics", qualifiers: { evidence_scope: "statistics_only", rank_criterion: "uncalibrated" },
    fields: [["n_effective", "Fitted periods"], ["policy:difference_lags", "Lagged differences"],
      ...[0, 1, 2, 3].flatMap(rank => [
        [`trace_statistics:${rank}`, `Trace statistic for rank at most ${rank}`] as const,
        [`max_eigenvalue_statistics:${rank}`, `Maximum-eigenvalue statistic for rank ${rank}`] as const,
      ])],
  }],
  ["time_series.native_arima", {
    label: "ARIMA forecast", fields: LOCAL_LEVEL_REPORT_FIELDS, qualifiers: { interval: "conditional_prediction" },
  }],
  ["time_series.arima_residual_check", {
    label: "ARIMA with Ljung–Box", qualifiers: { interval: "conditional_prediction", residual_reference: "asymptotic_chi_square" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["fit:diagnostics:whiteness:status", "Residual check status"],
      ["fit:diagnostics:whiteness:reason_code", "Residual check limitation"],
      ["fit:diagnostics:whiteness:n_effective", "Effective innovations"],
      ["fit:diagnostics:whiteness:fit_df", "Fitted AR and MA terms"],
      ["fit:diagnostics:whiteness:lag", "Ljung–Box lag"], ["fit:diagnostics:whiteness:statistic", "Ljung–Box statistic"],
      ["fit:diagnostics:whiteness:df", "Ljung–Box degrees of freedom"], ["fit:diagnostics:whiteness:p_value", "Ljung–Box p-value"]],
  }],
  ["time_series.native_sarima", {
    label: "Seasonal ARIMA forecast", qualifiers: { interval: "conditional_prediction" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["policy:seasonal_order:3", "Season length (periods)"]],
  }],
  ["time_series.native_arimax", {
    label: "ARIMAX scenario forecast", fields: LOCAL_LEVEL_REPORT_FIELDS, qualifiers: { interval: "given_supplied_predictors" },
  }],
  ["time_series.native_sarimax", {
    label: "SARIMAX scenario forecast", qualifiers: { interval: "given_supplied_predictors" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["policy:seasonal_order:3", "Season length (periods)"]],
  }],
  ["time_series.native_var", {
    label: "Vector autoregression", qualifiers: { interval: "conditional_marginal_prediction" },
    fields: [
      ["fit:n_effective", "Fitted periods"], ["policy:lag_order", "VAR lag order"],
      ["forecast:steps", "Forecast periods"], ["fit:stability", "Stability assessment"],
      ["diagnostics:granger:f_statistic", "Granger conditional F statistic"],
      ["diagnostics:granger:p_value", "Granger conditional p-value"],
    ],
  }],
  ["time_series.native_vecm", {
    label: "Rank-one VECM", qualifiers: { interval: "conditional_marginal_prediction", rank: "fixed_one" },
    fields: [
      ["fit:n_effective", "Fitted periods"], ["fit:rank", "Declared rank"], ["policy:difference_lags", "Lagged differences"],
      ["forecast:steps", "Forecast periods"], ["fit:normalized_series", "Normalized level series"],
    ],
  }],
  ["time_series.varma11_fixed_ma", {
    label: "VARMA with fixed diagonal MA", qualifiers: { interval: "conditional_marginal_prediction", ma: "fixed" },
    fields: [["policy:ma_coefficient", "Fixed diagonal MA"], ["fit:conditional_log_likelihood", "Conditional log likelihood"],
      ["fit:n_effective", "Fitted periods"], ["forecast:steps", "Forecast periods"]],
  }],
  ["time_series.native_arfima", {
    label: "ARFIMA(0,d,0)", qualifiers: { interval: "conditional_prediction" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["policy:fractional_difference", "Fractional difference (d)"],
      ["policy:difference_mode", "Fractional difference mode"], ["fit:marginal_variance", "Marginal variance"]],
  }],
  ["time_series.markov_switching", {
    label: "Markov switching mean", qualifiers: { interval: "conditional_mixture_prediction" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS,
      ["fit:mean_low", "Lower-regime mean"], ["fit:mean_high", "Higher-regime mean"],
      ["forecast:last:probability_low", "Lower-regime probability at horizon"],
      ["forecast:last:probability_high", "Higher-regime probability at horizon"],
    ],
  }],
  ["time_series.holt_winters_additive", {
    label: "Additive Holt-Winters forecast", qualifiers: { interval: "conditional_prediction" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["parameters:alpha", "Level smoothing (alpha)"], ["policy:season_period", "Season length"]],
  }],
  ["time_series.holt_winters_fit_alpha", {
    label: "Holt-Winters with holdout", qualifiers: { interval: "conditional_prediction" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["parameters:alpha", "Training-selected alpha"], ["estimation:training_steps", "Training periods"]],
  }],
  ["time_series.holt_winters_fit_joint", {
    label: "Joint additive Holt-Winters", qualifiers: { interval: "conditional_prediction", smoothing: "jointly_estimated" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["parameters:alpha", "Level smoothing (alpha)"],
      ["parameters:beta", "Trend smoothing (beta)"], ["parameters:gamma", "Seasonal smoothing (gamma)"],
      ["holdout:metrics:naive_rmse", "Seasonal naive holdout RMSE"], ["holdout:training_steps", "Holdout training periods"]],
  }],
  ["time_series.ets_trend", {
    label: "Additive ETS trend", qualifiers: { interval: "conditional_prediction", smoothing: "fixed" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["model_name", "ETS specification"], ["parameters:alpha", "Level smoothing"],
      ["parameters:beta", "Trend smoothing"], ["parameters:phi", "Damping"]],
  }],
  ["time_series.ets_trend_estimate", {
    label: "Estimated ETS trend", qualifiers: { interval: "conditional_prediction", smoothing: "profiled" },
    fields: [...LOCAL_LEVEL_REPORT_FIELDS, ["model_name", "ETS specification"], ["parameters:alpha", "Level smoothing"],
      ["policy:smoothing_modes:alpha", "Level smoothing mode"], ["parameters:beta", "Trend smoothing"],
      ["policy:smoothing_modes:beta", "Trend smoothing mode"], ["parameters:phi", "Damping"]],
  }],
  ["time_series.native_volatility", {
    label: "Conditional variance forecast", qualifiers: { quantity: "conditional_variance", units: "squared_input" },
    fields: [
      ["policy:family", "Volatility model"],
      ["forecast:last:variance", "Conditional variance at horizon"],
      ["forecast:steps", "Forecast horizon (periods)"],
      ["fit:persistence", "Estimated variance persistence"],
      ["holdout:metrics:mean_gaussian_loss", "Holdout mean Gaussian loss"],
      ["holdout:metrics:variance_mae", "Holdout variance MAE versus squared innovations"],
    ],
  }],
  ["time_series.native_egarch", {
    label: "EGARCH one-step variance", qualifiers: { quantity: "conditional_variance", units: "squared_input" },
    fields: [
      ["forecast:last:variance", "Next conditional variance"], ["forecast:last:log_variance", "Next log variance"],
      ["parameters:gamma", "Signed innovation coefficient"], ["parameters:beta", "Log variance persistence"],
      ["holdout:metrics:mean_gaussian_loss", "Holdout mean Gaussian loss"],
    ],
  }],
  ["time_series.native_igarch", {
    label: "IGARCH conditional variance", qualifiers: { quantity: "conditional_variance", units: "squared_input" },
    fields: [
      ["forecast:last:variance", "Conditional variance at horizon"], ["forecast:steps", "Forecast periods"],
      ["policy:persistence", "Integrated persistence"], ["parameters:omega", "Per-period variance increment"],
      ["fit:long_run_variance_reason", "Long-run variance status"],
    ],
  }],
  ["time_series.figarch_fixed", {
    label: "FIGARCH conditional variance", qualifiers: { quantity: "conditional_variance", units: "squared_input", coefficients: "fixed" },
    fields: [
      ["forecast:last:variance", "Conditional variance at horizon"], ["forecast:steps", "Forecast periods"],
      ["policy:truncation", "Retained lags"], ["fit:retained_weight_mass", "Retained weight mass"],
      ["fit:omitted_weight_mass", "Omitted weight mass"], ["fit:long_run_variance_status", "Long-run variance status"],
    ],
  }],
  ["time_series.local_level", { label: "Local-level forecast", fields: LOCAL_LEVEL_REPORT_FIELDS }],
  ["time_series.local_level_fit", { label: "Fitted local-level forecast", fields: LOCAL_LEVEL_REPORT_FIELDS }],
  ["quant.replay", {
    label: "Portfolio replay",
    qualifiers: { scope: "offline_simulation" },
    fields: [
      ["metrics:cumulative_net_return", "Simulated cumulative net return"],
      ["metrics:total_fees", "Simulated total fees"],
      ["metrics:final_equity", "Simulated final equity"],
      ["metrics:max_drawdown", "Maximum drawdown"],
      ["inputs:transaction_cost_bps", "Transaction cost (bps)"],
    ],
  }],
  ["quant.replay_fee_comparison", {
    label: "Portfolio replay fee comparison", qualifiers: { scope: "offline_simulation", difference: "higher_minus_base" },
    fields: [
      ["inputs:base_transaction_cost_bps", "Base fee (bps)"],
      ["inputs:higher_transaction_cost_bps", "Higher fee (bps)"],
      ["metrics:base:cumulative_net_return", "Base-fee net return"],
      ["metrics:higher:cumulative_net_return", "Higher-fee net return"],
      ["metrics:higher_minus_base:cumulative_net_return", "Net return difference (fraction)"],
      ["metrics:higher_minus_base:total_fees", "Additional simulated fees paid"],
      ["metrics:higher_minus_base:final_equity", "Final equity difference"],
    ],
  }],
  ["quant.replay_tail_risk", {
    label: "Historical portfolio tail risk",
    qualifiers: { scope: "offline_simulation", frequency: "per_observation", annualized: false, loss_sign: "positive_is_loss" },
    fields: [
      ["metrics:value_at_risk", "Historical value at risk"],
      ["metrics:expected_shortfall", "Historical expected shortfall"],
      ["metrics:confidence_bps", "Confidence level (basis points)"],
      ["metrics:window", "Trailing window (periods)"],
      ["inputs:end_period", "Last completed period"],
    ],
  }],
  ["quant.min_variance_walk_forward", {
    label: "Walk-forward portfolio", qualifiers: { scope: "offline_simulation", benchmark: "equal_weights" },
    fields: [
      ["metrics:strategy:cumulative_net_return", "Minimum-variance net return"],
      ["metrics:benchmark:cumulative_net_return", "Equal-weight net return"],
      ["metrics:cumulative_net_return_difference", "Net return difference (fraction)"],
      ["metrics:strategy:max_drawdown", "Minimum-variance maximum drawdown"],
      ["metrics:benchmark:max_drawdown", "Equal-weight maximum drawdown"],
      ["metrics:strategy:total_fees", "Minimum-variance fees"],
      ["metrics:benchmark:total_fees", "Equal-weight fees"],
      ["inputs:transaction_cost_bps", "Trading fee (basis points)"],
      ["inputs:window", "Training window periods"],
    ],
  }],
  ["quant.rolling_risk", {
    label: "Rolling asset risk",
    qualifiers: { frequency: "per_observation", annualized: false },
    fields: [
      ["metrics:latest_max_volatility", "Latest maximum volatility (per observation)"],
      ["metrics:maximum_volatility", "Maximum rolling volatility (per observation)"],
      ["metrics:window", "Window (observations)"],
      ["policy:annualized", "Annualized"],
      ["policy:units:volatility", "Volatility units"],
    ],
  }],
  ["quant.min_variance", {
    label: "Historical minimum variance", qualifiers: { frequency: "per_observation", annualized: false },
    fields: [
      ["metrics:sample_variance", "Portfolio sample variance"],
      ["metrics:objective_variance", "Regularized objective variance"],
      ["metrics:sample_rank", "Sample covariance rank"],
      ["inputs:shrinkage_bps", "Shrinkage (basis points)"], ["inputs:end_period", "Last completed period"],
    ],
  }],
]);

function nativeReportDefinition(entry: PostEstimationResult) {
  if (entry.artifact_type !== "workflow_capability_result") return undefined;
  const definition = NATIVE_REPORT_FIELDS.get(entry.operation_id);
  if (!definition) return undefined;
  const extra: Array<NativeReportFields[number]> = [];
  if (["time_series.native_var", "time_series.native_vecm", "time_series.varma11_fixed_ma"].includes(entry.operation_id)) {
    for (let i = 0; i < 8; i += 1) {
      const base = ["forecast", "last_by_series", String(i)];
      const name = valueAt(entry.result, [...base, "series"]);
      if (typeof name === "string") {
        extra.push([[...base, "mean"], `${name} forecast mean at horizon`],
          [[...base, "lower"], `${name} marginal interval lower bound`],
          [[...base, "upper"], `${name} marginal interval upper bound`]);
      }
    }
  }
  if (entry.operation_id === "quant.min_variance") {
    const allocation = valueAt(entry.result, ["allocation"]);
    if (allocation && typeof allocation === "object" && !Array.isArray(allocation)) {
      for (const asset of Object.keys(allocation).slice(0, 32)) {
        extra.push([["allocation", asset], `${asset} portfolio weight`]);
      }
    }
  }
  return extra.length ? { ...definition, fields: [...definition.fields, ...extra] } : definition;
}

function workflowProviderId(entry: PostEstimationResult): string | undefined {
  if (entry.artifact_type === "p7_analysis") return "evidence.workflow.p7.v1";
  if (entry.artifact_type === "workflow_capability_result") {
    return "evidence.workflow.capability.v1";
  }
  return undefined;
}

function workflowProvenance(entry: PostEstimationResult): Record<string, unknown> {
  const provenance: Record<string, unknown> = {
    artifact_type: entry.artifact_type,
    operation_id: entry.operation_id,
    workflow_id: entry.workflow_id,
    workflow_step_id: entry.workflow_step_id,
  };
  for (const key of [
    "pack_family",
    "source_sha256",
    "request_fingerprint",
    "result_sha256",
    "result_schema",
  ] as const) {
    const value = entry[key];
    if (value !== undefined && value !== "") provenance[key] = value;
  }
  return provenance;
}

const POST_ESTIMATION_ENVELOPE_FIELDS = new Set([
  "schema_version",
  "contract",
  "contract_version",
  "operation_id",
]);

function collectPostEstimationAtomicValues(
  value: unknown,
  path: string[],
  emit: (path: string[], value: string | number | boolean) => boolean,
): boolean {
  if (isAtomicFact(value)) {
    return path.length > 0 ? emit(path, value) : true;
  }
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      if (!collectPostEstimationAtomicValues(item, [...path, `[${index}]`], emit)) {
        return false;
      }
    }
    return true;
  }
  if (!value || typeof value !== "object") return true;
  const entries = Object.entries(value);
  entries.sort(([left], [right]) => (
    Number(right === "inference") - Number(left === "inference")
  ));
  for (const [key, item] of entries) {
    if (POST_ESTIMATION_ENVELOPE_FIELDS.has(key)) continue;
    if (!collectPostEstimationAtomicValues(item, [...path, key], emit)) return false;
  }
  return true;
}

/** Make declared post-estimation results citable in a generated report.
 *
 * These are server-computed scalars with artifact provenance, so they belong
 * in the deterministic fact table. Legacy operations keep their atomic
 * fields and qualifiers. Native research contributes selected aggregate
 * findings, with one finding from each result before secondary findings. */
export function buildPostEstimationFacts(
  results: PostEstimationResult[],
  startAt = 0,
): CitableFact[] {
  const definitions = results.map(entry => ({ entry, definition: nativeReportDefinition(entry) }));
  const legacy = definitions.filter(({ definition }) => !definition).map(({ entry }) => entry);
  const native = definitions.flatMap(({ entry, definition }) => {
    if (!definition) return [];
    const findings = definition.fields.flatMap(([path, label]) => {
      const parts = typeof path === "string" ? path.split(":") : path;
      const value = valueAt(entry.result, parts);
      return isAtomicFact(value) ? [{ entry, definition, path: parts.join(":"), label, value }] : [];
    });
    return [findings];
  });
  const rounds = Math.max(0, ...native.map((findings) => findings.length));
  const nativeFindings = Array.from({ length: rounds }, (_, round) =>
    native.flatMap((findings) => findings.slice(round, round + 1)),
  ).flat();
  const nativeLimit = legacy.length > 0 ? MAX_POST_ESTIMATION_FACTS / 2 : MAX_POST_ESTIMATION_FACTS;
  const nativeTruncated = nativeFindings.length > nativeLimit;
  const selectedNative = nativeFindings.slice(0, nativeLimit - Number(nativeTruncated));
  const legacyLimit = MAX_POST_ESTIMATION_FACTS - selectedNative.length - Number(nativeTruncated);
  const facts: CitableFact[] = [];
  let counter = startAt;

  function appendFact(
    entry: PostEstimationResult,
    nodeLabel: string,
    path: string,
    label: string,
    value: string | number | boolean,
    extraQualifiers?: NativeReportQualifiers,
  ) {
    const providerId = workflowProviderId(entry);
    facts.push({
      id: `c${++counter}`,
      node_key: `post_estimation:${entry.workflow_step_id}`,
      node_label: nodeLabel,
      field: `post_estimation:${entry.workflow_step_id}:${path}`,
      label,
      value,
      ...(providerId ? { provider_id: providerId } : {}),
      artifact_ids: [entry.artifact_id],
      qualifiers: { ...workflowProvenance(entry), ...extraQualifiers },
    });
  }

  for (const entry of legacy) {
    const label = POST_ESTIMATION_FACT_LABELS[entry.operation_id] ?? entry.operation_id;
    let truncated = false;
    collectPostEstimationAtomicValues(entry.result, [], (path, value) => {
      // Reserve one slot for a visible truncation marker.
      if (facts.length >= legacyLimit - 1) {
        truncated = true;
        return false;
      }
      const key = path.join(":");
      appendFact(entry, label, key, `${label} — ${key.replace(/_/g, " ")}`, value);
      return true;
    });
    if (truncated) {
      appendFact(entry, label, "facts_truncated", `${label} — evidence truncated at ${legacyLimit - 1} facts`, true);
      break;
    }
  }
  for (const { entry, definition, path, label, value } of selectedNative) {
    appendFact(entry, definition.label, path, `${definition.label} — ${label}`, value, definition.qualifiers);
  }
  if (nativeTruncated) {
    const { entry, definition } = nativeFindings[selectedNative.length];
    appendFact(entry, definition.label, "facts_truncated", `Native research evidence truncated at ${selectedNative.length} facts`, true);
  }
  return facts;
}

const MAX_FAMILY_EVIDENCE_FACTS = 240;
// Tags that identify the projection, not the result.
const FAMILY_EVIDENCE_ENVELOPE_FIELDS = new Set(["contract", "model_type"]);

function isInterval(key: string, value: unknown): value is [number, number] {
  return (
    /(^|_)(ci|band|interval)$/.test(key)
    && Array.isArray(value)
    && value.length === 2
    && value.every((bound) => typeof bound === "number" && Number.isFinite(bound))
  );
}

/** A row that carries its own label is named by it, and the label is not
 * repeated as a fact of the row. */
function namedRow(item: unknown, index: number): [string, unknown] {
  if (item && typeof item === "object" && !Array.isArray(item)) {
    const { label, ...rest } = item as Record<string, unknown>;
    if (isAtomicFact(label)) return [String(label), rest];
  }
  return [`[${index}]`, item];
}

function collectFamilyEvidenceValues(
  value: unknown,
  path: string[],
  emit: (path: string[], value: string | number | boolean) => boolean,
): boolean {
  if (isAtomicFact(value)) return path.length > 0 ? emit(path, value) : true;
  const key = path[path.length - 1] ?? "";
  if (isInterval(key, value)) {
    return emit([...path, "lower"], value[0]) && emit([...path, "upper"], value[1]);
  }
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      const [name, row] = namedRow(item, index);
      if (!collectFamilyEvidenceValues(row, [...path, name], emit)) return false;
    }
    return true;
  }
  if (!value || typeof value !== "object") return true;
  for (const [childKey, item] of Object.entries(value)) {
    if (path.length === 0 && FAMILY_EVIDENCE_ENVELOPE_FIELDS.has(childKey)) continue;
    if (!collectFamilyEvidenceValues(item, [...path, childKey], emit)) return false;
  }
  return true;
}

/** Make the declared model-family evidence citable in a generated report.
 *
 * The input is the projection the run-detail route serves under
 * `family_evidence`: the same bounded object the Agent reads, so a written
 * report and the Agent quote the same numbers. Before v1.8.10 the writer saw
 * only the coefficient row; for an event-study estimator that meant the
 * overall effect and nothing else. Nothing here names a family: rows are named
 * by their own label and two-number intervals become lower and upper bounds.
 */
export function buildFamilyEvidenceFacts(
  evidence: Record<string, unknown> | null | undefined,
  startAt = 0,
  provenance: { nodeKey: string; nodeLabel: string },
): CitableFact[] {
  const facts: CitableFact[] = [];
  if (!evidence) return facts;
  let counter = startAt;
  let truncated = false;
  collectFamilyEvidenceValues(evidence, [], (path, value) => {
    // Reserve one slot for the truncation marker, so a long result cannot
    // look complete after later evidence was discarded.
    if (facts.length >= MAX_FAMILY_EVIDENCE_FACTS - 1) {
      truncated = true;
      return false;
    }
    const key = path.join(":");
    facts.push({
      id: `c${++counter}`,
      node_key: provenance.nodeKey,
      node_label: provenance.nodeLabel,
      field: `family:${key}`,
      label: `${provenance.nodeLabel} — ${path.join(" · ").replace(/_/g, " ")}`,
      value,
    });
    return true;
  });
  if (truncated) {
    facts.push({
      id: `c${++counter}`,
      node_key: provenance.nodeKey,
      node_label: provenance.nodeLabel,
      field: "family:facts_truncated",
      label: `${provenance.nodeLabel} — family evidence truncated at ${MAX_FAMILY_EVIDENCE_FACTS - 1} facts`,
      value: true,
    });
  }
  return facts;
}

/** Bounded whitelist of truthful scalar evidence from ARMA-GARCH artifacts. */
export function buildTimeSeriesFacts(
  artifacts: TimeSeriesArtifactMap,
  startAt = 0,
  provenance: { nodeKey: string; nodeLabel: string } = {
    nodeKey: "model:arma_garch_1",
    nodeLabel: "ARMA-GARCH",
  },
): CitableFact[] {
  const facts: CitableFact[] = [];
  let counter = startAt;
  const add = (field: string, label: string, value: unknown) => {
    if (!isAtomicFact(value) || facts.length >= 80) return;
    facts.push({
      id: `c${++counter}`,
      node_key: provenance.nodeKey,
      node_label: provenance.nodeLabel,
      field,
      label,
      value,
    });
  };
  const from = (
    artifactId: string,
    path: string[],
    field: string,
    label: string,
  ) => add(field, label, valueAt(artifactPayload(artifacts[artifactId]), path));

  // Keep the analysis contract alongside model evidence so a generated report
  // cannot silently describe transformed/filtered data as the raw source.
  from("ts.analysis_contract", ["transform"], "ts:contract:transform", "analysis transform");
  from(
    "ts.analysis_contract",
    ["missing_value_policy"],
    "ts:contract:missing_value_policy",
    "missing-value policy",
  );
  from(
    "ts.analysis_contract",
    ["estimation_strategy"],
    "ts:contract:estimation_strategy",
    "estimation strategy",
  );
  from(
    "ts.data_audit",
    ["data_quality", "finite_value_count"],
    "ts:data:analysis_observations",
    "analysis-view observations",
  );
  const auditDiagnostics = valueAt(artifactPayload(artifacts["ts.data_audit"]), ["diagnostics"]);
  if (Array.isArray(auditDiagnostics)) {
    const missingExclusion = auditDiagnostics.find((diagnostic) => (
      diagnostic
      && typeof diagnostic === "object"
      && !Array.isArray(diagnostic)
      && (diagnostic as Record<string, unknown>).code === "MISSING_OBSERVATIONS_EXCLUDED"
    ));
    if (missingExclusion && typeof missingExclusion === "object" && !Array.isArray(missingExclusion)) {
      add(
        "ts:data:excluded_missing_observations",
        "excluded missing observations",
        valueAt(missingExclusion as Record<string, unknown>, ["evidence", "excluded_missing_count"]),
      );
    }
  }

  from("ts.arma_selection", ["final_selected_candidate_id"], "ts:arma:selected_candidate", "selected ARMA specification");
  from("ts.volatility_selection", ["selected_candidate_id"], "ts:variance:selected_candidate", "selected variance specification");
  for (const [stage, prefix] of [["mean_stage", "mean"], ["variance_stage", "variance"]] as const) {
    for (const criterion of ["aic", "aicc", "bic"] as const) {
      from(
        "ts.final_model",
        ["validation_fit", stage, criterion],
        `ts:${prefix}:${criterion}`,
        `${prefix} ${criterion.toUpperCase()}`,
      );
    }
  }

  const parameters = artifactPayload(artifacts["ts.parameters"]);
  for (const [section, prefix] of [
    ["mean_candidate", "mean"],
    ["selected_variance_candidate", "variance"],
  ] as const) {
    const values = valueAt(parameters, [section]);
    if (!values || typeof values !== "object" || Array.isArray(values)) continue;
    for (const [name, value] of Object.entries(values as Record<string, unknown>)) {
      add(`ts:parameter:${prefix}:${name}`, `${prefix} parameter ${name}`, value);
    }
  }
  const variance = valueAt(parameters, ["selected_variance_candidate"]);
  if (variance && typeof variance === "object" && !Array.isArray(variance)) {
    const record = variance as Record<string, unknown>;
    const alpha = Object.entries(record)
      .filter(([key, value]) => key.startsWith("alpha[") && typeof value === "number")
      .reduce((sum, [, value]) => sum + Number(value), 0);
    const beta = Object.entries(record)
      .filter(([key, value]) => key.startsWith("beta[") && typeof value === "number")
      .reduce((sum, [, value]) => sum + Number(value), 0);
    if (alpha > 0 || beta > 0) {
      const persistence = alpha + beta;
      add("ts:volatility:persistence", "volatility persistence", persistence);
      if (persistence > 0 && persistence < 1) {
        add(
          "ts:volatility:half_life_observations",
          "volatility half-life (observations)",
          Math.log(0.5) / Math.log(persistence),
        );
      }
    }
  }

  for (const [path, field, label] of [
    [["arch_lm", "p_value"], "ts:diagnostic:arch_lm_p_value", "ARCH-LM p-value"],
    [["normality", "p_value"], "ts:diagnostic:normality_p_value", "normality p-value"],
    [["normality", "skew"], "ts:diagnostic:skew", "standardized residual skew"],
    [["normality", "kurtosis"], "ts:diagnostic:kurtosis", "standardized residual kurtosis"],
  ] as const) {
    from("ts.final_diagnostics", [...path], field, label);
  }
  for (const metric of [
    "validation_n", "successful_forecast_n", "mae", "rmse", "mean_error",
    "interval_coverage", "average_interval_width", "exception_count", "exception_rate",
    "pinball_loss",
  ]) {
    from("ts.forecast_metrics", [metric], `ts:validation:${metric}`, `validation ${metric}`);
  }
  for (const metric of [
    "conditional_mean", "conditional_variance", "conditional_volatility",
    "lower_bound", "upper_bound", "lower_quantile",
  ]) {
    from("ts.next_forecast", [metric], `ts:forecast:${metric}`, `next forecast ${metric}`);
  }
  return facts;
}

function collectNumericLeaves(
  value: unknown,
  path: string,
  leaves: Array<{ path: string; value: number }>,
  limit: number,
): boolean {
  if (typeof value === "number" && Number.isFinite(value)) {
    if (leaves.length >= limit) return true;
    leaves.push({ path, value });
    return false;
  }
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      if (collectNumericLeaves(item, `${path}[${index}]`, leaves, limit)) {
        return true;
      }
    }
    return false;
  }
  if (value && typeof value === "object") {
    // A chart's row sample is not a citable report fact: a report cites the summary
    // of every row, and the sample reaches a provider only where rows may.
    if ((value as { protocol_version?: unknown }).protocol_version === FIGURE_ROWS_PROTOCOL) return false;
    for (const [key, item] of Object.entries(value)) {
      if (collectNumericLeaves(item, `${path}.${key}`, leaves, limit)) {
        return true;
      }
    }
  }
  return false;
}

export function buildFactTable(
  forest: ForestViewModel,
  activeRunId: string,
): { facts: CitableFact[]; scope: ReportScope; fingerprints: string[] } {
  const pathNodes = forest.nodes.filter((node) => (node.runs ?? []).includes(activeRunId));
  const facts: CitableFact[] = [];
  const fingerprints: string[] = [];
  let counter = 0;
  const nextId = () => `c${++counter}`;

  for (const node of pathNodes) {
    const resolved = resolveNodeOperationContext({
      forest,
      selected_forest_node_key: node.nodeKey,
      active_head_run_id: activeRunId,
    });
    if (!resolved.ok) continue;
    const context = resolved.context;
    fingerprints.push(context.context_fingerprint);
    const nodeLabel = context.selection.display_label;

    for (const [key, value] of Object.entries(context.node_payload.params)) {
      if (!isAtomicFact(value)) continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `param:${key}`,
        label: key,
        value,
      });
    }
    const metrics = context.node_payload.metrics ?? {};
    for (const [key, value] of Object.entries(metrics)) {
      if (value === null || value === undefined) continue;
      if (typeof value === "object") continue; // scalars only — keep facts atomic
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `metric:${key}`,
        label: key,
        value,
      });
    }
    // v1.6.11 C-2 — model coefficient rows (serve-time decoration) expand into
    // atomic per-term facts so the report can cite estimates and p-values.
    const coefficientRows = Array.isArray(metrics.coefficients)
      ? metrics.coefficients
      : [];
    for (const row of coefficientRows) {
      if (!row || typeof row !== "object") continue;
      const { variable, estimate, std_error, p_value } = row as Record<string, unknown>;
      if (typeof variable !== "string" || typeof estimate !== "number") continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `coef:${variable}`,
        label: `coefficient (${variable})`,
        value: estimate,
      });
      if (typeof std_error === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_se:${variable}`,
          label: `std. error (${variable})`,
          value: std_error,
        });
      }
      if (typeof p_value === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_p:${variable}`,
          label: `p-value (${variable})`,
          value: p_value,
        });
      }
    }
    for (const decision of context.node_payload.decisions) {
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `decision:${decision.id}`,
        label: decision.question,
        value: decision.picked,
      });
    }
  }

  return {
    facts,
    scope: {
      run_id: activeRunId,
      node_count: pathNodes.length,
      node_keys: pathNodes.map((n) => n.nodeKey),
    },
    fingerprints,
  };
}
