// frontend/src/lineage/detail/sections/EstimatedEquationSection.tsx
//
// v1.6.8 — the FITTED equation for a model node, built from the owner run's
// model_results coefficients. RoleGroupsSection below it shows the
// *specification* (`y ~ x1 + x2`); this section shows the *estimate*:
//
//   wage = 1.517 + 1.857·x1 − 0.845·x2 …        (OLS family)
//   logit(P(y=1)) = …                            (logit / binomial)
//   log(E[y]) = …                                (poisson / negbin)
//
// Honesty rules:
//   - Only renders when the owner run's model_results contain a coefficient
//     table for THIS node's model id. CS/SA/dCDH publish effect bundles
//     (att_gt / aggregations), not a single-equation table — they render
//     nothing here; the Table view owns those results.
//   - `_did_D` (TWFE DID) is displayed as `D (ATT)`; entity/time fixed
//     effects are absorbed and noted in the meta line, never faked as terms.
//   - Every term carries se / p in its tooltip, so the equation line is a
//     summary, not a replacement for the coefficient table.

import { useEffect, useState } from "react";
import { useLineage } from "../../LineageContext";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import { fetchRunDetail, type ModelResult, type CoefficientRecord } from "../../../api";
import type { GraphViewNode, HeadSetNode } from "../../api/graphViewTypes";

const INTERCEPT_TERMS = new Set(["intercept", "(intercept)", "const", "constant", "1"]);

function fmt(n: number): string {
  return String(Number(n.toPrecision(4)));
}

/** "_did_D" is the TWFE DID treatment dummy whose coefficient IS the ATT. */
function displayTerm(term: string): string {
  return term === "_did_D" ? "D (ATT)" : term;
}

function termTooltip(term: string, c: CoefficientRecord): string {
  const parts = [`${displayTerm(term)}: ${c.estimate != null ? fmt(c.estimate) : "—"}`];
  if (c.std_error != null) parts.push(`se ${fmt(c.std_error)}`);
  const p = c.p_value_display ?? (c.p_value != null ? fmt(c.p_value) : null);
  if (p != null) parts.push(`p ${p}`);
  return parts.join(" · ");
}

/** Left-hand side by estimator family (link functions must not be silently
 *  dropped — a logit equation is NOT `y = …`). */
export function equationLhs(modelType: string | undefined, y: string): string {
  const t = (modelType ?? "").toLowerCase();
  if (t.includes("logit") || t.includes("binomial")) return `logit(P(${y}=1))`;
  if (t.includes("probit")) return `probit(P(${y}=1))`;
  if (t.includes("poisson") || t.includes("negbin")) return `log(E[${y}])`;
  return y;
}

export interface EquationTerm {
  term: string;
  label: string;
  coef: number;
  tooltip: string;
}

export interface EstimatedEquation {
  lhs: string;
  intercept: EquationTerm | null;
  terms: EquationTerm[];
  /** meta line: estimator label, n, fit stat, FE note. */
  meta: string;
}

/** Pure builder so the equation semantics are unit-testable without the
 *  fetch/context plumbing. Returns null when there is nothing honest to
 *  render (no finite coefficient estimates). */
