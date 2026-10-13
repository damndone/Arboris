import type { ReactNode } from "react";
import type { Draft } from "./manualApi";
import { formatEstimate, formatPValue } from "../format/numbers";

type Fact = Draft["facts"][number];
const labels: Record<string, string> = { p_value: "p-value", std_error: "Standard error", ci_lower: "Confidence interval lower bound", ci_upper: "Confidence interval upper bound", nobs: "Observations", n_observations: "Observations", r_squared: "R²", adjusted_r_squared: "Adjusted R²", estimate: "Estimate" };
export function factLabel(fact: Fact): string {
  return fact.label.split(" · ").map(part => labels[part] ?? part.replace(/_/g, " ")).join(" · ");
}
export function factValue(fact: Fact): string {
  if (fact.value === null) return "Not reported";
  if (typeof fact.value === "boolean") return fact.value ? "Yes" : "No";
  if (typeof fact.value !== "number") return fact.value;
  return /(?:^|[/ .])p_value$/.test(fact.field) ? formatPValue(fact.value) : formatEstimate(fact.value);
}
/** Display only: source values, identities and saved prose remain untouched. */
export function ReportReadingView({ text, facts }: { text: string; facts: Fact[] }) {
  const byId = new Map(facts.map(f => [f.id, f]));
  const technical: ReactNode[] = [];
  const lines = text.split("\n").map((line, index) => {
    const match = line.match(/^- .* \[\[c:([^\]]+)\]\]$/);
    const fact = match ? byId.get(match[1]) : undefined;
    // Python and JavaScript spell floats differently (0.0/0, 1e-08/1e-8).
    // Require the exact registered label and citation, and an equal scalar.
    const prefix = fact ? `- ${fact.label}: ` : "";
    const suffix = fact ? ` [[c:${fact.id}]]` : "";
    const scalar = fact && line.startsWith(prefix) && line.endsWith(suffix) ? line.slice(prefix.length, -suffix.length) : null;
    const matches = fact && scalar !== null && (typeof fact.value === "number"
      ? /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(scalar) && Number(scalar) === fact.value
      : scalar === (fact.value === null ? "None" : typeof fact.value === "boolean" ? (fact.value ? "True" : "False") : fact.value));
    if (fact && matches) {
      const item = <details key={index} className="manual-reading__fact"><summary>{factLabel(fact)}: <strong>{factValue(fact)}</strong></summary><small>Original line: {line}<br/>Exact value: {String(fact.value)} · Field: {fact.field} · Evidence: {fact.id} · Run: {fact.source.run_id}</small></details>;
      const technicalField = /^(?:param|decision)\//.test(fact.field) || /\/(?:id|model_id|model_run_id|model_type|artifact_id|result_id|source_id|execution_key|contract|contract_version|reason_code|operation_id)$/.test(fact.field) || /\/retained_positions\//.test(fact.field);
      if (technicalField) { technical.push(item); return null; }
      return item;
    }
    if (line.startsWith("# ")) return <h3 key={index}>{line.slice(2)}</h3>;
    return <p key={index}>{line || "\u00a0"}</p>;
  });
  return <section aria-label="Report reading view" className="manual-reading">{lines}{technical.length > 0 && <details><summary>Methods and technical evidence ({technical.length})</summary>{technical}</details>}</section>;
}
