import type {ModelResult} from "../api";
import {formatEstimate,formatPValue} from "../format/numbers";

type DispersionResult=Pick<ModelResult,"model_id"|"dispersion"|"alpha_estimated"|"alpha_fixed_value"|
  "ancillary_parameters"|"overdispersion_test"|"information_matrix"|"warnings">;

export function CountModelResultCard({model}:{model:DispersionResult}) {
  if (model.dispersion !== "mean" && model.dispersion !== "constant") return null;
  const estimated=model.alpha_estimated === true;
  const test=model.overdispersion_test;
  return <section className="panel" aria-label="Dispersion inference">
    <h3 className="subhead">{estimated
      ? `Estimated dispersion (${model.dispersion === "constant" ? "NB1" : "NB2"})`
      : "Fixed dispersion"}</h3>
    {estimated ? <table className="coefficients-table">
      <thead><tr><th>Auxiliary parameter</th><th>Estimate</th><th>Std. error</th><th>95% interval</th></tr></thead>
      <tbody>{model.ancillary_parameters?.map(row=><tr key={row.name}>
        <td>{row.name}</td><td>{formatEstimate(row.estimate)}</td><td>{formatEstimate(row.std_error)}</td>
        <td>{formatEstimate(row.conf_low)} — {formatEstimate(row.conf_high)}</td>
      </tr>)}</tbody>
    </table> : <p>Alpha fixed at {formatEstimate(model.alpha_fixed_value)}; not estimated.</p>}
    {estimated && test && <p>Poisson boundary LR: {formatEstimate(test.statistic)}, {test.distribution},
      df = {test.df}, p = {formatPValue(test.p_value)}.</p>}
    {model.warnings?.map((warning,index)=><p role="alert" key={index}>
      {typeof warning === "string" ? warning : `${warning.code}: ${warning.message}`}
    </p>)}
    <p className="ios-hint">Auxiliary dispersion is separate from regression coefficient hypotheses.
      {model.information_matrix && ` Information: ${model.information_matrix}.`}</p>
  </section>;
}
