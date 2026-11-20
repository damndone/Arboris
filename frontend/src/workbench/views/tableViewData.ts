import type { RunDetail } from "../../api";
import { DEFAULT_SIGNIFICANCE_LEVELS } from "../../report/RegressionTable";
import type { SignificanceLevels } from "../../report/RegressionTable";
import { formatEstimate } from "../../format/numbers";

export function shortRunId(id: string): string {
  const tail = id.split("_").pop() ?? id;
  return tail.slice(0, 8);
}

export const fmt = formatEstimate;

export type ByGroup = { column?: string; key?: string; n_groups?: number; not_estimable?: { key?: string; nobs?: number; reason?: string }[] };

export function byGroup(model: object): ByGroup | null {
  const block = (model as { by_group?: unknown }).by_group;
  return block !== null && typeof block === "object" ? (block as ByGroup) : null;
}

/** "region = east" for one group's result of a by-group run. */
export function groupLabel(model: object): string | null {
  const block = byGroup(model);
  return block?.column ? `${block.column} = ${block.key ?? ""}` : null;
}

/** Groups listed as not estimable, with their reasons; shown once, on the first group. */
export function notEstimableGroups(model: object): string | null {
  const block = byGroup(model);
  const skipped = block?.not_estimable ?? [];
  if (!block || skipped.length === 0 || (model as { by_group?: { index?: number } }).by_group?.index !== 1) return null;
  return skipped.map((item) => `Not estimated: ${block.column} = ${item.key} (${item.nobs} rows): ${item.reason}`).join(" ");
}

export function pooledDf(coefficient: object): string {
  const df = (coefficient as { df?: number | null }).df;
  return typeof df === "number" ? df.toFixed(1) : "∞";
}

export function confidenceIntervalText(coefficient: {
  ci_lower?: number | null;
  ci_upper?: number | null;
  confidence_interval?: readonly [number, number] | null;
}): string {
  const lower = typeof coefficient.ci_lower === "number" ? coefficient.ci_lower : coefficient.confidence_interval?.[0];
  const upper = typeof coefficient.ci_upper === "number" ? coefficient.ci_upper : coefficient.confidence_interval?.[1];
  if (typeof lower !== "number" || typeof upper !== "number") return "—";
  return `[${fmt(lower)}, ${fmt(upper)}]`;
}

