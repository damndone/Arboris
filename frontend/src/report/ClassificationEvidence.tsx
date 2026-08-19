import type { ReactNode } from "react";

type EvidenceRecord = Record<string, unknown>;

export type ClassificationEvidenceStatus = "validated" | "degraded" | "unavailable";

export interface ClassificationEvidenceTaskIdentity {
  readonly task_type: string;
  readonly positive_class: unknown;
  readonly class_support: Readonly<Record<string, number>>;
  readonly task_hash: string;
}

export interface ClassificationEvidenceSplitIdentity {
  readonly profile: string;
  readonly split_hash: string;
  readonly [key: string]: unknown;
}

export interface ClassificationEvidenceReleasePlan {
  readonly plan_hash: string;
  readonly task_hash: string;
  readonly split_hash: string;
  readonly model_id: string;
  readonly model_hash: string;
  readonly calibration_hash: string;
  readonly policy_hash: string;
  readonly [key: string]: unknown;
}

export interface ClassificationEvidenceHoldoutIdentity {
  readonly status: string;
  readonly release_plan_hash: string;
  readonly release_count: number;
  readonly release_plan: ClassificationEvidenceReleasePlan;
  readonly [key: string]: unknown;
}

export interface ClassificationEvidencePacket {
  readonly payload_schema: "workbench.prediction.classification-evidence";
  readonly schema_version: 1;
  readonly status: ClassificationEvidenceStatus;
  readonly task: ClassificationEvidenceTaskIdentity;
  readonly split: ClassificationEvidenceSplitIdentity;
  readonly metrics: Readonly<Record<string, unknown>>;
  readonly calibration: Readonly<Record<string, unknown>>;
  readonly baselines: readonly unknown[];
  readonly controls: readonly unknown[];
  readonly comparison: Readonly<Record<string, unknown>>;
  readonly explanations: Readonly<Record<string, unknown>>;
  readonly stability: Readonly<Record<string, unknown>>;
  readonly shift: Readonly<Record<string, unknown>>;
  readonly decision_policy: Readonly<Record<string, unknown>>;
  readonly blocked_reasons: readonly string[];
  readonly evidence_refs: Readonly<{
    readonly task: string;
    readonly split: string;
    readonly model: string;
    readonly holdout: string;
    readonly release_plan: string;
    readonly [key: string]: string;
  }>;
  readonly holdout: ClassificationEvidenceHoldoutIdentity;
  readonly c0_evidence_envelope: Readonly<Record<string, unknown>>;
  readonly c0_consumer_projection: Readonly<Record<string, unknown>>;
  readonly foundation_status: Readonly<{
    readonly execution_status: "completed" | "partial" | "blocked" | "failed";
    readonly availability: "available" | "not_available" | "not_applicable";
    readonly completeness_status: "complete" | "degraded" | "insufficient" | "not_applicable";
    readonly producer_status: ClassificationEvidenceStatus;
  }>;
}

const tableStyle = { fontSize: 12, borderCollapse: "collapse" as const };
const cellStyle = { padding: "2px 10px 2px 0", textAlign: "left" as const };
const SAFE_DISPLAY_KEYS = new Set([
  "positive_class", "class_support", "split_profile", "split_hash", "profile",
  "status", "reason", "brier", "ece", "calibration_method", "sample_scope", "n_bins",
  "selected_model", "same_split", "baseline_model", "metric", "direction",
  "method", "feature_count", "folds", "n_folds", "summary", "compared_to",
  "selection_status", "holdout", "threshold", "time_horizon", "cost_policy",
  "split", "holdout_ref", "calibration", "explanations", "stability", "shift",
]);

function asRecord(value: unknown): EvidenceRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as EvidenceRecord
    : null;
}

