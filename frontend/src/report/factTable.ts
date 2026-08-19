// v1.6.11 slice C — deterministic citable-fact extraction.
//
// The fact table is the anti-hallucination contract: it is built HERE, from
// the same pure context resolver the drawer uses, and sent to the model as the
// only permitted source of numbers. Chips later render from this local table
// (never from model output), so an invented number can never become a chip.
import type { PostEstimationResult } from "../api";
import type { ForestViewModel } from "../lineage/api/graphViewTypes";
import { resolveNodeOperationContext } from "../lineage/api/nodeOperationContext";
import {
  readReportEvidence,
  type EvidenceViewModel,
} from "./reportEvidence";

export interface CitableFact {
  id: string;
  node_key: string;
  node_label: string;
  /** e.g. "param:covariance", "metric:r_squared", "decision:standard_errors" */
  field: string;
  label: string;
  value: unknown;
  /** Optional provider metadata; old facts remain valid without it. */
  provider_id?: string;
  kind?: "estimate" | "diagnostic" | "sample" | "decision" | "metadata" | string;
  unit?: string | null;
  artifact_ids?: string[];
  claim_types?: string[];
  validation_level?: "external_oracle" | "internal_only" | "unverified" | string;
  qualifiers?: Record<string, unknown>;
}

export interface ReportEvidenceProvenance {
  readonly artifactRef?: string;
  readonly artifactId?: string;
  readonly artifactType?: string;
  readonly commitId?: string;
  readonly envelopeRef?: string;
  readonly lineageRefs?: readonly string[];
  readonly projectionRef?: Record<string, unknown>;
  readonly resultIdentity?: Record<string, unknown>;
  readonly indexed?: boolean;
  readonly admissionStatus?: string;
  readonly projections?: readonly Record<string, unknown>[];
  readonly envelopeDigests?: readonly string[];
}

export type ReportEvidenceProjection = EvidenceViewModel & {
  readonly validationStatus: string;
  readonly validationSummary: Readonly<Record<string, unknown>>;
  readonly commitId?: string;
  readonly reasonCode?: string;
  readonly provenance: ReportEvidenceProvenance;
};

function asEvidenceRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function readEvidenceProvenance(value: unknown): ReportEvidenceProvenance | null {
  const record = asEvidenceRecord(value);
  if (!record) return null;
  const provenance: ReportEvidenceProvenance = {};
  for (const key of [
    "artifactRef",
    "artifactId",
    "artifactType",
    "commitId",
    "envelopeRef",
    "admissionStatus",
  ] as const) {
    if (record[key] !== undefined && typeof record[key] !== "string") return null;
    if (typeof record[key] === "string") {
      (provenance as Record<string, unknown>)[key] = record[key];
    }
  }
  if (record.indexed !== undefined && typeof record.indexed !== "boolean") return null;
  if (record.indexed === true) {
    (provenance as Record<string, unknown>).indexed = true;
  }
  if (record.lineageRefs !== undefined) {
    if (!Array.isArray(record.lineageRefs) || !record.lineageRefs.every((item) => typeof item === "string")) return null;
    (provenance as Record<string, unknown>).lineageRefs = record.lineageRefs;
  }
  if (record.envelopeDigests !== undefined) {
    if (!Array.isArray(record.envelopeDigests) || !record.envelopeDigests.every((item) => typeof item === "string")) return null;
    (provenance as Record<string, unknown>).envelopeDigests = record.envelopeDigests;
  }
  if (record.projectionRef !== undefined) {
    const projectionRef = asEvidenceRecord(record.projectionRef);
    if (!projectionRef) return null;
    (provenance as Record<string, unknown>).projectionRef = projectionRef;
  }
  if (record.resultIdentity !== undefined) {
    const resultIdentity = asEvidenceRecord(record.resultIdentity);
    if (!resultIdentity) return null;
    (provenance as Record<string, unknown>).resultIdentity = resultIdentity;
  }
  if (record.projections !== undefined) {
    if (!Array.isArray(record.projections)) return null;
    const projections = record.projections
      .map(asEvidenceRecord)
      .filter((item): item is Record<string, unknown> => item !== null);
    if (projections.length !== record.projections.length) return null;
    (provenance as Record<string, unknown>).projections = projections;
  }
  return provenance;
}

