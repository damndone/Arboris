import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { formatScalar, ResultValue } from "./ResultValue";

it("reads a saved result as fields and tables, with the exact JSON one click away", () => {
  const value = { test_statistic: 12.3456789, p_value: 0.000123456, df: 2, groups: [{ level: "a", n: 10 }, { level: "b", n: 12 }], method: "kruskal_wallis" };
  render(<ResultValue value={value} />);
  expect(screen.getByText("Test statistic")).toBeInTheDocument();
  expect(screen.getByText("12.3457")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Level" })).toBeInTheDocument();
  expect(screen.getAllByRole("row")).toHaveLength(3);
  expect(screen.queryByText(/"p_value": 0.000123456/)).toBeNull();
  const exact = screen.getByText("Exact JSON").parentElement as HTMLDetailsElement;
  exact.open = true;
  fireEvent(exact, new Event("toggle"));
  expect(screen.getByText(/"p_value": 0.000123456/)).toBeVisible();
});

it("formats scalars for reading", () => {
  expect(formatScalar(null)).toBe("—");
  expect(formatScalar(true)).toBe("Yes");
  expect(formatScalar(1234567)).toBe("1,234,567");
  expect(formatScalar(0.1234567891)).toBe("0.123457");
});

it("loads and switches individual saved regression trees on demand", () => {
  render(<ResultValue value={{
    result: { operation_id: "prediction.native_random_forest_regression", metrics: { rmse: 0.5 },
      mean_baseline: { rmse: 3 }, split: { train_rows: 8, test_rows: 2 }, model_structure: { tree_count: 2 } },
    local_detail: { prediction_basis: { kind: "random_forest_regression", predictor_order: ["x"],
      trees: [4.125, 7.875].map((training_mean, tree_id) => ({
        tree_id, nodes: [{ node_id: 0, feature_index: -1, training_rows: 8, training_mean, training_mse: 0 }],
      })) } },
  }} />);
  expect(screen.queryByRole("combobox", { name: "Saved tree" })).toBeNull();
  const details = screen.getByText("Inspect individual trees").parentElement as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect(screen.getByRole("cell", { name: "4.125" })).toBeVisible();
  fireEvent.change(screen.getByRole("combobox", { name: "Saved tree" }), { target: { value: "1" } });
  expect(screen.getByRole("cell", { name: "7.875" })).toBeVisible();
  expect(screen.queryByRole("cell", { name: "4.125" })).toBeNull();
});

it("compares held-out probabilities and inspects a saved classification tree", () => {
  render(<ResultValue value={{
    result: { operation_id: "prediction.native_random_forest_classification", metrics: { log_loss: 0.53 },
      prevalence_baseline: { probability: 0.5, log_loss: 0.69 },
      split: { train_rows: 8, test_rows: 4 }, model_structure: { tree_count: 2 } },
    local_detail: { prediction_basis: { kind: "random_forest_classification", predictor_order: ["x"],
      trees: [0.125, 0.875].map(probability => ({
        nodes: [{ node_id: 0, feature_index: -1, training_rows: 8, probability }],
      })) } },
  }} />);
  expect(screen.getByText("Training-prevalence baseline")).toBeVisible();
  const details = screen.getByText("Inspect individual trees").parentElement as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  fireEvent.change(screen.getByRole("combobox", { name: "Saved tree" }), { target: { value: "1" } });
  expect(screen.getByRole("columnheader", { name: "Smoothed probability" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "0.875" })).toBeVisible();
});

it("shows Johansen hypotheses by rank with the interpretation boundary", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.johansen_rank", n_effective: 78,
      ranks: [0, 1, 2], canonical_eigenvalues: [0.4, 0.2, 0.1],
      trace_statistics: [45.4, 16.9, 5.9], max_eigenvalue_statistics: [28.5, 11, 5.9],
      policy: { series_columns: ["a", "b", "c"], difference_lags: 1 } },
  }} />);
  expect(screen.getByRole("columnheader", { name: "Trace statistic" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "45.4" })).toBeVisible();
  expect(screen.getByText(/Critical values and rank selection/)).toBeVisible();
});

it("shows jointly fitted smoothing and the held-out comparison", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.holt_winters_fit_joint", parameters: { alpha: 0.25, beta: 0.12, gamma: 0.42 },
      fit: { n_observed: 160 }, forecast: { steps: 2 }, estimation: { method: "joint_conditional_training_sse" },
      policy: { season_period: 4, confidence_level: 0.99 },
      holdout: { training_steps: 152, metrics: { rmse: 1.2, mae: 1.0, naive_rmse: 2.3, naive_mae: 2.0 } } },
  }} />);
  expect(screen.getByText("Jointly fitted additive Holt-Winters")).toBeVisible();
  expect(screen.getByText("Seasonal smoothing (gamma)")).toBeVisible();
  expect(screen.getByRole("cell", { name: "Seasonal naive" })).toBeVisible();
});