const CLASSIFICATION_EVIDENCE_SCHEMA = "workbench.prediction.classification-evidence";
const CLASSIFICATION_C0_CONSUMERS = new Set(["agent", "notebook", "report"]);
const CLASSIFICATION_C0_BASE_FACETS = new Set(["classification", "task", "split", "holdout", "release_plan"]);
const CLASSIFICATION_C0_STATUS = {
  validated: { execution_status: "completed", availability: "available", completeness_status: "complete", projection_status: "available", source_eligible: true },
  degraded: { execution_status: "completed", availability: "available", completeness_status: "degraded", projection_status: "available", source_eligible: false },
  unavailable: { execution_status: "blocked", availability: "not_available", completeness_status: "insufficient", projection_status: "blocked", source_eligible: false },
} as const;
const CLASSIFICATION_REQUIRED_FIELDS = [
  "status", "task", "split", "metrics", "calibration", "baselines", "controls", "comparison",
  "explanations", "stability", "shift", "decision_policy", "blocked_reasons", "evidence_refs",
  "holdout", "c0_evidence_envelope", "c0_consumer_projection", "foundation_status",
] as const;

function isFiniteNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= 0;
}

function isStringRecord(value: unknown): value is EvidenceRecord {
  const record = asRecord(value);
  return record !== null && Object.values(record).every((item) => typeof item === "string");
}

