// v1.9.0 — a saved result, read rather than dumped: records become tables,
// objects become labelled lists, numbers keep six significant digits. The
// exact JSON stays one click away for anyone who needs it verbatim.

import { useState, type ReactNode } from "react";
import { ResearchCurve, type ResearchPoint } from "./ResearchCurve";
import "./operations.css";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

const MAX_ROWS = 200;
const MAX_DEPTH = 4;
const numberFormat = new Intl.NumberFormat("en", { maximumSignificantDigits: 6 });

const isRecord = (value: Json): value is { [key: string]: Json } => typeof value === "object" && value !== null && !Array.isArray(value);
const isScalar = (value: Json) => value === null || typeof value !== "object";

export function label(key: string): string {
  const words = key.replace(/[_.]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

const smallFormat = new Intl.NumberFormat("en", { notation: "scientific", maximumSignificantDigits: 3 });

export function formatScalar(value: Json): string {
  if (value === null) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value) && Math.abs(value) < 1e15) return value.toLocaleString("en");
    // Tiny values (p-values above all) keep their magnitude instead of rounding to 0.
    return value !== 0 && Math.abs(value) < 1e-4 ? smallFormat.format(value) : numberFormat.format(value);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/** A record that reads as one table row: scalars, lists of scalars, and one
 *  level of flat sub-records (`effect: {r}` becomes the column "Effect r"). */
function flatRow(row: Json): { [key: string]: Json } | null {
  if (!isRecord(row)) return null;
  const flat: { [key: string]: Json } = {};
  for (const [key, value] of Object.entries(row)) {
    if (isScalar(value)) flat[key] = value;
    else if (Array.isArray(value) && value.every(isScalar)) flat[key] = value.map(formatScalar).join(", ");
    else if (isRecord(value) && Object.values(value).every(isScalar)) {
      for (const [sub, inner] of Object.entries(value)) flat[`${key} ${sub}`] = inner;
    } else return null;
  }
  return flat;
}

const empty = (value: Json | undefined) => value === undefined || value === null || value === "";

function Table({ rows }: { rows: Array<{ [key: string]: Json }> }) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((column) => rows.some((row) => !empty(row[column])));
  return (
    <div className="op-result__table">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column} scope="col">{label(column)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, MAX_ROWS).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column} data-numeric={typeof row[column] === "number" || undefined}>{formatScalar(row[column] ?? null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="op-result__more">First {MAX_ROWS} of {rows.length.toLocaleString("en")} rows.</p>}
    </div>
  );
}

function Value({ value, depth }: { value: Json; depth: number }): ReactNode {
  if (isScalar(value)) return <span data-numeric={typeof value === "number" || undefined}>{formatScalar(value)}</span>;
  if (depth >= MAX_DEPTH) return <code>{JSON.stringify(value)}</code>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="op-result__none">None</span>;
    if (value.every(isScalar)) return <span>{value.map(formatScalar).join(", ")}</span>;
    const rows = value.map(flatRow);
    if (rows.every((row) => row !== null)) return <Table rows={rows as Array<{ [key: string]: Json }>} />;
    return (
      <ol className="op-result__list">
        {value.slice(0, MAX_ROWS).map((item, index) => <li key={index}><Value value={item} depth={depth + 1} /></li>)}
      </ol>
    );
  }
  // What was computed reads before how it was computed.
  const entries = Object.entries(value).sort(([a], [b]) => Number(/^results?$/.test(b)) - Number(/^results?$/.test(a)));
  if (entries.length === 0) return <span className="op-result__none">None</span>;
  return (
    <dl className="op-result__fields">
      {entries.map(([key, item]) => (
        <div key={key} data-block={!isScalar(item) || undefined}>
          <dt>{label(key)}</dt>
          <dd><Value value={item} depth={depth + 1} /></dd>
        </div>
      ))}
    </dl>
  );
}

const numberArray = (value: Json | undefined): value is number[] =>
  Array.isArray(value) && value.length > 0 && value.every(item => typeof item === "number" && Number.isFinite(item));

const percent = new Intl.NumberFormat("en", { style: "percent", maximumSignificantDigits: 17 });
const chartNumber = (value: number) => Math.abs(value) >= 1e7 ? smallFormat.format(value) : formatScalar(value);
const chartTime = (time: Json | undefined) => typeof time === "number" || typeof time === "string" ? String(time) : "—";