/** Parse the server-owned report projection, including its provenance gate. */
export function readReportEvidenceProjection(value: unknown): ReportEvidenceProjection | null {
  const base = readReportEvidence(value);
  if (!base || !asEvidenceRecord(value)) return null;
  const candidate = asEvidenceRecord(value)!;
  const provenance = readEvidenceProvenance(candidate.provenance);
  if (!provenance) return null;
  const validationStatus = candidate.validationStatus;
  const validationSummary = asEvidenceRecord(candidate.validationSummary);
  if (typeof validationStatus !== "string" || validationStatus.trim().length === 0 || !validationSummary) return null;
  const commitId = candidate.commitId;
  const reasonCode = candidate.reasonCode;
  if (commitId !== undefined && typeof commitId !== "string") return null;
  if (reasonCode !== undefined && typeof reasonCode !== "string") return null;
  return {
    ...base,
    validationStatus,
    validationSummary,
    ...(commitId !== undefined ? { commitId } : {}),
    ...(reasonCode !== undefined ? { reasonCode } : {}),
    provenance,
  };
}

/** Construct a typed empty contribution when the server cannot admit facts. */
export function unavailableReportEvidence(
  reasonCode: string,
  artifactRef = "UNAVAILABLE",
): ReportEvidenceProjection {
  return {
    projectionId: `report:unavailable:${artifactRef}`,
    consumerId: "report",
    consumerVersion: "1.0",
    artifactRef,
    envelopeRef: "UNAVAILABLE",
    envelopeDigest: "UNAVAILABLE",
    status: "unavailable",
    executionStatus: "unavailable",
    availability: "unavailable",
    completenessStatus: "unavailable",
    validationStatus: "unavailable",
    validationSummary: {
      status: "unavailable",
      reasonCode,
    },
    facts: [],
    sections: [{ key: "persisted-evidence", label: "Persisted evidence", status: "unavailable" }],
    reasonCode,
    provenance: {
      artifactId: artifactRef,
      indexed: true,
      admissionStatus: "unavailable",
    },
  };
}

const MAX_TYPED_EVIDENCE_FACTS = 80;

/** Convert only the bounded server projection into citable report facts. */
export function buildReportEvidenceFacts(
  evidence: ReportEvidenceProjection | null | undefined,
  startAt = 0,
): CitableFact[] {
  if (!evidence || evidence.status !== "available") return [];
  const commitId = evidence.commitId ?? evidence.provenance.commitId;
  return evidence.facts.slice(0, MAX_TYPED_EVIDENCE_FACTS).map((fact, index) => ({
    id: `c${startAt + index + 1}`,
    node_key: `evidence:${evidence.projectionId}`,
    node_label: "Persisted report evidence",
    field: `evidence:${evidence.consumerId}:${fact.statisticId}`,
    label: `${fact.statisticId}${fact.unit ? ` (${fact.unit})` : ""}`,
    value: fact.value,
    provider_id: "evidence.report.typed.v1",
    kind: "estimate",
    artifact_ids: [evidence.artifactRef],
    qualifiers: {
      projection_id: evidence.projectionId,
      commit_id: commitId ?? "UNAVAILABLE",
      envelope_digest: evidence.envelopeDigest,
      fact_id: fact.factId,
      provenance: evidence.provenance,
    },
  }));
}

export interface ReportScope {
  run_id: string;
  node_count: number;
  node_keys: string[];
}

export interface FigureFactInput {
  artifact_id: string;
  chart_type: string;
  source?: {
    preview_json?: string;
    preview_truncated?: boolean;
    [key: string]: unknown;
  } | null;
}

const MAX_FIGURE_FACTS = 80;
const MAX_POST_ESTIMATION_FACTS = 80;