/** Validate the complete server-owned packet before any report rendering. */
export function isTypedClassificationEvidencePacket(value: unknown): value is ClassificationEvidencePacket {
  const packet = asRecord(value);
  if (
    packet === null
    || packet.payload_schema !== CLASSIFICATION_EVIDENCE_SCHEMA
    || packet.schema_version !== 1
    || (packet.status !== "validated" && packet.status !== "degraded" && packet.status !== "unavailable")
    || CLASSIFICATION_REQUIRED_FIELDS.some((field) => !(field in packet))
  ) return false;

  const status = packet.status;
  const expected = CLASSIFICATION_C0_STATUS[status];
  const task = asRecord(packet.task);
  const split = asRecord(packet.split);
  const comparison = asRecord(packet.comparison);
  const holdout = asRecord(packet.holdout);
  const releasePlan = asRecord(holdout?.release_plan);
  const evidenceRefs = asRecord(packet.evidence_refs);
  const foundation = asRecord(packet.foundation_status);
  if (
    task === null
    || typeof task.task_type !== "string"
    || typeof task.task_hash !== "string"
    || asRecord(task.class_support) === null
    || !Object.values(asRecord(task.class_support) as EvidenceRecord).every((item) => typeof item === "number" && Number.isFinite(item))
    || split === null
    || typeof split.profile !== "string"
    || typeof split.split_hash !== "string"
    || asRecord(packet.metrics) === null
    || asRecord(packet.calibration) === null
    || !Array.isArray(packet.baselines)
    || !Array.isArray(packet.controls)
    || comparison === null
    || typeof comparison.selected_model !== "string"
    || asRecord(packet.explanations) === null
    || asRecord(packet.stability) === null
    || asRecord(packet.shift) === null
    || asRecord(packet.decision_policy) === null
    || !Array.isArray(packet.blocked_reasons)
    || packet.blocked_reasons.some((item) => typeof item !== "string")
    || holdout === null
    || typeof holdout.status !== "string"
    || typeof holdout.release_plan_hash !== "string"
    || !isFiniteNonNegativeInteger(holdout.release_count)
    || releasePlan === null
    || typeof releasePlan.plan_hash !== "string"
    || typeof releasePlan.task_hash !== "string"
    || typeof releasePlan.split_hash !== "string"
    || typeof releasePlan.model_id !== "string"
    || typeof releasePlan.model_hash !== "string"
    || typeof releasePlan.calibration_hash !== "string"
    || typeof releasePlan.policy_hash !== "string"
    || releasePlan.plan_hash !== holdout.release_plan_hash
    || releasePlan.task_hash !== task.task_hash
    || releasePlan.split_hash !== split.split_hash
    || releasePlan.model_id !== comparison.selected_model
    || holdout.model_id !== comparison.selected_model
    || evidenceRefs === null
    || Object.keys(evidenceRefs).length !== 5
    || !isStringRecord(evidenceRefs)
  ) return false;

  const expectedRefs = {
    task: `classification-task:${task.task_hash}`,
    split: `classification-split:${split.split_hash}`,
    model: `classification-model:${comparison.selected_model}:${releasePlan.model_hash}`,
    holdout: `classification-holdout:${releasePlan.plan_hash}`,
    release_plan: `classification-release-plan:${releasePlan.plan_hash}`,
  };
  if (Object.entries(expectedRefs).some(([key, expectedRef]) => evidenceRefs[key] !== expectedRef)) return false;
  const envelope = asRecord(packet.c0_evidence_envelope);
  const envelopeIdentity = asRecord(envelope?.result_identity);
  const inputProvenance = asRecord(envelope?.input_provenance);
  const projection = asRecord(packet.c0_consumer_projection);
  const projectionPayload = asRecord(projection?.payload);
  const resultRef = `classification-evidence:${task.task_hash}:${split.split_hash}:${releasePlan.plan_hash}`;
  if (
    envelope === null
    || envelopeIdentity === null
    || inputProvenance === null
    || envelope.execution_status !== expected.execution_status
    || envelope.availability !== expected.availability
    || envelope.completeness_status !== expected.completeness_status
    || envelopeIdentity.result_ref !== resultRef
    || envelopeIdentity.task_hash !== task.task_hash
    || envelopeIdentity.split_hash !== split.split_hash
    || envelopeIdentity.holdout_hash !== releasePlan.plan_hash
    || envelopeIdentity.release_plan_hash !== releasePlan.plan_hash
    || inputProvenance.task_hash !== task.task_hash
    || inputProvenance.split_hash !== split.split_hash
    || inputProvenance.holdout_hash !== releasePlan.plan_hash
    || inputProvenance.release_plan_hash !== releasePlan.plan_hash
    || projection === null
    || projection.contract !== "consumer-projection"
    || projection.contract_version !== "1.0"
    || projection.producer_version !== "1.8.9"
    || projectionPayload === null
    || projectionPayload.projection_id !== resultRef
    || typeof projectionPayload.projection_ref !== "string"
    || projectionPayload.projection_ref.length === 0
    || projectionPayload.projection_status !== expected.projection_status
    || !Array.isArray(projectionPayload.slots)
    || projectionPayload.slots.length !== 3
  ) return false;

  const slots = projectionPayload.slots.map(asRecord);
  if (slots.some((slot) => slot === null)) return false;
  const consumers = new Set(slots.map((slot) => slot?.consumer));
  const expectedFacets = new Set(CLASSIFICATION_C0_BASE_FACETS);
  if (!expected.source_eligible) expectedFacets.add("degraded");
  if (
    consumers.size !== CLASSIFICATION_C0_CONSUMERS.size
    || [...consumers].some((consumer) => !CLASSIFICATION_C0_CONSUMERS.has(String(consumer)))
    || slots.some((slot) => {
      const facets = slot?.artifact_facets;
      return (
        typeof slot?.consumer !== "string"
        || !Array.isArray(facets)
        || facets.length !== expectedFacets.size
        || new Set(facets).size !== expectedFacets.size
        || facets.some((facet) => typeof facet !== "string" || !expectedFacets.has(facet))
        || slot?.payload_schema_ref !== CLASSIFICATION_EVIDENCE_SCHEMA
        || slot?.source_eligible !== expected.source_eligible
      );
    })
  ) return false;

  const notApplicable = asRecord(projectionPayload.not_applicable_projection);
  if (
    notApplicable === null
    || notApplicable.status !== "not_applicable"
    || typeof notApplicable.reason !== "string"
    || notApplicable.reason.length === 0
    || foundation === null
    || Object.keys(foundation).length !== 4
    || foundation.execution_status !== expected.execution_status
    || foundation.availability !== expected.availability
    || foundation.completeness_status !== expected.completeness_status
    || foundation.producer_status !== status
  ) return false;
  return true;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  // Typed evidence is rendered through allowlisted scalar fields. Never dump
  // an unvalidated nested object/array into the report surface.
  return "structured value unavailable";
}

function displayLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} style={{ marginTop: 10 }}>
      <h3 style={{ fontSize: 12, margin: "0 0 5px" }}>{title}</h3>
      {children}
    </section>
  );
}

function Unavailable({ label }: { label: string }) {
  return (
    <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
      {label} unavailable; no serialized value was supplied by the typed packet.
    </p>
  );
}