/** "correlation_heatmap" → "Correlation heatmap" for captions/alt text. */
export function humanize(id: string): string {
  const s = id.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Reader-facing names for the declared post-estimation operations.
 *
 * An unknown operation still renders — it falls back to its id — because a
 * missing label is a cosmetic gap, while hiding a computed result would put
 * us back where this section started: evidence nobody sees. */
export const POST_ESTIMATION_LABELS: Record<string, string> = {
  "model.quadratic_stationary_point": "Quadratic stationary point",
  "model.joint_f_test": "Joint F test",
  "model.white_test": "White test",
};

/** Keys that identify the payload format rather than tell the reader anything. */

/**
 * The current GET /runs/{id} response only exposes model_results. Keep the
 * optional report-facing fields local until that API has a durable contract;
 * their absence is rendered explicitly below instead of being treated as
 * empty evidence.
 */
export type TableViewRunDetailExtensions = {
  significance_levels?: SignificanceLevels;
  variable_labels?: Readonly<Record<string, string>>;
  labels?: { variable_labels?: Readonly<Record<string, string>> };
  table_1?: unknown;
  statistical_evidence?: unknown;
};

export const EMPTY_VARIABLE_LABELS: Readonly<Record<string, string>> = {};
export const STAR_MARKERS = ["***", "**", "*"] as const;

export type TableOneRow = {
  column: string;
  label: string;
  count?: number | null;
  missing?: number | null;
  mean?: number | null;
  std?: number | null;
  value_labels?: Record<string, string>;
};

export type StatisticalEvidenceResult = {
  test_id?: string;
  test_type?: string;
  nobs?: number;
  statistic?: number | null;
  p_value?: number | null;
  effect_size?: unknown;
  source_id?: string;
};

export type StatisticalEvidencePacket = {
  payload_schema: "workbench.statistics.evidence-packet";
  schema_version: 1;
  results: StatisticalEvidenceResult[];
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function normalizeSignificanceLevels(value: unknown): SignificanceLevels {
  const normalized: SignificanceLevels = { ...DEFAULT_SIGNIFICANCE_LEVELS };
  if (!isRecord(value)) return normalized;
  for (const marker of STAR_MARKERS) {
    const cutoff = finiteNumber(value[marker]);
    if (cutoff !== null && cutoff >= 0 && cutoff <= 1) normalized[marker] = cutoff;
  }
  return normalized;
}

export function normalizeVariableLabels(value: unknown): Readonly<Record<string, string>> {
  if (!isRecord(value)) return EMPTY_VARIABLE_LABELS;
  const labels: Record<string, string> = {};
  for (const [column, label] of Object.entries(value)) {
    if (column.trim() && typeof label === "string" && label.trim()) labels[column] = label;
  }
  return labels;
}

export function normalizeTableOne(value: unknown): TableOneRow[] {
  const rows = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.rows)
      ? value.rows
      : [];
  return rows.flatMap((candidate) => {
    if (!isRecord(candidate)) return [];
    const column = typeof candidate.column === "string"
      ? candidate.column
      : typeof candidate.variable === "string"
        ? candidate.variable
        : "";
    if (!column) return [];
    const label = typeof candidate.label === "string" ? candidate.label : column;
    const valueLabels = isRecord(candidate.value_labels)
      ? Object.fromEntries(
        Object.entries(candidate.value_labels)
          .filter(([, item]) => typeof item === "string")
          .map(([key, item]) => [key, item as string]),
      )
      : undefined;
    return [{
      column,
      label,
      count: finiteNumber(candidate.count),
      missing: finiteNumber(candidate.missing),
      mean: finiteNumber(candidate.mean),
      std: finiteNumber(candidate.std),
      value_labels: valueLabels,
    }];
  });
}

export function normalizeStatisticalEvidence(value: unknown): StatisticalEvidencePacket | null {
  const candidate = isRecord(value) && isRecord(value.payload) && !Array.isArray(value.results)
    ? value.payload
    : value;
  if (
    !isRecord(candidate)
    || candidate.payload_schema !== "workbench.statistics.evidence-packet"
    || candidate.schema_version !== 1
    || !Array.isArray(candidate.results)
  ) {
    return null;
  }
  return {
    payload_schema: "workbench.statistics.evidence-packet",
    schema_version: 1,
    results: candidate.results.filter(isRecord).map((result) => ({
      test_id: typeof result.test_id === "string" ? result.test_id : undefined,
      test_type: typeof result.test_type === "string" ? result.test_type : undefined,
      nobs: finiteNumber(result.nobs) ?? undefined,
      statistic: finiteNumber(result.statistic),
      p_value: finiteNumber(result.p_value),
      effect_size: result.effect_size,
      source_id: typeof result.source_id === "string" ? result.source_id : undefined,
    })),
  };
}

export function evidenceTestLabel(testType: string | undefined): string {
  return ({
    anova_posthoc: "ANOVA post-hoc",
    bartlett: "Bartlett test",
    cohens_d: "Cohen's d",
    eta_squared: "Eta squared",
    levene: "Levene test",
    omega_squared: "Omega squared",
    paired_t_test: "Paired t test",
    shapiro_wilk: "Shapiro-Wilk test",
    wilcoxon_signed_rank: "Wilcoxon signed-rank test",
  } as Record<string, string>)[testType ?? ""] ?? humanize(testType ?? "statistical test");
}

export function evidenceEffectValue(effectSize: unknown): string {
  if (finiteNumber(effectSize) !== null) return fmt(effectSize as number);
  if (isRecord(effectSize)) {
    const value = finiteNumber(effectSize.value);
    if (value !== null) return fmt(value);
  }
  return "—";
}

export function tableViewExtensions(detail: RunDetail | null): TableViewRunDetailExtensions {
  return (detail ?? {}) as RunDetail & TableViewRunDetailExtensions;
}

export function variableLabelsForTable(detail: RunDetail | null): Readonly<Record<string, string>> {
  const extensions = tableViewExtensions(detail);
  const variableLabels = extensions.variable_labels
    ?? extensions.labels?.variable_labels
    ?? EMPTY_VARIABLE_LABELS;
  const termLabels = detail?.term_labels;
  // The server renders coefficient terms (dummies, polynomials, interactions)
  // with the declared labels; a plain variable label is the fallback.
  return termLabels && Object.keys(termLabels).length > 0
    ? { ...variableLabels, ...termLabels }
    : variableLabels;
}