/** Extract only bounded numeric leaves from the serve-time figure source. */
export function buildFigureFacts(
  figures: FigureFactInput[],
  startAt = 0,
): CitableFact[] {
  const facts: CitableFact[] = [];
  let counter = startAt;
  const nextId = () => `c${++counter}`;

  for (const figure of figures) {
    const source = figure.source;
    const previewWasTruncated = source?.preview_truncated === true;
    if (previewWasTruncated) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:preview_truncated`,
        label: `${figure.chart_type} numeric preview truncated`,
        value: true,
      });
    }
    if (!source?.preview_json) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(source.preview_json) as unknown;
    } catch {
      if (!previewWasTruncated) {
        facts.push({
          id: nextId(),
          node_key: `figure:${figure.artifact_id}`,
          node_label: figure.chart_type,
          field: `figure:${figure.artifact_id}:preview_invalid`,
          label: `${figure.chart_type} numeric preview unavailable`,
          value: true,
        });
      }
      continue;
    }
    const leaves: Array<{ path: string; value: number }> = [];
    const locallyTruncated = collectNumericLeaves(
      parsed,
      "source",
      leaves,
      MAX_FIGURE_FACTS,
    );
    for (const leaf of leaves) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:${leaf.path}`,
        label: `${figure.chart_type} · ${leaf.path}`,
        value: leaf.value,
      });
    }
    if (locallyTruncated && !previewWasTruncated) {
      facts.push({
        id: nextId(),
        node_key: `figure:${figure.artifact_id}`,
        node_label: figure.chart_type,
        field: `figure:${figure.artifact_id}:preview_truncated`,
        label: `${figure.chart_type} numeric preview truncated`,
        value: true,
      });
    }
  }
  return facts;
}

type TimeSeriesArtifactMap = Record<string, unknown>;

function artifactPayload(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const record = value as Record<string, unknown>;
  const payload = record.payload;
  return payload && typeof payload === "object" && !Array.isArray(payload)
    ? payload as Record<string, unknown>
    : record;
}

function valueAt(root: Record<string, unknown>, path: string[]): unknown {
  let value: unknown = root;
  for (const key of path) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    value = (value as Record<string, unknown>)[key];
  }
  return value;
}

function isAtomicFact(value: unknown): value is string | number | boolean {
  return (
    (typeof value === "string" && value !== "")
    || (typeof value === "number" && Number.isFinite(value))
    || typeof value === "boolean"
  );
}

/** Reader-facing names for declared post-estimation operations. */
const POST_ESTIMATION_FACT_LABELS: Record<string, string> = {
  "model.quadratic_stationary_point": "Quadratic stationary point",
  "model.joint_f_test": "Joint F test",
  "model.white_test": "White test",
};

function workflowProviderId(entry: PostEstimationResult): string | undefined {
  if (entry.artifact_type === "p7_analysis") return "evidence.workflow.p7.v1";
  if (entry.artifact_type === "workflow_capability_result") {
    return "evidence.workflow.capability.v1";
  }
  return undefined;
}

function workflowProvenance(entry: PostEstimationResult): Record<string, unknown> {
  const provenance: Record<string, unknown> = {
    artifact_type: entry.artifact_type,
    operation_id: entry.operation_id,
    workflow_id: entry.workflow_id,
    workflow_step_id: entry.workflow_step_id,
  };
  for (const key of [
    "pack_family",
    "source_sha256",
    "request_fingerprint",
    "result_sha256",
    "result_schema",
  ] as const) {
    const value = entry[key];
    if (value !== undefined && value !== "") provenance[key] = value;
  }
  return provenance;
}

const POST_ESTIMATION_ENVELOPE_FIELDS = new Set([
  "schema_version",
  "contract",
  "contract_version",
  "operation_id",
]);

