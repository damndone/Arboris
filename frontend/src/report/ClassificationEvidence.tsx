import type { ReactNode } from "react";

type EvidenceRecord = Record<string, unknown>;

export type ClassificationEvidencePacket = Readonly<Record<string, unknown>>;

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
  const packet = asRecord(evidence) ?? {};
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
