// v1.9.0 — what the stage's result view shows for a model step, derived from
// the run detail the backend already serves (model_results, the diagnostic
// summary, term labels). Pure functions; the view only lays them out.

import type { RunDetail } from "../../api";
import type { DecisionViewModel, GraphViewNode } from "../../lineage/api/graphViewTypes";
import { describeInference } from "../../format/inference";

type ModelResult = NonNullable<RunDetail["model_results"]>[number];
type Rec = Record<string, unknown>;

const rec = (value: unknown): Rec | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Rec) : null;
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === "string" && value ? value : null);

/** "model:ols_1" → "ols_1"; null for steps that are not models. */
export function modelIdOf(node: Pick<GraphViewNode, "raw" | "id" | "stage" | "kind">): string | null {
  if (node.stage !== "model" && node.kind !== "model") return null;
  const raw = rec(node.raw);
  const id = str(raw?.id) ?? node.id;
  return id.startsWith("model:") ? id.slice("model:".length) : null;
}

export function pickModelResult(detail: RunDetail | null, modelId: string | null): ModelResult | null {
  const results = detail?.model_results ?? [];
  if (results.length === 0) return null;
  const result = results.find((result) => rec(result)?.model_id === modelId) ?? (modelId === null ? results[0] : null);
  const evidence = rec(detail?.model_family_evidence);
  return result && evidence && rec(result)?.source_contract === "linear_mixed_effects.result" &&
    evidence?.model_id === rec(result)?.model_id && rec(evidence.coefficients)
    ? evidence as unknown as ModelResult : result;
}

export interface CoefficientRow {
  term: string;
  label: string;
  estimate: number | null;
  se: number | null;
  ciLow: number | null;
  ciHigh: number | null;
  p: number | null;
  pDisplay: string | null;
  intercept: boolean;
}

const INTERCEPT = /^(intercept|const|\(intercept\)|_cons)$/i;

export function coefficientRows(result: ModelResult | null, termLabels: unknown): CoefficientRow[] {
  const coefficients = rec(rec(result)?.coefficients);
  if (!coefficients) return [];
  const labels = rec(termLabels) ?? {};
  return Object.entries(coefficients).map(([term, value]) => {
    const c = rec(value) ?? {};
    return {
      term,
      label: str(labels[term]) ?? str(c.label) ?? term,
      estimate: num(c.estimate),
      se: num(c.std_error),
      ciLow: num(c.ci_lower),
      ciHigh: num(c.ci_upper),
      p: num(c.p_value),
      pDisplay: str(c.p_value_display),
      intercept: INTERCEPT.test(term),
    };
  });
}

/** The number the result leads with: the declared estimand, else the first slope. */
export function keyCoefficient(rows: CoefficientRow[], result: ModelResult | null): CoefficientRow | null {
  const estimand = rec(rec(result)?.primary_estimand);
  const named = str(estimand?.term) ?? str(estimand?.coefficient) ?? null;
  return rows.find((row) => row.term === named) ?? rows.find((row) => !row.intercept) ?? rows[0] ?? null;
}

export interface FitStat {
  label: string;
  value: number;
}

export function fitStats(result: ModelResult | null): FitStat[] {
  const r = rec(result) ?? {};
  const stats: Array<[string, unknown]> = [
    ["n", r.nobs],
    ["R²", r.r_squared],
    ["Adjusted R²", r.r_squared_adj],
    ["Pseudo R²", r.pseudo_r2],
    ["AIC", r.aic],
    ["BIC", r.bic],
  ];
  return stats.flatMap(([label, value]) => (num(value) === null ? [] : [{ label, value: num(value)! }]));
}

export function inferenceLine(result: ModelResult | null): string | null {
  return result ? describeInference(result) : null;
}

export type CheckStatus = "holds" | "caution" | "fails";

export interface CheckSummary {
  status: CheckStatus;
  label: string;
  reasons: string[];
}

export function checkSummary(detail: RunDetail | null): CheckSummary | null {
  const preview = rec(detail?.diagnostic_summary_preview);
  if (!preview || preview.available === false) return null;
  const counts = rec(preview.trust_counts) ?? {};
  const reasons = (Array.isArray(preview.primary_reasons) ? preview.primary_reasons : [])
    .map((reason) => str(rec(reason)?.message))
    .filter((message): message is string => message !== null);
  const blockers = num(counts.blockers) ?? 0;
  const warnings = (num(counts.warnings) ?? 0) + (num(counts.cautions) ?? 0);
  if (blockers > 0) return { status: "fails", label: `${blockers} blocking issue${blockers === 1 ? "" : "s"}`, reasons };
  if (warnings > 0) return { status: "caution", label: `${warnings} to look at`, reasons };
  return { status: "holds", label: "Ready to interpret", reasons };
}

/** Choices the analysis made for the user that still wait for a decision. */
export function pendingChoices(decisions: DecisionViewModel[]): string[] {
  return decisions.filter((d) => d.reviewStatus === "needed").map((d) => d.question);
}