function collectPostEstimationAtomicValues(
  value: unknown,
  path: string[],
  emit: (path: string[], value: string | number | boolean) => boolean,
): boolean {
  if (isAtomicFact(value)) {
    return path.length > 0 ? emit(path, value) : true;
  }
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      if (!collectPostEstimationAtomicValues(item, [...path, `[${index}]`], emit)) {
        return false;
      }
    }
    return true;
  }
  if (!value || typeof value !== "object") return true;
  const entries = Object.entries(value);
  entries.sort(([left], [right]) => (
    Number(right === "inference") - Number(left === "inference")
  ));
  for (const [key, item] of entries) {
    if (POST_ESTIMATION_ENVELOPE_FIELDS.has(key)) continue;
    if (!collectPostEstimationAtomicValues(item, [...path, key], emit)) return false;
  }
  return true;
}

/** Compatibility-only reader for legacy direct callers.
 *
 * The ReportWorkspaceContext does not use this raw result adapter.  Its
 * citable post-estimation facts come exclusively from buildReportEvidenceFacts
 * after the server-owned committed projection has been parsed.
 *
 * Make declared post-estimation results citable in a generated report.
 *
 * These are server-computed scalars with artifact provenance, so they belong
 * in the deterministic fact table rather than in prose. Every atomic field of
 * the result is emitted, including qualifiers such as
 * `stationary_point_within_observed_range`: citing a turning point without the
 * flag saying it sits outside the observed data is how an extrapolation gets
 * reported as a finding. Schema tags are dropped -- they identify the payload
 * format, not the result. */
export function buildPostEstimationFacts(
  results: PostEstimationResult[],
  startAt = 0,
): CitableFact[] {
  const facts: CitableFact[] = [];
  let counter = startAt;
  for (const entry of results) {
    const label =
      POST_ESTIMATION_FACT_LABELS[entry.operation_id] ?? entry.operation_id;
    const providerId = workflowProviderId(entry);
    let truncated = false;
    collectPostEstimationAtomicValues(entry.result, [], (path, value) => {
      // Reserve one slot for a visible truncation marker. Without it, a large
      // result could look complete while later atomic evidence was discarded.
      if (facts.length >= MAX_POST_ESTIMATION_FACTS - 1) {
        truncated = true;
        return false;
      }
      const key = path.join(":");
      facts.push({
        id: `c${++counter}`,
        node_key: `post_estimation:${entry.workflow_step_id}`,
        node_label: label,
        field: `post_estimation:${entry.workflow_step_id}:${key}`,
        label: `${label} — ${key.replace(/_/g, " ")}`,
        value,
        ...(providerId ? { provider_id: providerId } : {}),
        artifact_ids: [entry.artifact_id],
        qualifiers: workflowProvenance(entry),
      });
      return true;
    });
    if (truncated) {
      facts.push({
        id: `c${++counter}`,
        node_key: `post_estimation:${entry.workflow_step_id}`,
        node_label: label,
        field: `post_estimation:${entry.workflow_step_id}:facts_truncated`,
        label: `${label} — evidence truncated at ${MAX_POST_ESTIMATION_FACTS - 1} facts`,
        value: true,
        ...(providerId ? { provider_id: providerId } : {}),
        artifact_ids: [entry.artifact_id],
        qualifiers: workflowProvenance(entry),
      });
      return facts;
    }
  }
  return facts;
}