export function buildEstimatedEquation(
  result: ModelResult,
  y: string,
): EstimatedEquation | null {
  const entries = Object.entries(result.coefficients ?? {}).filter(
    ([, c]) => typeof c.estimate === "number" && Number.isFinite(c.estimate),
  );
  if (entries.length === 0) return null;
  const toTerm = ([term, c]: [string, CoefficientRecord]): EquationTerm => ({
    term,
    label: displayTerm(term),
    coef: c.estimate as number,
    tooltip: termTooltip(term, c),
  });
  const intercept =
    entries.filter(([t]) => INTERCEPT_TERMS.has(t.toLowerCase())).map(toTerm)[0] ?? null;
  const terms = entries
    .filter(([t]) => !INTERCEPT_TERMS.has(t.toLowerCase()))
    .map(toTerm);
  if (!intercept && terms.length === 0) return null;

  const modelType = (result.model_type ?? "").toLowerCase();
  const isPanelFamily =
    modelType.includes("panel") || modelType === "did" || modelType.includes("twfe");
  const metaParts: string[] = [];
  if (result.model_type) metaParts.push(result.model_type);
  if (result.nobs !== undefined) metaParts.push(`n=${result.nobs}`);
  if (result.r_squared != null) metaParts.push(`R²=${fmt(result.r_squared)}`);
  else if (result.pseudo_r2 != null) metaParts.push(`pseudo-R²=${fmt(result.pseudo_r2)}`);
  if (isPanelFamily) metaParts.push("entity/time fixed effects absorbed");

  return {
    lhs: equationLhs(result.model_type, y),
    intercept,
    terms,
    meta: metaParts.join(" · "),
  };
}

/** `model:ols_1` (per-run op id / forest opNodeId) → model_results id `ols_1`. */
function modelIdOf(node: GraphViewNode): string {
  const opId = (node as HeadSetNode).opNodeId ?? node.id;
  return opId.startsWith("model:") ? opId.slice("model:".length) : opId;
}

export function EstimatedEquationSection({ node }: { node: GraphViewNode }) {
  const { model } = useLineage();
  const resolvedContext = useResolvedNodeOperationContext();
  const contextProjectRoot = useProjectRootOptional();
  // Same fallback ladder as the rest of the drawer: context (slug routes) →
  // legacy ?project_root= query.
  const projectRoot =
    contextProjectRoot ??
    new URLSearchParams(window.location.search).get("project_root") ??
    "";
  // Owner run: the run a rerun would fork from (forest); legacy per-run
  // graphs fall back to the URL run, which owns every node it shows.
  const ownerRunId = resolvedContext?.ok
    ? resolvedContext.context.ownership.owner_run_id
    : model.runId;
  const modelId = modelIdOf(node);

  const [equation, setEquation] = useState<EstimatedEquation | null>(null);

  useEffect(() => {
    if (!projectRoot || !ownerRunId) return undefined;
    let cancelled = false;
    setEquation(null);
    fetchRunDetail(projectRoot, ownerRunId)
      .then((detail) => {
        if (cancelled) return;
        const match = (detail.model_results ?? []).find(
          (r) => r.model_id === modelId,
        );
        setEquation(match ? buildEstimatedEquation(match, detail.y ?? "y") : null);
      })
      .catch(() => {
        /* no results, no equation — the spec section still renders */
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, ownerRunId, modelId]);

  if (!equation) return null;

  const pieces: React.ReactNode[] = [];
  if (equation.intercept) {
    pieces.push(
      <span key="__intercept" title={equation.intercept.tooltip}>
        {fmt(equation.intercept.coef)}
      </span>,
    );
  }
  equation.terms.forEach((t, i) => {
    const first = pieces.length === 0;
    const sign = t.coef < 0 ? "−" : "+";
    pieces.push(
      <span key={t.term} title={t.tooltip}>
        {first ? (t.coef < 0 ? "−" : "") : ` ${sign} `}
        {fmt(Math.abs(t.coef))}·{t.label}
      </span>,
    );
    void i;
  });

  return (
    <section
      aria-label="Estimated equation"
      data-testid="estimated-equation-section"
      style={{ marginTop: 18 }}
    >
      <div
        className="ln-section-label"
        style={{ marginBottom: 4, fontSize: 11, color: "var(--label-secondary)" }}
      >
        Estimated equation
      </div>
      <div
        data-testid="estimated-equation"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          color: "var(--label)",
          lineHeight: 1.6,
          overflowWrap: "anywhere",
        }}
      >
        {equation.lhs} = {pieces}
      </div>
      {equation.meta && (
        <div style={{ marginTop: 4, fontSize: 11, color: "var(--label-tertiary)" }}>
          {equation.meta} · se/p per term on hover; full table in the Table view
        </div>
      )}
    </section>
  );
}