it("shows validation selection separately from final held-out Ridge errors", () => {
  render(<ResultValue value={{ result: {
    operation_id: "prediction.native_ridge_selection",
    selection: { selected_alpha: 6, fit_rows: 6, validation_rows: 2, refit_rows: 8,
      candidates: [{ alpha: 1, validation_rmse: 0.8 }, { alpha: 6, validation_rmse: 0 }] },
    metrics: { rmse: 0.5 }, mean_baseline: { rmse: 1.5 }, split: { train_rows: 8, test_rows: 2 },
  } }} />);
  expect(screen.getByText("Selected penalty")).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Validation RMSE" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "Training-mean baseline" })).toBeVisible();
});

it("compares both saved equity paths and shows the two fees for a period", () => {
  const path = (ending_equity: number, fees: number) => ({ rows: [
    { row: 0, end_time: "2026-01-02", ending_equity, fees, net_return: ending_equity / 100 - 1 },
  ] });
  render(<ResultValue value={{
    result: { operation_id: "quant.replay_fee_comparison", inputs: { base_transaction_cost_bps: 0,
      higher_transaction_cost_bps: 25 },
    metrics: { base: { final_equity: 108, total_fees: 0 }, higher: { final_equity: 106, total_fees: 2 },
      higher_minus_base: { final_equity: -2, cumulative_net_return: -0.02, total_fees: 2 } } },
    local_detail: { fee_comparison: { base: path(108, 0), higher: path(106, 2) } },
  }} />);
  expect(screen.getByRole("columnheader", { name: "Final equity" })).toBeVisible();
  const chart = screen.getByRole("img", { name: "Fee comparison equity" });
  expect(chart).toBeVisible();
  fireEvent.keyDown(chart, { key: "End" });
  const detail = screen.getByRole("tooltip", { name: "Fee comparison equity details" });
  expect(detail).toHaveTextContent("Higher fee paid");
  expect(detail).toHaveTextContent("2026-01-02");
});

it("puts the result before its provenance and tabulates rows with one level of nesting", () => {
  const saved = {
    schema_version: "v1",
    request_fingerprint: "sha256:abc",
    result: { family: "correlations", result: { results: [
      { variables: ["a", "b"], nobs: 40, p_value: 2.4e-17, effect: { r: 0.923 }, warnings: [] },
      { variables: ["a", "c"], nobs: 40, p_value: 0.037, effect: { r: 0.331 }, warnings: [] },
    ] } },
  };
  render(<ResultValue value={saved} />);
  expect(screen.getByRole("columnheader", { name: "Effect r" })).toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "Warnings" })).toBeNull();
  expect(screen.getByText("a, b")).toBeInTheDocument();
  expect(screen.getByText("2.4E-17")).toBeInTheDocument();
  expect(screen.getByText("Request fingerprint")).not.toBeVisible();
});

it("shows a local portfolio curve and keeps its rows out of provenance", () => {
  render(<ResultValue value={{
    result: { operation_id: "quant.replay", metrics: { final_equity: 110 } },
    local_detail: { series: { total_rows: 3, truncated: true, rows: [
      { row: 0, end_time: "2027-01-31T16:00:00Z", ending_equity: 100 },
      { row: 2, execution_time: "2027-03-01T09:30:00Z", end_time: "2027-03-31T16:00:00Z",
        ending_equity: 110, fees: 0.75, net_return: 0.0525, drawdown: 0.0125 },
    ] } },
  }} />);
  const chart = screen.getByRole("img", { name: "Portfolio equity" });
  expect(within(chart).getByText("Holding period order")).toBeVisible();
  expect(within(chart).getByText("Equity (input units)")).toBeVisible();
  fireEvent.keyDown(chart, { key: "End" });
  const detail = screen.getByRole("tooltip", { name: "Portfolio equity details" });
  expect(detail).toHaveTextContent("2027-03-31T16:00:00Z");
  expect(detail).toHaveTextContent("2027-03-01T09:30:00Z");
  expect(detail).toHaveTextContent("0.75");
  expect(detail).toHaveTextContent("5.25%");
  expect(detail).toHaveTextContent("1.25%");
  expect(screen.getByText("2 of 3 periods displayed. Metrics use all periods.")).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Ending equity" })).toBeVisible();
  expect(screen.queryByText("Local detail")).toBeNull();
});