function KeyValueList({ value }: { value: unknown }) {
  const record = asRecord(value);
  const entries = record
    ? Object.entries(record).filter(([key]) => SAFE_DISPLAY_KEYS.has(key))
    : [];
  if (entries.length === 0) return <Unavailable label="Details" />;
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 }}>
      {entries.map(([key, item]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd style={{ margin: 0 }}>{displayValue(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

function MetricTable({ metrics }: { metrics: unknown }) {
  const record = asRecord(metrics);
  const entries = record ? Object.entries(record).map(([name, item]) => [name, asRecord(item)] as const) : [];
  const rows = entries.filter((entry): entry is readonly [string, EvidenceRecord] => entry[1] !== null);
  if (rows.length === 0) return <Unavailable label="Metrics" />;
  return (
    <table style={tableStyle}>
      <thead>
        <tr><th style={cellStyle}>Metric</th><th style={cellStyle}>Estimate</th><th style={cellStyle}>Status</th><th style={cellStyle}>Scope</th></tr>
      </thead>
      <tbody>
        {rows.map(([name, item]) => (
          <tr key={name}>
            <td style={cellStyle}>{displayLabel(name)}</td>
            <td style={cellStyle}>{displayValue(item.point_estimate)}</td>
            <td style={cellStyle}>{displayValue(item.status)}</td>
            <td style={cellStyle}>{displayValue(item.sample_scope)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RecordArray({ value, label }: { value: unknown; label: string }) {
  const items = asArray(value);
  if (items.length === 0) return <Unavailable label={label} />;
  return (
    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
      {items.map((item, index) => <li key={index}>{displayValue(item)}</li>)}
    </ul>
  );
}

function classificationTitle(task: unknown): string {
  const taskRecord = asRecord(task);
  const taskType = typeof taskRecord?.task_type === "string" ? taskRecord.task_type : "classification";
  return `${taskType.charAt(0).toUpperCase()}${taskType.slice(1)} classification`;
}

export function ClassificationEvidence({ evidence }: { evidence: ClassificationEvidencePacket }) {
  if (!isTypedClassificationEvidencePacket(evidence)) {
    return (
      <div data-testid="classification-evidence" style={{ fontSize: 13 }}>
        <strong>UNAVAILABLE</strong>
        <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "4px 0 0" }}>
          Classification evidence is unavailable because its typed C0 envelope or projection is invalid.
        </p>
      </div>
    );
  }
  const packet = evidence;
  const task = asRecord(packet.task);
  const split = asRecord(packet.split);
  const policy = asRecord(packet.decision_policy);
  const blockedReasons = asArray(packet.blocked_reasons).filter((item): item is string => typeof item === "string");
  const evidenceRefs = asRecord(packet.evidence_refs);

  return (
    <div data-testid="classification-evidence" style={{ fontSize: 13 }}>
      <h2 style={{ fontSize: 14, margin: 0 }}>{classificationTitle(task)}</h2>
      {blockedReasons.length > 0 && (
        <Section title="Blocked">
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
            {blockedReasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </Section>
      )}
      <Section title="Task and split">
        <KeyValueList value={{
          positive_class: task?.positive_class,
          class_support: task?.class_support,
          split_profile: split?.profile,
          split_hash: split?.split_hash,
        }} />
      </Section>
      <Section title="Class support">
        <KeyValueList value={task?.class_support} />
      </Section>
      <Section title="Metrics">
        <MetricTable metrics={packet.metrics} />
      </Section>
      <Section title="Calibration">
        <KeyValueList value={packet.calibration} />
      </Section>
      <Section title="Baselines and controls">
        <RecordArray value={packet.baselines} label="Baselines" />
        <RecordArray value={packet.controls} label="Controls" />
      </Section>
      <Section title="Comparison">
        <KeyValueList value={packet.comparison} />
      </Section>
      <Section title="Explanations and stability">
        <KeyValueList value={packet.explanations} />
        <KeyValueList value={packet.stability} />
      </Section>
      <Section title="Shift">
        <KeyValueList value={packet.shift} />
      </Section>
      <Section title="Decision policy and holdout boundary">
        <KeyValueList value={policy} />
        <KeyValueList value={evidenceRefs} />
      </Section>
    </div>
  );
}
