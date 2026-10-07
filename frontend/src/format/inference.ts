/**
 * One line that says how a result's standard errors and tests were computed.
 *
 * Inference engine v2 (v1.8.10) reports robust OLS against t(N - K) and
 * clustered OLS against t(G - 1). A result written before it carries no
 * `inference_version`; if its robust or clustered p-values used the normal
 * distribution, the line says so instead of letting it pass for the new rule.
 */

type Evidence = Record<string, unknown>;

function record(value: unknown): Evidence | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Evidence) : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const STANDARD_ERRORS: Record<string, string> = {
  clustered: "Cluster-robust (CR1)",
  hac: "Newey–West (HAC)",
  robust: "Robust (HC1)",
  unadjusted: "Conventional",
};

/** "Bartlett kernel, lag 4 (Newey–West 1994 rule), ordered by year" */
function hacDetail(evidence: Evidence): string | null {
  const hac = record(evidence.hac);
  const lags = count(hac?.lags);
  if (!hac || lags === null) return null;
  const rule = hac.lag_rule === "specified" ? "specified" : "Newey–West 1994 rule";
  const order = typeof hac.time_order === "string" ? `, ordered by ${hac.time_order}` : "";
  return `Bartlett kernel, lag ${lags} (${rule})${order}`;
}

/** A sampling design replaces the fitted variance and df; its own block says how. */
function describeDesignInference(design: Evidence): string {
  const method = typeof design.variance_method === "string" ? design.variance_method : "linearization";
  // Before v1.8.10 no convention was recorded and R survey's degf - p + 1 was used.
  const convention = design.df_convention === "design" ? "design" : "design_minus_p";
  const df = count(design.inference_degf) ?? count(convention === "design" ? design.degf : design.residual_degf);
  const basis = convention === "design" ? "design df, PSUs minus strata" : "design df minus parameters plus one, R survey";
  return [
    `Standard errors: Design-based (${method})`,
    df !== null ? `Inference: t(${Math.round(df)}), ${basis}` : `Inference: t, ${basis}`,
  ].join(" · ");
}

export function describeInference(result: unknown): string | null {
  const model = record(result);
  const design = record(model?.survey_design);
  if (design) return describeDesignInference(design);
  const evidence = record(model?.covariance_evidence) ?? record(model?.inference_config);
  if (!evidence) return null;
  const covariance = typeof evidence.covariance === "string" ? evidence.covariance : "";
  // A panel or DID fit (it names its entity) with robust errors did not cluster
  // by entity: inconsistent with a fixed number of periods. Since v1.8.11 these
  // fits cluster by entity unless robust is chosen; older results are marked.
  const unclusteredPanel = covariance === "robust" && typeof model?.entity_col === "string" && evidence.cluster_entity !== true;
  if (unclusteredPanel && evidence.inference_version === undefined) {
    return "Standard errors: Heteroskedasticity-robust, not clustered (legacy result; rerun to cluster by entity)";
  }
  const label = unclusteredPanel ? "Heteroskedasticity-robust, not clustered" : STANDARD_ERRORS[covariance];
  const parts = [`Standard errors: ${label ?? (covariance || "unspecified")}`];
  const clusters = count(evidence.cluster_count);
  const clusterVariable = typeof evidence.cluster_variable === "string" && evidence.cluster_variable ? evidence.cluster_variable : null;
  if (covariance === "clustered" && clusters !== null) {
    parts.push(clusterVariable && model?.entity_col !== undefined ? `Clusters: ${clusters} (by ${clusterVariable})` : `Clusters: ${clusters}`);
  }
  const hac = covariance === "hac" ? hacDetail(evidence) : null;
  if (hac) parts.push(hac);
  const df = count(evidence.effective_df);
  const pooledFrom = count(record(model?.multiple_imputation)?.m);
  if (evidence.df_method === "barnard_rubin") {
    parts.push("Inference: t, Barnard–Rubin df per coefficient");
    if (pooledFrom !== null) parts.push(`Pooled from m = ${pooledFrom} imputations (Rubin's rules)`);
  } else if (evidence.inference_distribution === "t") {
    parts.push(df !== null ? `Inference: t(${Math.round(df)})` : "Inference: t");
  } else if (evidence.inference_version === undefined && (covariance === "robust" || covariance === "clustered")) {
    parts.push("Inference: z (legacy asymptotic; rerun for finite-sample t)");
  } else {
    parts.push("Inference: z");
  }
  return parts.join(" · ");
}

/** Why a result shows no standard errors, tests or intervals, if it does not. */
export function describeSuppressedInference(result: unknown): string | null {
  const model = record(result);
  const suppressed = record(model?.inference_suppressed);
  const reason = suppressed?.reason;
  return typeof reason === "string" && reason ? `Inference not shown: ${reason}` : null;
}

/** " units (120 rows)" when n counts units rather than rows, else "". */
export function nobsBasis(result: unknown): string {
  const model = record(result);
  if (model?.nobs_basis !== "units") return "";
  const rows = count(model.n_rows);
  return rows !== null ? ` units (${rows} rows)` : " units";
}