it("renders forecast periods as rows with predictive interval bounds", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.local_level", forecast: { steps: 2 }, policy: { confidence_level: 0.95 } },
    local_detail: { forecast: { steps: 2, time: ["2027-01-01", "2027-02-01T00:00:00Z"], mean: [2, 3], lower: [0, 1], upper: [4, 5] } },
  }} />);
  const chart = screen.getByRole("img", { name: "Forecast with prediction intervals" });
  expect(within(chart).getByText("Forecast period")).toBeVisible();
  expect(within(chart).getByText("Predicted value")).toBeVisible();
  fireEvent.keyDown(chart, { key: "End" });
  const detail = screen.getByRole("tooltip", { name: "Forecast with prediction intervals details" });
  expect(detail).toHaveTextContent("2027-02-01T00:00:00Z");
  expect(detail).toHaveTextContent("95% prediction interval");
  expect(detail).toHaveTextContent("3");
  expect(screen.getByRole("columnheader", { name: "Lower" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "2027-02-01T00:00:00Z" })).toBeVisible();
});

it("reads the rolling window's maximum and actual asset values in input units", () => {
  render(<ResultValue value={{
    result: { operation_id: "quant.rolling_risk", metrics: { window: 12 }, inputs: { window: 12 } },
    local_detail: {
      series: { total_rows: 2, rows: [
        { row: 11, time: "2027-01-01T08:00:00Z", volatility: [0.012, 0.016] },
        { row: 12, time: "2027-01-02T08:00:00Z", volatility: [0.028, 0.009] },
      ] },
      latest_covariance: { columns: ["asset_a", "asset_b"], matrix: [[0.0001, 0], [0, 0.0002]] },
    },
  }} />);
  const chart = screen.getByRole("img", { name: "Highest asset volatility in each displayed window" });
  expect(within(chart).getByText("Observation order")).toBeVisible();
  expect(within(chart).getByText("Volatility (input return units)")).toBeVisible();
  fireEvent.keyDown(chart, { key: "End" });
  const detail = screen.getByRole("tooltip", { name: "Highest asset volatility in each displayed window details" });
  expect(detail).toHaveTextContent("2027-01-02T08:00:00Z");
  expect(detail).toHaveTextContent("asset_a");
  expect(detail).toHaveTextContent("0.028");
  expect(detail).toHaveTextContent("asset_b");
  expect(detail).toHaveTextContent("0.009");
  expect(detail).toHaveTextContent("12 observations");
});

it("shows the requested prediction level without rounding it to 100%", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.local_level", policy: { confidence_level: 0.9999999 } },
    local_detail: { forecast: { time: [1], mean: [2], lower: [0], upper: [4] } },
  }} />);
  expect(screen.getByText("99.99999% prediction interval")).toBeVisible();
});

it("compares walk-forward portfolios on the same end dates and exposes the stored decision cutoff", () => {
  const strategy = [
    { end_time: "2020-02-04", ending_equity: 108, fees: 0.3 },
    { end_time: "2020-02-05", ending_equity: 110, fees: 0.1 },
  ];
  render(<ResultValue value={{
    result: { operation_id: "quant.min_variance_walk_forward", inputs: { transaction_cost_bps: 10 },
      metrics: { strategy: { cumulative_net_return: 0.1 }, benchmark: { cumulative_net_return: 0.08 } } },
    local_detail: { strategy_series: { rows: strategy },
      benchmark_series: { rows: strategy.map((row) => ({ ...row, ending_equity: row.ending_equity - 2 })) },
      decisions: { rows: strategy.map((row, i) => ({ end_time: row.end_time, as_of_time: `2020-02-0${i + 2}`,
        execution_time: `2020-02-0${i + 3}` })) } },
  }} />);
  expect(screen.getByRole("row", { name: /Equal weights.*8%/ })).toBeVisible();
  const chart = screen.getByRole("img", { name: "Walk-forward equity" });
  fireEvent.keyDown(chart, { key: "End" });
  const details = screen.getByRole("tooltip", { name: "Walk-forward equity details" });
  expect(details).toHaveTextContent("2020-02-05");
  expect(details).toHaveTextContent("Training cutoff2020-02-03");
  expect(details).toHaveTextContent("Execution2020-02-04");
  expect(details).toHaveTextContent("Equal weights108");
});