/** Bounded whitelist of truthful scalar evidence from ARMA-GARCH artifacts. */
export function buildTimeSeriesFacts(
  artifacts: TimeSeriesArtifactMap,
  startAt = 0,
  provenance: { nodeKey: string; nodeLabel: string } = {
    nodeKey: "model:arma_garch_1",
    nodeLabel: "ARMA-GARCH",
  },
): CitableFact[] {
  const facts: CitableFact[] = [];
  let counter = startAt;
  const add = (field: string, label: string, value: unknown) => {
    if (!isAtomicFact(value) || facts.length >= 80) return;
    facts.push({
      id: `c${++counter}`,
      node_key: provenance.nodeKey,
      node_label: provenance.nodeLabel,
      field,
      label,
      value,
    });
  };
  const from = (
    artifactId: string,
    path: string[],
    field: string,
    label: string,
  ) => add(field, label, valueAt(artifactPayload(artifacts[artifactId]), path));

  // Keep the analysis contract alongside model evidence so a generated report
  // cannot silently describe transformed/filtered data as the raw source.
  from("ts.analysis_contract", ["transform"], "ts:contract:transform", "analysis transform");
  from(
    "ts.analysis_contract",
    ["missing_value_policy"],
    "ts:contract:missing_value_policy",
    "missing-value policy",
  );
  from(
    "ts.analysis_contract",
    ["estimation_strategy"],
    "ts:contract:estimation_strategy",
    "estimation strategy",
  );
  from(
    "ts.data_audit",
    ["data_quality", "finite_value_count"],
    "ts:data:analysis_observations",
    "analysis-view observations",
  );
  const auditDiagnostics = valueAt(artifactPayload(artifacts["ts.data_audit"]), ["diagnostics"]);
  if (Array.isArray(auditDiagnostics)) {
    const missingExclusion = auditDiagnostics.find((diagnostic) => (
      diagnostic
      && typeof diagnostic === "object"
      && !Array.isArray(diagnostic)
      && (diagnostic as Record<string, unknown>).code === "MISSING_OBSERVATIONS_EXCLUDED"
    ));
    if (missingExclusion && typeof missingExclusion === "object" && !Array.isArray(missingExclusion)) {
      add(
        "ts:data:excluded_missing_observations",
        "excluded missing observations",
        valueAt(missingExclusion as Record<string, unknown>, ["evidence", "excluded_missing_count"]),
      );
    }
  }

  from("ts.arma_selection", ["final_selected_candidate_id"], "ts:arma:selected_candidate", "selected ARMA specification");
  from("ts.volatility_selection", ["selected_candidate_id"], "ts:variance:selected_candidate", "selected variance specification");
  for (const [stage, prefix] of [["mean_stage", "mean"], ["variance_stage", "variance"]] as const) {
    for (const criterion of ["aic", "aicc", "bic"] as const) {
      from(
        "ts.final_model",
        ["validation_fit", stage, criterion],
        `ts:${prefix}:${criterion}`,
        `${prefix} ${criterion.toUpperCase()}`,
      );
    }
  }

  const parameters = artifactPayload(artifacts["ts.parameters"]);
  for (const [section, prefix] of [
    ["mean_candidate", "mean"],
    ["selected_variance_candidate", "variance"],
  ] as const) {
    const values = valueAt(parameters, [section]);
    if (!values || typeof values !== "object" || Array.isArray(values)) continue;
    for (const [name, value] of Object.entries(values as Record<string, unknown>)) {
      add(`ts:parameter:${prefix}:${name}`, `${prefix} parameter ${name}`, value);
    }
  }
  const variance = valueAt(parameters, ["selected_variance_candidate"]);
  if (variance && typeof variance === "object" && !Array.isArray(variance)) {
    const record = variance as Record<string, unknown>;
    const alpha = Object.entries(record)
      .filter(([key, value]) => key.startsWith("alpha[") && typeof value === "number")
      .reduce((sum, [, value]) => sum + Number(value), 0);
    const beta = Object.entries(record)
      .filter(([key, value]) => key.startsWith("beta[") && typeof value === "number")
      .reduce((sum, [, value]) => sum + Number(value), 0);
    if (alpha > 0 || beta > 0) {
      const persistence = alpha + beta;
      add("ts:volatility:persistence", "volatility persistence", persistence);
      if (persistence > 0 && persistence < 1) {
        add(
          "ts:volatility:half_life_observations",
          "volatility half-life (observations)",
          Math.log(0.5) / Math.log(persistence),
        );
      }
    }
  }

  for (const [path, field, label] of [
    [["arch_lm", "p_value"], "ts:diagnostic:arch_lm_p_value", "ARCH-LM p-value"],
    [["normality", "p_value"], "ts:diagnostic:normality_p_value", "normality p-value"],
    [["normality", "skew"], "ts:diagnostic:skew", "standardized residual skew"],
    [["normality", "kurtosis"], "ts:diagnostic:kurtosis", "standardized residual kurtosis"],
  ] as const) {
    from("ts.final_diagnostics", [...path], field, label);
  }
  for (const metric of [
    "validation_n", "successful_forecast_n", "mae", "rmse", "mean_error",
    "interval_coverage", "average_interval_width", "exception_count", "exception_rate",
    "pinball_loss",
  ]) {
    from("ts.forecast_metrics", [metric], `ts:validation:${metric}`, `validation ${metric}`);
  }
  for (const metric of [
    "conditional_mean", "conditional_variance", "conditional_volatility",
    "lower_bound", "upper_bound", "lower_quantile",
  ]) {
    from("ts.next_forecast", [metric], `ts:forecast:${metric}`, `next forecast ${metric}`);
  }
  return facts;
}