function Forecast({ value, title, bandLabel }: { value: Json; title: string; bandLabel: string }) {
  if (!isRecord(value)) return null;
  const { time, mean, lower, upper } = value;
  if (!numberArray(mean) || !numberArray(lower) || !numberArray(upper) || !Array.isArray(time)
      || [lower.length, upper.length, time.length].some(length => length !== mean.length)) return null;
  const rows = mean.map((prediction, i) => ({ time: time[i], prediction, lower: lower[i], upper: upper[i] }));
  const { probability_low, probability_high } = value;
  const regimeProbabilities = numberArray(probability_low) && numberArray(probability_high)
    && probability_low.length === mean.length && probability_high.length === mean.length
    ? [probability_low, probability_high] : null;
  const points = rows.map((row, i) => ({
    position: i + 1, time: chartTime(row.time), value: row.prediction, lower: row.lower, upper: row.upper,
    details: regimeProbabilities ? [
      ["Lower-mean regime", percent.format(regimeProbabilities[0][i])],
      ["Higher-mean regime", percent.format(regimeProbabilities[1][i])],
    ] as [string, string][] : undefined,
  }));
  return <section>
    <h4>{title}</h4>
    <ResearchCurve title="Forecast with prediction intervals" xLabel="Forecast period" yLabel="Predicted value"
      points={points} formatValue={chartNumber} bandLabel={bandLabel} />
    <Table rows={rows} />
  </section>;
}

function SeriesForecast({ value, title, bandLabel }: { value: Json; title: string; bandLabel: string }) {
  const [selected, setSelected] = useState("");
  if (!isRecord(value)) return null;
  const names = Object.keys(value);
  const name = names.includes(selected) ? selected : names[0];
  if (name === undefined) return null;
  return <section>
    <label>Forecast series{" "}
      <select value={name} onChange={event => setSelected(event.target.value)}>
        {names.map(series => <option key={series} value={series}>{series}</option>)}
      </select>
    </label>
    <Forecast key={name} value={value[name]} title={`${title} · ${name}`} bandLabel={bandLabel} />
  </section>;
}

function Correlogram({ value }: { value: { [key: string]: Json } }) {
  const { lags, acf, pacf } = value;
  if (!numberArray(lags) || !numberArray(acf) || !Array.isArray(pacf)
      || acf.length !== lags.length || pacf.length !== lags.length) return null;
  const rows = lags.map((lag, index) => ({ lag, acf: acf[index], pacf: pacf[index] }));
  const acfPoints = rows.map(({ lag, acf }) => ({ position: lag, time: `Lag ${lag}`, value: acf }));
  const pacfPoints = rows.flatMap(({ lag, pacf }) => typeof pacf === "number"
    ? [{ position: lag, time: `Lag ${lag}`, value: pacf }] : []);
  return <section>
    <h4>Lag correlations</h4>
    <ResearchCurve title="Autocorrelation (ACF)" xLabel="Lag (periods)" yLabel="ACF"
      points={acfPoints} formatValue={chartNumber} stem />
    <ResearchCurve title="Partial autocorrelation (PACF)" xLabel="Lag (periods)" yLabel="PACF"
      points={pacfPoints} formatValue={chartNumber} stem />
    <p>Lag 0 ACF is 1 by definition. PACF starts at lag 1.</p>
    <Table rows={rows.slice(1).map(row => ({ lag: row.lag, ACF: row.acf, PACF: row.pacf }))} />
  </section>;
}

function VarianceForecast({ value, title }: { value: Json; title: string }) {
  if (!isRecord(value)) return null;
  const { time, variance } = value;
  if (!numberArray(variance) || !Array.isArray(time) || time.length !== variance.length) return null;
  const logVariance = numberArray(value.log_variance) && value.log_variance.length === variance.length ? value.log_variance : null;
  const rows = variance.map((estimate, index) => ({
    time: time[index], variance: estimate, ...(logVariance ? { log_variance: logVariance[index] } : {}),
  }));
  return <section>
    <h4>{title}</h4>
    <ResearchCurve title={title} xLabel="Forecast period" yLabel="Variance (squared input units)"
      points={rows.map((row, index) => ({
        position: index + 1, time: chartTime(row.time), value: row.variance,
        details: logVariance ? [["Log variance", chartNumber(logVariance[index])]] : undefined,
      }))}
      formatValue={chartNumber} />
    <Table rows={rows} />
  </section>;
}