it("distinguishes the fitted forecast from the supplied FIGARCH coefficients and local lag weights", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.figarch_fixed", parameters: { d: 0.35 },
      policy: { truncation: 32 }, fit: { n_observed: 64, retained_weight_mass: 0.8, omitted_weight_mass: 0.2 },
      forecast: { steps: 2 } },
    local_detail: { variance_forecast: { time: [65, 66], variance: [0.8, 1.1] },
      lag_weights: { first_lag: 1, values: [0.1, 0.075] } },
  }} />);
  expect(screen.getByText("FIGARCH with fixed coefficients")).toBeVisible();
  expect(screen.getByText("Undefined for the infinite-lag model")).toBeVisible();
  const details = screen.getByText("Retained fractional lag weights").parentElement as HTMLDetailsElement;
  expect(screen.queryByRole("columnheader", { name: "Weight" })).toBeNull();
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect(screen.getByRole("columnheader", { name: "Weight" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "0.075" })).toBeVisible();
});

it("shows conditional variance in squared input units with the exact date and no mean interval", () => {
  render(<ResultValue value={{
    result: {
      operation_id: "time_series.native_volatility", fit: { n_observed: 300, persistence: 0.83 },
      forecast: { steps: 2, last: { variance: 0.004 } }, policy: { family: "garch_1_1" },
      holdout: { metrics: { mean_gaussian_loss: -1.2, variance_mae: 0.003 } },
    },
    local_detail: { variance_forecast: { time: ["2027-01-02", "2027-01-03"], variance: [0.003, 0.004] } },
  }} />);
  const chart = screen.getByRole("img", { name: "Conditional variance forecast" });
  expect(within(chart).getByText("Variance (squared input units)")).toBeVisible();
  fireEvent.keyDown(chart, { key: "End" });
  expect(screen.getByRole("tooltip")).toHaveTextContent("2027-01-03");
  expect(screen.getByRole("tooltip")).toHaveTextContent("0.004");
  expect(screen.getByRole("columnheader", { name: "Variance" })).toBeVisible();
  expect(screen.queryByText(/prediction interval/i)).toBeNull();
});

it("presents the selected training alpha and lets the reader inspect each training candidate", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.holt_winters_fit_alpha", fit: { n_observed: 20 },
      forecast: { steps: 1 }, policy: { season_period: 4 }, parameters: { alpha: 0.05, beta: 0.2, gamma: 0.1 },
      estimation: { method: "training_prefix_alpha_grid", training_steps: 16, training_sse: 2.5 } },
    local_detail: { alpha_grid_sse: [2.5, 3] },
  }} />);
  expect(screen.getByText("Selected alpha")).toBeVisible();
  expect(screen.getByText("Training periods")).toBeVisible();
  const details = screen.getByText("Training alpha search").parentElement as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect(screen.getByRole("columnheader", { name: "Training SSE" })).toBeVisible();
});

it("switches a multivariate forecast by the selected series while keeping its marginal interval", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.native_var", fit: { n_effective: 48 }, forecast: { steps: 2 },
      policy: { lag_order: 2, confidence_level: 0.9 } },
    local_detail: { series_forecasts: {
      a: { time: [51, 52], mean: [3, 4], lower: [1, 2], upper: [5, 6] },
      b: { time: [51, 52], mean: [20, 30], lower: [10, 20], upper: [40, 50] },
    } },
  }} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Forecast series" }), { target: { value: "b" } });
  const chart = screen.getByRole("img", { name: "Forecast with prediction intervals" });
  fireEvent.keyDown(chart, { key: "End" });
  const detail = screen.getByRole("tooltip");
  expect(detail).toHaveTextContent("30");
  expect(detail).toHaveTextContent("90% marginal prediction interval");
});

it("renders a learned tree split by predictor name and preserves the smoothed probabilities", () => {
  render(<ResultValue value={{
    result: { operation_id: "prediction.native_cart", metrics: { log_loss: 0.42 }, split: { train_rows: 10, test_rows: 4 },
      prevalence_baseline: { probability: 0.5, log_loss: 0.693 }, model_structure: { node_count: 3, root_predictor: "income" } },
    local_detail: { prediction_basis: { predictor_order: ["income"],
      nodes: [{ node_id: 0, feature_index: 0, threshold: 5.3, left_id: 1, right_id: 2, training_rows: 10, probability: 0.5 }] } },
  }} />);
  expect(screen.getByText("Training-prevalence baseline")).toBeVisible();
  const tree = screen.getByText("Tree splits and leaf probabilities").parentElement as HTMLDetailsElement;
  tree.open = true;
  fireEvent(tree, new Event("toggle"));
  expect(screen.getByRole("cell", { name: "income ≤ 5.3" })).toBeVisible();
});