function collectNumericLeaves(
  value: unknown,
  path: string,
  leaves: Array<{ path: string; value: number }>,
  limit: number,
): boolean {
  if (typeof value === "number" && Number.isFinite(value)) {
    if (leaves.length >= limit) return true;
    leaves.push({ path, value });
    return false;
  }
  if (Array.isArray(value)) {
    for (const [index, item] of value.entries()) {
      if (collectNumericLeaves(item, `${path}[${index}]`, leaves, limit)) {
        return true;
      }
    }
    return false;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (collectNumericLeaves(item, `${path}.${key}`, leaves, limit)) {
        return true;
      }
    }
  }
  return false;
}

export function buildFactTable(
  forest: ForestViewModel,
  activeRunId: string,
): { facts: CitableFact[]; scope: ReportScope; fingerprints: string[] } {
  const pathNodes = forest.nodes.filter((node) => (node.runs ?? []).includes(activeRunId));
  const facts: CitableFact[] = [];
  const fingerprints: string[] = [];
  let counter = 0;
  const nextId = () => `c${++counter}`;

  for (const node of pathNodes) {
    const resolved = resolveNodeOperationContext({
      forest,
      selected_forest_node_key: node.nodeKey,
      active_head_run_id: activeRunId,
    });
    if (!resolved.ok) continue;
    const context = resolved.context;
    fingerprints.push(context.context_fingerprint);
    const nodeLabel = context.selection.display_label;

    for (const [key, value] of Object.entries(context.node_payload.params)) {
      if (!isAtomicFact(value)) continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `param:${key}`,
        label: key,
        value,
      });
    }
    const metrics = context.node_payload.metrics ?? {};
    for (const [key, value] of Object.entries(metrics)) {
      if (value === null || value === undefined) continue;
      if (typeof value === "object") continue; // scalars only — keep facts atomic
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `metric:${key}`,
        label: key,
        value,
      });
    }
    // v1.6.11 C-2 — model coefficient rows (serve-time decoration) expand into
    // atomic per-term facts so the report can cite estimates and p-values.
    const coefficientRows = Array.isArray(metrics.coefficients)
      ? metrics.coefficients
      : [];
    for (const row of coefficientRows) {
      if (!row || typeof row !== "object") continue;
      const { variable, estimate, std_error, p_value } = row as Record<string, unknown>;
      if (typeof variable !== "string" || typeof estimate !== "number") continue;
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `coef:${variable}`,
        label: `coefficient (${variable})`,
        value: estimate,
      });
      if (typeof std_error === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_se:${variable}`,
          label: `std. error (${variable})`,
          value: std_error,
        });
      }
      if (typeof p_value === "number") {
        facts.push({
          id: nextId(),
          node_key: node.nodeKey,
          node_label: nodeLabel,
          field: `coef_p:${variable}`,
          label: `p-value (${variable})`,
          value: p_value,
        });
      }
    }
    for (const decision of context.node_payload.decisions) {
      facts.push({
        id: nextId(),
        node_key: node.nodeKey,
        node_label: nodeLabel,
        field: `decision:${decision.id}`,
        label: decision.question,
        value: decision.picked,
      });
    }
  }

  return {
    facts,
    scope: {
      run_id: activeRunId,
      node_count: pathNodes.length,
      node_keys: pathNodes.map((n) => n.nodeKey),
    },
    fingerprints,
  };
}
