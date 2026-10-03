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
  robust: "Robust (HC1)",
  unadjusted: "Conventional",
};

export function describeInference(result: unknown): string | null {
  const model = record(result);
  const evidence = record(model?.covariance_evidence) ?? record(model?.inference_config);
  if (!evidence) return null;
  const covariance = typeof evidence.covariance === "string" ? evidence.covariance : "";
  const parts = [`Standard errors: ${STANDARD_ERRORS[covariance] ?? (covariance || "unspecified")}`];
  const clusters = count(evidence.cluster_count);
  if (covariance === "clustered" && clusters !== null) parts.push(`Clusters: ${clusters}`);
  const df = count(evidence.effective_df);
  if (evidence.inference_distribution === "t") {
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