it("uses the shared tree display for original-unit regression means and MSE", () => {
  render(<ResultValue value={{
    result: { operation_id: "prediction.native_cart_regression", metrics: { mse: 2.5, rmse: 1.581, mae: 1.5 },
      mean_baseline: { prediction: 2, mse: 4.5, rmse: 2.121, mae: 1.5 }, split: { train_rows: 8, test_rows: 2 },
      model_structure: { node_count: 3, root_predictor: "income" } },
    local_detail: { prediction_basis: { kind: "regression", predictor_order: ["income"],
      nodes: [{ node_id: 0, feature_index: 0, threshold: 5.3, left_id: 1, right_id: 2, training_rows: 8,
                training_mean: 2, training_mse: 4, mse_gain: 1.333 }] } },
  }} />);
  expect(within(screen.getByRole("row", { name: /Training-mean baseline/ })).getByRole("cell", { name: "4.5" })).toBeVisible();
  const tree = screen.getByText("Tree splits and leaf means").parentElement as HTMLDetailsElement;
  tree.open = true;
  fireEvent(tree, new Event("toggle"));
  expect(screen.getByRole("cell", { name: "income ≤ 5.3" })).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Training MSE" })).toBeVisible();
  expect(screen.queryByRole("columnheader", { name: "Smoothed probability" })).toBeNull();
});

it("shows portfolio weights and keeps sample and objective covariances distinct", () => {
  render(<ResultValue value={{
    result: { operation_id: "quant.min_variance", metrics: { sample_variance: 0.003, objective_variance: 0.004 },
      allocation: { asset_a: 0.7, asset_b: 0.3 } },
    local_detail: { sample_covariance: { columns: ["asset_a"], matrix: [[0.005]] },
      objective_covariance: { columns: ["asset_a"], matrix: [[0.006]] }, cutoff: { last_period: 8, as_of_time: "2026-11-05" } },
  }} />);
  expect(screen.getByRole("cell", { name: "70%" })).toBeVisible();
  expect(screen.getByText("Sample covariance")).toBeVisible();
  expect(screen.getByText("Objective covariance")).toBeVisible();
  expect(screen.getByText("2026-11-05")).toBeVisible();
});

it("shows the ACF and PACF by lag with their exact values and no invented significance bands", () => {
  render(<ResultValue value={{
    result: { operation_id: "time_series.correlogram", n_observations: 24, metrics: { lag_one_acf: -0.25 } },
    local_detail: { correlogram: { lags: [0, 1, 2], acf: [1, -0.25, 0.1], pacf: [null, -0.25, 0.04] } },
  }} />);
  const acf = screen.getByRole("img", { name: "Autocorrelation (ACF)" });
  const pacf = screen.getByRole("img", { name: "Partial autocorrelation (PACF)" });
  expect(within(acf).getByText("Lag (periods)")).toBeVisible();
  expect(pacf.querySelectorAll(".research-curve__stem")).toHaveLength(2);
  fireEvent.keyDown(pacf, { key: "Home" });
  const detail = screen.getByRole("tooltip", { name: "Partial autocorrelation (PACF) details" });
  expect(detail).toHaveTextContent("Lag 1");
  expect(detail).toHaveTextContent("-0.25");
  expect(screen.getByRole("columnheader", { name: "PACF" })).toBeVisible();
  expect(screen.queryByText(/prediction interval/i)).toBeNull();
});

it("compares held-out logistic metrics against training prevalence and explains missing AUC", () => {
  render(<ResultValue value={{ result: {
    operation_id: "prediction.native_logistic", split: { train_rows: 15, test_rows: 5 },
    metrics: { log_loss: 0.42, brier_score: 0.12, accuracy: 0.8, roc_auc: null },
    prevalence_baseline: { probability: 0.5, log_loss: 0.693, brier_score: 0.25, accuracy: 0, roc_auc: null },
    roc_auc_reason: "single_class_test_outcome",
  } }} />);
  expect(screen.getByText("Training-prevalence baseline")).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Log loss" })).toBeVisible();
  expect(screen.getByText("ROC AUC needs both classes in the holdout.")).toBeVisible();
  expect(screen.queryByText("RMSE")).toBeNull();
});

it("shows signed historical loss and the exact portfolio window", () => {
  render(<ResultValue value={{
    result: { operation_id: "quant.replay_tail_risk",
      metrics: { value_at_risk: -0.004, expected_shortfall: 0.006, confidence_bps: 9500, window: 20 } },
    local_detail: { tail_window: { first_period: 2, as_of_period: 21, as_of_end_time: "2025-01-10" } },
  }} />);
  expect(screen.getByText("-0.4%")).toBeVisible();
  expect(screen.getByText("0.6%")).toBeVisible();
  expect(screen.getByText("95%")).toBeVisible();
  expect(screen.getByText("2025-01-10")).toBeVisible();
});