function DeferredDetails({ title, children }: { title: string; children: () => ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details className="op-result__raw" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{title}</summary>
    {open && children()}
  </details>;
}

function LocalDetail({ value, result }: { value: { [key: string]: Json }; result: Json }) {
  const { forecast, holdout_forecast, holdout_origin_time, series, trace, latest_covariance, split_times, prediction_basis } = value;
  const alphaGrid = value.alpha_grid_sse;
  const rows = series && isRecord(series) && Array.isArray(series.rows) ? series.rows.filter(isRecord) : [];
  const equity = rows.map(row => row.ending_equity);
  const risk = rows.map(row => numberArray(row.volatility) ? Math.max(...row.volatility) : null);
  const positions = rows.map(row => typeof row.row === "number" ? row.row + 1 : null);
  const policy = isRecord(result) && isRecord(result.policy) ? result.policy : null;
  const level = policy?.confidence_level;
  const intervalLabel = policy?.forecast_interval === "conditional_two_normal_mixture_quantiles"
    ? "mixture prediction interval" : "prediction interval";
  const bandLabel = typeof level === "number" ? `${percent.format(level)} ${intervalLabel}` : "Prediction interval";
  const marginalBandLabel = typeof level === "number" ? `${percent.format(level)} marginal prediction interval` : "Marginal prediction interval";
  const inputs = isRecord(result) && isRecord(result.inputs) ? result.inputs : null;
  const assets = latest_covariance && isRecord(latest_covariance) && Array.isArray(latest_covariance.columns)
    ? latest_covariance.columns : [];
  const portfolioPoints: ResearchPoint[] = numberArray(positions) && numberArray(equity) ? rows.map((row, index) => {
    const details: [string, string][] = [["Holding period", String(positions[index])]];
    if (row.execution_time != null) details.push(["Execution time", chartTime(row.execution_time)]);
    if (typeof row.fees === "number") details.push(["Fees (input units)", String(row.fees)]);
    if (typeof row.net_return === "number") details.push(["Net return", percent.format(row.net_return)]);
    if (typeof row.drawdown === "number") details.push(["Drawdown", percent.format(row.drawdown)]);
    return { position: positions[index], time: chartTime(row.end_time), value: equity[index], details };
  }) : [];
  const riskPoints: ResearchPoint[] = numberArray(positions) && numberArray(risk) ? rows.map((row, index) => {
    const details: [string, string][] = [["Observation", String(positions[index])]];
    if (typeof inputs?.window === "number") details.push(["Window", `${inputs.window} observations`]);
    if (numberArray(row.volatility)) {
      const byAsset = row.volatility.map((value, index) => ({
        label: typeof assets[index] === "string" ? assets[index] : `Asset ${index + 1}`,
        value,
      })).sort((left, right) => right.value - left.value);
      for (const asset of byAsset.slice(0, 4)) details.push([asset.label, String(asset.value)]);
      if (byAsset.length > 4) details.push(["Other assets", `${byAsset.length - 4} more in the saved series`]);
    }
    return { position: positions[index], time: chartTime(row.time), value: risk[index], details };
  }) : [];
  return <div className="op-result__details">
    {isRecord(value.correlogram) && <Correlogram value={value.correlogram} />}
    {forecast && <Forecast value={forecast} title="Future forecast" bandLabel={bandLabel} />}
    {value.series_forecasts && <SeriesForecast value={value.series_forecasts} title="Future forecast" bandLabel={marginalBandLabel} />}
    {value.series_holdout_forecasts && <DeferredDetails title="Holdout forecasts by series">
      {() => <>
        {holdout_origin_time != null && <p>Training cutoff {formatScalar(holdout_origin_time)}</p>}
        <SeriesForecast value={value.series_holdout_forecasts} title="Fixed-origin holdout" bandLabel={marginalBandLabel} />
      </>}
    </DeferredDetails>}
    {value.variance_forecast && <VarianceForecast value={value.variance_forecast} title="Conditional variance forecast" />}
    {isRecord(value.lag_weights) && <DeferredDetails title="Retained fractional lag weights">
      {() => {
        const weights = value.lag_weights;
        if (!isRecord(weights) || !numberArray(weights.values) || typeof weights.first_lag !== "number") return null;
        const firstLag = weights.first_lag;
        return <Table rows={weights.values.map((weight, index) => ({ lag: firstLag + index, weight }))} />;
      }}
    </DeferredDetails>}
    {value.holdout_variance && <DeferredDetails title="Holdout variance">
      {() => <>
        {holdout_origin_time != null && <p>Training cutoff {formatScalar(holdout_origin_time)}</p>}
        <VarianceForecast value={value.holdout_variance} title="One-step holdout variance" />
      </>}
    </DeferredDetails>}
    {holdout_forecast && <DeferredDetails title="Holdout forecast">
      {() => <>
        {holdout_origin_time != null && <p>Training cutoff {formatScalar(holdout_origin_time)}</p>}
        <Forecast value={holdout_forecast} title="Fixed-origin holdout" bandLabel={bandLabel} />
      </>}
    </DeferredDetails>}
    {trace && isRecord(trace) && <DeferredDetails title="Filter diagnostics">
      {() => <Value value={trace} depth={0} />}
    </DeferredDetails>}
    {numberArray(alphaGrid) && <DeferredDetails title="Training alpha search">
      {() => <Table rows={alphaGrid.map((sse, index) => ({ alpha: (index + 1) / 20, "Training SSE": sse }))} />}
    </DeferredDetails>}
    {Array.isArray(value.innovation_lag_correlations) && <DeferredDetails title="Innovation diagnostics">
      {() => <>
        <p>Pairwise lag correlations of standardized one-step forecast errors on the original time grid.</p>
        <Value value={value.innovation_lag_correlations} depth={0} />
      </>}
    </DeferredDetails>}
    {series && isRecord(series) && numberArray(equity) && <section>
      <h4>Simulated portfolio</h4>
      {portfolioPoints.length > 0 && <ResearchCurve title="Portfolio equity" xLabel="Holding period order"
        yLabel="Equity (input units)" points={portfolioPoints} formatValue={chartNumber} />}
      {series.truncated && <p className="op-result__more">
        {rows.length} of {formatScalar(series.total_rows)} periods displayed. Metrics use all periods.
      </p>}
      <Table rows={rows.map(row => ({
        end_time: row.end_time, ending_equity: row.ending_equity,
        fees: row.fees, net_return: row.net_return, drawdown: row.drawdown,
      }))} />
    </section>}
    {isRecord(value.strategy_series) && isRecord(value.benchmark_series) && isRecord(value.decisions)
      && <WalkForwardDetail strategy={value.strategy_series} benchmark={value.benchmark_series} decisions={value.decisions} />}
    {numberArray(risk) && <section>
      <h4>Rolling volatility</h4>
      {riskPoints.length > 0 && <ResearchCurve title="Highest asset volatility in each displayed window" xLabel="Observation order"
        yLabel="Volatility (input return units)" points={riskPoints} formatValue={chartNumber} />}
      {series && isRecord(series) && series.truncated && <p className="op-result__more">
        {rows.length} of {formatScalar(series.total_rows)} windows displayed. Metrics use all complete windows.
      </p>}
      <Table rows={rows.map((row, index) => ({ time: row.time, maximum_volatility: risk[index] }))} />
    </section>}
    {latest_covariance && isRecord(latest_covariance) && <DeferredDetails title="Latest covariance matrix">
      {() => <CovarianceTable value={latest_covariance} />}
    </DeferredDetails>}
    {isRecord(value.innovation_covariance) && <DeferredDetails title="Innovation covariance">
      {() => <CovarianceTable value={value.innovation_covariance as Record<string, Json>} columnLabel="Series" />}
    </DeferredDetails>}
    {isRecord(value.coefficient_table) && <DeferredDetails title="Lag coefficients by equation">
      {() => <Value value={value.coefficient_table} depth={0} />}
    </DeferredDetails>}
    {isRecord(value.moving_average_matrix) && <DeferredDetails title="Fixed moving-average matrix">
      {() => <CovarianceTable value={value.moving_average_matrix as Record<string, Json>} columnLabel="Series" />}
    </DeferredDetails>}
    {isRecord(value.short_run_coefficients) && <DeferredDetails title="Error-correction coefficients">
      {() => <Value value={{ cointegrating_relation: value.cointegrating_relation,
        loading_coefficients: value.loading_coefficients, short_run_coefficients: value.short_run_coefficients }} depth={0} />}
    </DeferredDetails>}
    {isRecord(value.impulse_responses) && <DeferredDetails title="Reduced-form innovation responses">
      {() => <>
        <p>Responses are to a unit innovation in one series. Other innovations are held fixed.</p>
        <Value value={value.impulse_responses} depth={0} />
      </>}
    </DeferredDetails>}
    {isRecord(value.sample_covariance) && <DeferredDetails title="Sample covariance">
      {() => <CovarianceTable value={value.sample_covariance as Record<string, Json>} />}
    </DeferredDetails>}
    {isRecord(value.objective_covariance) && <DeferredDetails title="Objective covariance">
      {() => <CovarianceTable value={value.objective_covariance as Record<string, Json>} />}
    </DeferredDetails>}
    {isRecord(value.cutoff) && <Value value={value.cutoff} depth={0} />}
    {isRecord(value.fee_comparison) && <FeeComparisonDetail value={value.fee_comparison} />}
    {isRecord(value.sample) && <section>
      <h4>Fitted sample</h4>
      <Value value={value.sample} depth={0} />
    </section>}
    {isRecord(value.tail_window) && <section>
      <h4>Completed replay window</h4>
      <Value value={{ first_period: value.tail_window.first_period, as_of_period: value.tail_window.as_of_period,
        first_end_time: value.tail_window.first_end_time, as_of_end_time: value.tail_window.as_of_end_time }} depth={0} />
    </section>}
    {isRecord(prediction_basis) && Array.isArray(prediction_basis.nodes) && Array.isArray(prediction_basis.predictor_order)
      ? <DeferredDetails title={prediction_basis.kind === "regression" ? "Tree splits and leaf means" : "Tree splits and leaf probabilities"}>
          {() => <PredictionTree value={prediction_basis} />}
        </DeferredDetails>
      : isRecord(prediction_basis) && (prediction_basis.kind === "random_forest_regression"
        || prediction_basis.kind === "random_forest_classification")
      ? <DeferredDetails title="Inspect individual trees">
          {() => <ForestDetail value={prediction_basis} />}
        </DeferredDetails>
      : prediction_basis && <DeferredDetails title="Reproduce predictions">
      {() => <Value value={{ split_times: split_times ?? null, prediction_basis }} depth={0} />}
    </DeferredDetails>}
  </div>;
}

function PredictionTree({ value }: { value: Record<string, Json> }) {
  const { nodes, predictor_order } = value;
  if (!Array.isArray(nodes) || !Array.isArray(predictor_order)) return null;
  return <Table rows={nodes.filter(isRecord).map(node => {
    const feature = typeof node.feature_index === "number" && node.feature_index >= 0 ? predictor_order[node.feature_index] : null;
    return {
      node: node.node_id,
      split: feature == null ? "Leaf" : `${formatScalar(feature)} ≤ ${String(node.threshold)}`,
      left_child: feature == null ? null : node.left_id,
      right_child: feature == null ? null : node.right_id,
      training_rows: node.training_rows,
      ...(value.kind === "regression"
        ? { training_mean: node.training_mean, "Training MSE": node.training_mse,
            "MSE reduction": feature == null ? null : node.mse_gain }
        : { smoothed_probability: node.probability }),
    };
  })} />;
}

function ForestDetail({ value }: { value: Record<string, Json> }) {
  const [selected, setSelected] = useState(0);
  const trees = Array.isArray(value.trees) ? value.trees.filter(isRecord) : [];
  if (!trees.length) return null;
  const index = Math.min(selected, trees.length - 1);
  return <>
    <label>Saved tree
      <select aria-label="Saved tree" value={index} onChange={event => setSelected(Number(event.target.value))}>
        {trees.map((_, position) => <option key={position} value={position}>Tree {position + 1}</option>)}
      </select>
    </label>
    <PredictionTree value={{ kind: value.kind === "random_forest_regression" ? "regression" : "classification",
      predictor_order: value.predictor_order, nodes: trees[index].nodes }} />
  </>;
}

function FeeComparisonDetail({ value }: { value: Record<string, Json> }) {
  const { base, higher } = value;
  if (!isRecord(base) || !isRecord(higher) || !Array.isArray(base.rows) || !Array.isArray(higher.rows)) return null;
  const rows = base.rows.filter(isRecord);
  const comparison = higher.rows.filter(isRecord);
  const baseEquity = rows.map(row => row.ending_equity);
  const higherEquity = comparison.map(row => row.ending_equity);
  if (rows.length !== comparison.length || !numberArray(baseEquity) || !numberArray(higherEquity)
      || rows.some((row, index) => row.end_time !== comparison[index].end_time || row.row !== comparison[index].row)) return null;
  const points = rows.map((row, index) => ({
    position: typeof row.row === "number" ? row.row + 1 : index + 1,
    time: chartTime(row.end_time), value: baseEquity[index],
    details: [["Base fee paid", formatScalar(row.fees)], ["Higher fee paid", formatScalar(comparison[index].fees)]] as const,
  }));
  return <section>
    <h4>Simulated equity by fee</h4>
    <ResearchCurve title="Fee comparison equity" xLabel="Holding period" yLabel="Equity (input units)"
      points={points} formatValue={chartNumber}
      comparison={{ primary: "Base fee", label: "Higher fee", values: higherEquity }} />
  </section>;
}

function WalkForwardDetail({ strategy, benchmark, decisions }: {
  strategy: Record<string, Json>; benchmark: Record<string, Json>; decisions: Record<string, Json>;
}) {
  if (!Array.isArray(strategy.rows) || !Array.isArray(benchmark.rows) || !Array.isArray(decisions.rows)) return null;
  const rows = strategy.rows.filter(isRecord);
  const equal = benchmark.rows.filter(isRecord);
  const dates = decisions.rows.filter(isRecord);
  const equity = rows.map((row) => row.ending_equity);
  const benchmarkEquity = equal.map((row) => row.ending_equity);
  if (rows.length !== equal.length || rows.length !== dates.length || !numberArray(equity) || !numberArray(benchmarkEquity)
      || rows.some((row, index) => row.end_time !== equal[index].end_time || row.end_time !== dates[index].end_time)) return null;
  const points = rows.map((row, index) => ({
    position: index, time: chartTime(row.end_time), value: equity[index],
    details: [
      ["Training cutoff", chartTime(dates[index].as_of_time)],
      ["Execution", chartTime(dates[index].execution_time)],
      ["Minimum-variance fees", formatScalar(row.fees)],
      ["Equal-weight fees", formatScalar(equal[index].fees)],
    ] as const,
  }));
  return <section>
    <h4>Simulated portfolio comparison</h4>
    <ResearchCurve title="Walk-forward equity" xLabel="Evaluation period" yLabel="Equity (input units)"
      points={points} formatValue={chartNumber}
      comparison={{ primary: "Minimum variance", label: "Equal weights", values: benchmarkEquity }} />
    <DeferredDetails title="Saved allocation decisions">
      {() => <Value value={{ equal_weight_target: decisions.benchmark_target, decisions: dates }} depth={0} />}
    </DeferredDetails>
  </section>;
}

function CovarianceTable({ value, columnLabel = "Asset" }: { value: { [key: string]: Json }; columnLabel?: string }) {
  const { columns, matrix } = value;
  if (!Array.isArray(columns) || !Array.isArray(matrix)) return null;
  return <div className="op-result__table">
    <table>
      <thead><tr><th scope="col">{columnLabel}</th>{columns.map((name, i) => <th key={i} scope="col">{formatScalar(name)}</th>)}</tr></thead>
      <tbody>{matrix.map((row, i) => Array.isArray(row) && <tr key={i}>
        <th scope="row">{formatScalar(columns[i])}</th>
        {row.map((cell, j) => <td key={j} data-numeric>{formatScalar(cell)}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function researchSummary(result: { [key: string]: Json }): Json | null {
  const { operation_id, metrics, mean_baseline, fit, forecast, holdout, split, policy } = result;
  if (typeof operation_id !== "string") return null;
  if (operation_id === "time_series.correlogram" && isRecord(metrics)) {
    return { observations: result.n_observations, ...metrics };
  }
  if (operation_id === "time_series.stationarity_statistic" && isRecord(policy)) {
    const adf = result.method === "adf";
    return {
      diagnostic: adf ? "ADF (constant)" : "KPSS (level)",
      null_hypothesis: adf ? "Unit root" : "Level stationarity",
      statistic: result.statistic,
      [adf ? "lagged_differences" : "bartlett_truncation_lag"]: policy.lag,
      effective_observations: result.n_effective,
      evidence_scope: "Statistic only",
      ...(isRecord(result.adf_regression) ? result.adf_regression : {}),
    };
  }
  if (["time_series.native_arima", "time_series.arima_residual_check", "time_series.native_sarima",
       "time_series.native_arimax", "time_series.native_sarimax"].includes(operation_id)
      && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      order: policy.order,
      ...(policy.seasonal_order ? { seasonal_order: policy.seasonal_order } : {}),
      observed_periods: fit.n_observed,
      effective_observations: fit.n_effective,
      forecast_periods: forecast.steps,
      AIC: fit.aic,
      BIC: fit.bic,
      ...(isRecord(fit.diagnostics) && isRecord(fit.diagnostics.whiteness)
        ? { "Ljung–Box residual check": fit.diagnostics.whiteness } : {}),
      ...(policy.future_regressors ? { predictor_scenario: "Forecast uses the supplied future values on the selected time grid." } : {}),
      interval_basis: "Gaussian prediction intervals condition on the fit and exclude parameter uncertainty.",
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id === "time_series.native_var" && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      lag_order: policy.lag_order,
      fitted_periods: fit.n_effective,
      forecast_periods: forecast.steps,
      stability: fit.stability === "sufficient_contraction" ? "Certified by contraction bound" : "Undetermined by contraction bound",
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
      granger: isRecord(result.diagnostics) ? result.diagnostics.granger ?? null : null,
    };
  }
  if (operation_id === "time_series.native_vecm" && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      fixed_cointegration_rank: fit.rank, lagged_differences: policy.difference_lags,
      normalized_series: fit.normalized_series, fitted_periods: fit.n_effective, forecast_periods: forecast.steps,
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id === "time_series.johansen_rank" && isRecord(policy)) {
    const { ranks, canonical_eigenvalues, trace_statistics, max_eigenvalue_statistics } = result;
    if (!numberArray(ranks) || !numberArray(canonical_eigenvalues) || !numberArray(trace_statistics)
        || !numberArray(max_eigenvalue_statistics)
        || [canonical_eigenvalues, trace_statistics, max_eigenvalue_statistics].some(values => values.length !== ranks.length)) {
      return null;
    }
    return {
      level_series: policy.series_columns, lagged_differences: policy.difference_lags, fitted_periods: result.n_effective,
      deterministic_term: "Constant restricted to the cointegrating space",
      rank_hypotheses: ranks.map((rank, index) => ({
        rank, canonical_eigenvalue: canonical_eigenvalues[index], trace_statistic: trace_statistics[index],
        "Maximum-eigenvalue statistic": max_eigenvalue_statistics[index],
      })),
      interpretation: "The trace statistic tests rank at most r; the maximum-eigenvalue statistic compares rank r with r + 1. Critical values and rank selection are outside this result.",
    };
  }
  if (operation_id === "time_series.varma11_fixed_ma" && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      fixed_diagonal_ma: policy.ma_coefficient, fitted_periods: fit.n_effective, forecast_periods: forecast.steps,
      conditional_log_likelihood: fit.conditional_log_likelihood,
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id === "time_series.native_arfima" && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      fractional_difference: policy.fractional_difference, difference_mode: policy.difference_mode,
      observed_periods: fit.n_observed, marginal_variance: fit.marginal_variance,
      forecast_periods: forecast.steps, holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id === "time_series.markov_switching" && isRecord(fit) && isRecord(forecast)) {
    return {
      lower_regime_mean: fit.mean_low, higher_regime_mean: fit.mean_high,
      stay_probability_low: fit.p_low_low, stay_probability_high: fit.p_high_high,
      shared_innovation_variance: fit.shared_variance,
      forecast_periods: forecast.steps,
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (["time_series.holt_winters_additive", "time_series.holt_winters_fit_alpha"].includes(operation_id)
      && isRecord(fit) && isRecord(forecast) && isRecord(policy)
      && isRecord(result.estimation) && isRecord(result.parameters)) {
    const { alpha, beta, gamma } = result.parameters;
    const estimated = result.estimation.method === "training_prefix_alpha_grid";
    return {
      season_period: policy.season_period,
      ...(estimated ? { selected_alpha: alpha, training_periods: result.estimation.training_steps,
        training_SSE: result.estimation.training_sse } : { alpha }),
      beta, gamma,
      observed_periods: fit.n_observed,
      forecast_periods: forecast.steps,
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (["time_series.ets_trend", "time_series.ets_trend_estimate"].includes(operation_id)
      && isRecord(fit) && isRecord(forecast) && isRecord(result.parameters)) {
    return {
      model: result.model_name, alpha: result.parameters.alpha, beta: result.parameters.beta,
      damping: result.parameters.phi, initial_level: fit.initial_level, initial_slope: fit.initial_slope,
      observed_periods: fit.n_observed, forecast_periods: forecast.steps,
      ...(isRecord(policy) && isRecord(policy.smoothing_modes) ? { smoothing_modes: policy.smoothing_modes } : {}),
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id === "time_series.figarch_fixed" && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      model: "FIGARCH with fixed coefficients", coefficients: result.parameters,
      training_periods: fit.n_observed, forecast_periods: forecast.steps, retained_lags: policy.truncation,
      retained_weight_mass: fit.retained_weight_mass, omitted_weight_mass: fit.omitted_weight_mass,
      long_run_variance: "Undefined for the infinite-lag model",
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (["time_series.native_volatility", "time_series.native_egarch", "time_series.native_igarch"].includes(operation_id)
      && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    return {
      model: policy.family,
      training_periods: fit.n_observed,
      forecast_periods: forecast.steps,
      ...(operation_id === "time_series.native_egarch" && isRecord(result.parameters)
        ? { log_variance_persistence: result.parameters.beta } : { persistence: fit.persistence }),
      ...(operation_id === "time_series.native_igarch" ? { long_run_variance: "Undefined at persistence one" } : {}),
      active_bounds: fit.active_bounds,
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id.startsWith("time_series.local_level") && isRecord(fit) && isRecord(forecast)) {
    return {
      observed_periods: fit.n_observed,
      missing_periods: fit.n_missing,
      forecast_periods: forecast.steps,
      predictive_interval_level: isRecord(policy) ? policy.confidence_level : null,
      interval_basis: operation_id === "time_series.local_level_fit"
        ? "Common scale fitted on the training segment at fixed variance ratios. Intervals are conditional on the fit."
        : "Intervals use the supplied Gaussian variances.",
      holdout_errors: isRecord(holdout) ? holdout.metrics : null,
    };
  }
  if (operation_id === "time_series.holt_winters_fit_joint" && isRecord(result.parameters)
      && isRecord(fit) && isRecord(forecast) && isRecord(policy)) {
    const { alpha, beta, gamma } = result.parameters;
    const errors = isRecord(holdout) && isRecord(holdout.metrics) ? holdout.metrics : null;
    return {
      model: "Jointly fitted additive Holt-Winters",
      "Level smoothing (alpha)": alpha, "Trend smoothing (beta)": beta, "Seasonal smoothing (gamma)": gamma,
      season_length: policy.season_period, observed_periods: fit.n_observed, forecast_periods: forecast.steps,
      predictive_interval_level: typeof policy.confidence_level === "number" ? percent.format(policy.confidence_level) : null,
      holdout_training_periods: isRecord(holdout) ? holdout.training_steps : null,
      holdout_errors: errors ? [
        { forecast: "Joint fit", RMSE: errors.rmse, MAE: errors.mae },
        { forecast: "Seasonal naive", RMSE: errors.naive_rmse, MAE: errors.naive_mae },
      ] : null,
    };
  }
  if (operation_id.startsWith("prediction.native_") && isRecord(metrics) && isRecord(mean_baseline) && isRecord(split)) {
    const selection = operation_id === "prediction.native_ridge_selection" && isRecord(result.selection)
      ? result.selection : null;
    return {
      ...(selection && {
        selected_penalty: selection.selected_alpha, initial_fit_rows: selection.fit_rows,
        validation_rows: selection.validation_rows, refit_rows: selection.refit_rows,
        validation_scores: Array.isArray(selection.candidates) ? selection.candidates.filter(isRecord).map(candidate => ({
          penalty: candidate.alpha, "Validation RMSE": candidate.validation_rmse,
          selected: candidate.alpha === selection.selected_alpha,
        })) : null,
      }),
      training_rows: split.train_rows,
      test_rows: split.test_rows,
      test_errors: [
        { prediction: "Fitted model", ...metrics },
        { prediction: "Training-mean baseline", mse: mean_baseline.mse, rmse: mean_baseline.rmse,
          mae: mean_baseline.mae, r2: mean_baseline.r2 },
      ],
      ...(isRecord(result.model_structure) ? { tree: result.model_structure } : {}),
    };
  }
  if (["prediction.native_logistic", "prediction.native_cart", "prediction.native_random_forest_classification"].includes(operation_id)
      && isRecord(metrics) && isRecord(result.prevalence_baseline) && isRecord(split)) {
    const { probability, ...baseline } = result.prevalence_baseline;
    return {
      training_rows: split.train_rows,
      test_rows: split.test_rows,
      baseline_positive_probability: probability,
      holdout_scores: [
        { prediction: "Fitted model", ...metrics },
        { prediction: "Training-prevalence baseline", ...baseline },
      ],
      ...(isRecord(result.model_structure) ? { tree: result.model_structure } : {}),
      auc_note: result.roc_auc_reason === "single_class_test_outcome" ? "ROC AUC needs both classes in the holdout." : null,
    };
  }
  if (operation_id === "quant.replay_tail_risk" && isRecord(metrics)) {
    return {
      historical_value_at_risk: typeof metrics.value_at_risk === "number" ? percent.format(metrics.value_at_risk) : null,
      historical_expected_shortfall: typeof metrics.expected_shortfall === "number" ? percent.format(metrics.expected_shortfall) : null,
      confidence_level: typeof metrics.confidence_bps === "number" ? percent.format(metrics.confidence_bps / 10_000) : null,
      window_periods: metrics.window,
      tail_observation_equivalent: metrics.tail_observation_equivalent,
      interpretation: "Positive values denote losses per period in the simulated history.",
    };
  }
  if (operation_id === "quant.min_variance" && isRecord(metrics) && isRecord(result.allocation)) {
    return {
      sample_variance_per_period: metrics.sample_variance,
      shrinkage_objective_per_period: metrics.objective_variance,
      allocation: Object.entries(result.allocation).map(([asset, weight]) => ({
        asset, weight: typeof weight === "number" ? percent.format(weight) : null,
      })),
    };
  }
  if (operation_id === "quant.min_variance_walk_forward" && isRecord(metrics)
      && isRecord(metrics.strategy) && isRecord(metrics.benchmark)) {
    const portfolios = [["Minimum variance", metrics.strategy], ["Equal weights", metrics.benchmark]] as const;
    return {
      evaluated_portfolios: portfolios.map(([portfolio, values]) => ({
        portfolio,
        net_return: typeof values.cumulative_net_return === "number" ? `${formatScalar(100 * values.cumulative_net_return)}%` : null,
        max_drawdown: typeof values.max_drawdown === "number" ? `${formatScalar(100 * values.max_drawdown)}%` : null,
        per_period_volatility: typeof values.realized_net_return_volatility === "number"
          ? `${formatScalar(100 * values.realized_net_return_volatility)}%` : null,
        fees: values.total_fees,
      })),
      trading_fee_bps: isRecord(result.inputs) ? result.inputs.transaction_cost_bps : null,
    };
  }
  if (operation_id === "quant.replay_fee_comparison" && isRecord(result.inputs) && isRecord(metrics)
      && isRecord(metrics.base) && isRecord(metrics.higher) && isRecord(metrics.higher_minus_base)) {
    const scenarios = [
      ["Base fee", result.inputs.base_transaction_cost_bps, metrics.base],
      ["Higher fee", result.inputs.higher_transaction_cost_bps, metrics.higher],
    ] as const;
    const gap = metrics.higher_minus_base.cumulative_net_return;
    return {
      fee_scenarios: scenarios.map(([scenario, fee, values]) => ({
        scenario, fee_bps: fee, final_equity: values.final_equity, total_fees: values.total_fees,
        net_return: typeof values.cumulative_net_return === "number" ? percent.format(values.cumulative_net_return) : null,
        max_drawdown: typeof values.max_drawdown === "number" ? percent.format(values.max_drawdown) : null,
      })),
      higher_fee_net_return_difference: typeof gap === "number" ? `${formatScalar(100 * gap)} pp` : null,
      higher_fee_equity_difference: metrics.higher_minus_base.final_equity,
      additional_fees_paid: metrics.higher_minus_base.total_fees,
    };
  }
  if ((operation_id === "quant.replay" || operation_id === "quant.rolling_risk") && isRecord(metrics)) return metrics;
  return null;
}

export function ResultValue({ value }: { value: unknown }) {
  const json = value as Json;
  // A saved result is an envelope: the result, plus where it came from
  // (source, request, fingerprints). The result comes first.
  const envelope = isRecord(json) && isRecord(json.result) ? json : null;
  const local = envelope?.local_detail;
  const result = envelope ? envelope.result : json;
  const headline = isRecord(result) ? researchSummary(result) : null;
  const provenance = envelope ? Object.fromEntries(Object.entries(envelope).filter(([key]) => key !== "result" && key !== "local_detail")) : null;
  return (
    <div className="op-result" aria-label="Analysis result">
      <Value value={headline ?? result} depth={0} />
      {local && isRecord(local) && <LocalDetail value={local} result={result} />}
      {headline && <DeferredDetails title="Method and full results">{() => <Value value={result} depth={0} />}</DeferredDetails>}
      {provenance && Object.keys(provenance).length > 0 && (
        <details className="op-result__raw">
          <summary>Provenance</summary>
          <Value value={provenance} depth={1} />
        </details>
      )}
      <DeferredDetails title="Exact JSON">{() => <pre>{JSON.stringify(value, null, 2)}</pre>}</DeferredDetails>
    </div>
  );
}
