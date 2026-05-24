export interface DPDisplay {
  title: string;
  displaySelected: (selected: unknown) => string;
  displayAlternatives: (params: Record<string, unknown>) => string[];
  whyShort: (params: Record<string, unknown>) => string;
  whyLong: (params: Record<string, unknown>) => string;
  confirmPrompt: string;
  evidenceFields?: string[];
}

const MODEL_TYPE_MAP: Record<string, string> = {
  continuous: "OLS",
  binary: "Logit",
  count: "Poisson",
};

export const DP_REGISTRY: Record<string, DPDisplay> = {
  model_type_auto_select: {
    title: "Model type",
    displaySelected: (s) => MODEL_TYPE_MAP[String(s)] ?? String(s),
    displayAlternatives: () => ["OLS", "Logit", "Poisson"],
    whyShort: (p) =>
      `y appears ${p.y_dtype === "object" ? "categorical" : "continuous"}`,
    whyLong: (p) =>
      `y has ${p.y_unique} unique values (dtype ${p.y_dtype}), so the system treated it as ${MODEL_TYPE_MAP[String(p.selected ?? "continuous")]?.toLowerCase() ?? "continuous"}.`,
    confirmPrompt:
      "Confirm that y should be modeled this way; revisit if the outcome is actually categorical or count-based.",
    evidenceFields: ["y_unique", "y_dtype"],
  },
  ols_default_robust_se: {
    title: "Standard errors",
    displaySelected: (s) => String(s),
    displayAlternatives: () => ["non-robust", "clustered", "HC0", "HC2", "HC3"],
    whyShort: () => "System default",
    whyLong: () =>
      "HC1 robust standard errors are applied by default to every OLS regression.",
    confirmPrompt:
      "Confirm HC1 is appropriate; revisit if heteroskedasticity is uncertain or you have grouped errors.",
  },
  categorical_auto_dummy: {
    title: "Categorical encoding",
    displaySelected: () => "Dummy variables",
    displayAlternatives: () => ["Leave as continuous", "Drop variable"],
    whyShort: (p) => `${p.n_unique} unique values, treated as categorical`,
    whyLong: (p) =>
      `Column '${p.variable}' has ${p.n_unique} unique non-null values; dummy-encoded with '${p.reference_level}' as reference level.`,
    confirmPrompt:
      "Confirm this variable is genuinely categorical (not ordinal-as-integer).",
    evidenceFields: ["variable", "n_unique", "reference_level"],
  },
  auto_coerce_to_numeric: {
    title: "Numeric coercion",
    displaySelected: () => "Coerced to numeric",
    displayAlternatives: () => ["Leave as string", "Treat as categorical"],
    whyShort: (p) =>
      `${typeof p.conversion_rate === "number" ? Math.round(p.conversion_rate * 100) : "?"}% convertible`,
    whyLong: (p) =>
      `Column '${p.variable}' was object dtype; the system converted it to numeric (${typeof p.conversion_rate === "number" ? Math.round(p.conversion_rate * 100) : "?"}% of rows convertible).`,
    confirmPrompt:
      "Confirm this column should be numeric (vs. ordinal labels or identifiers).",
    evidenceFields: ["variable", "conversion_rate"],
  },
  handle_missing_values: {
    title: "Missing-value handling",
    displaySelected: () => "Drop rows with any missing",
    displayAlternatives: () => [
      "Mean imputation",
      "Group median imputation",
      "Missing-as-category",
      "Multiple imputation",
    ],
    whyShort: () => "System default",
    whyLong: () =>
      "The pipeline drops rows with any missing y or x value (listwise deletion). Assumes MCAR.",
    confirmPrompt:
      "Confirm listwise deletion is acceptable; consider per-variable strategy for time-series/panel/causal contexts.",
  },
  variable_silently_dropped: {
    title: "Variable dropped",
    displaySelected: () => "Removed from model",
    displayAlternatives: () => [
      "Drop rows instead",
      "Impute",
      "Manual review",
    ],
    whyShort: (p) =>
      String(p.drop_reason ?? "unknown").replace(/_/g, " "),
    whyLong: (p) =>
      `Variable '${p.variable}' was dropped due to ${String(p.drop_reason ?? "unknown").replace(/_/g, " ")}.`,
    confirmPrompt: "Confirm this variable should be excluded from analysis.",
    evidenceFields: ["variable", "drop_reason"],
  },
};

function humanize(id: string): string {
  return id
    .split("_")
    .map((w) => (w[0]?.toUpperCase() ?? "") + w.slice(1))
    .join(" ");
}

export function getDPDisplay(decisionId: string): DPDisplay {
  const entry = DP_REGISTRY[decisionId];
  if (entry) return entry;
  return {
    title: humanize(decisionId),
    displaySelected: (s) => String(s),
    displayAlternatives: () => [],
    whyShort: () => "",
    whyLong: () => "",
    confirmPrompt: "",
  };
}
