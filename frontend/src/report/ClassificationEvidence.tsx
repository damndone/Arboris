import type { ReactNode } from "react";

type RecordValue = Record<string, unknown>;

export type ClassificationEvidencePacket = {
  status: "validated" | "blocked" | "unavailable";
  packet_id?: string;
  model_id?: string | null;
  task?: RecordValue;
  split?: RecordValue;
  evaluation?: RecordValue;
  calibration?: RecordValue;
  baselines?: unknown[];
  controls?: unknown[];
  comparison?: RecordValue;
  explanations?: RecordValue;
  decision_policy?: RecordValue;
  holdout_boundary?: RecordValue;
  warnings?: string[];
  blocked_reasons?: string[];
  evidence_receipt?: RecordValue;
  reason?: string;
};

function asRecord(value: unknown): RecordValue | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "—";
  }
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} style={{ marginTop: 10 }}>
      <h4 style={{ fontSize: 12, margin: "0 0 5px" }}>{title}</h4>
      {children}
    </section>
  );
}

function ValueList({ record }: { record: RecordValue | null }) {
  if (!record || Object.keys(record).length === 0) return <span>—</span>;
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 }}>
      {Object.entries(record).map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd style={{ margin: 0 }}>{display(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function metricRows(evaluation: RecordValue | null): Array<[string, unknown]> {
  const metrics = asRecord(evaluation?.metrics);
  if (!metrics) return [];
  return Object.entries(metrics);
}

export function ClassificationEvidence({
  evidence,
}: {
  evidence: ClassificationEvidencePacket | null | undefined;
}) {
  if (!evidence) return null;
  if (evidence.status === "unavailable") {
    return (
      <section data-testid="classification-evidence-unavailable" aria-label="Classification evidence unavailable" className="ios-card">
        <div className="ios-card-title">Classification evidence unavailable</div>
        <p>{evidence.reason ?? "No typed classification evidence packet was supplied."}</p>
      </section>
    );
  }
  if (evidence.status === "blocked") {
    return (
      <section data-testid="classification-evidence-blocked" aria-label="Classification evidence blocked" className="ios-card">
        <div className="ios-card-title">Classification evidence blocked</div>
        <ul>{(evidence.blocked_reasons ?? evidence.warnings ?? ["The classification run did not produce usable evidence."]).map((reason) => <li key={reason}>{reason}</li>)}</ul>
      </section>
    );
  }

  const task = asRecord(evidence.task);
  const split = asRecord(evidence.split);
  const evaluation = asRecord(evidence.evaluation);
  const calibration = asRecord(evidence.calibration);
  const diagnostics = asRecord(evaluation?.diagnostics);
  const policy = asRecord(evidence.decision_policy);
  const holdout = asRecord(evidence.holdout_boundary);
  const receipt = asRecord(evidence.evidence_receipt);
  const classMapping = asRecord(task?.class_mapping);
  const controls = asArray(evidence.controls);
  const baselines = asArray(evidence.baselines);
  const explanations = asRecord(evidence.explanations);

  return (
    <section data-testid="classification-evidence" aria-label="Classification evidence" className="ios-card">
      <div className="ios-card-title">Classification evidence</div>
      <p style={{ fontSize: 12 }}>
        Target: <strong>{display(task?.target)}</strong> · Positive class: <strong>{display(task?.positive_class)}</strong> · Selected model: <strong>{display(evidence.model_id)}</strong>
      </p>
      <Section title="Task and split">
        <ValueList record={{ structure: task?.structure, class_mapping: classMapping, profile: split?.profile, split_hash: split?.split_hash }} />
      </Section>
      <Section title="Evaluation metrics">
        {metricRows(evaluation).length === 0 ? <p>Metrics unavailable in the typed packet.</p> : (
          <table style={{ fontSize: 12, borderCollapse: "collapse" }}>
            <tbody>{metricRows(evaluation).map(([name, value]) => {
              const metric = asRecord(value);
              return <tr key={name}><th style={{ textAlign: "left", paddingRight: 12 }}>{name}</th><td>{display(metric?.point_estimate ?? metric?.value ?? value)}</td><td style={{ paddingLeft: 12, color: "var(--label-tertiary)" }}>source: {display(metric?.source ?? metric?.sample_scope)}</td></tr>;
            })}</tbody>
          </table>
        )}
      </Section>
      <Section title="Calibration and baselines">
        <ValueList record={calibration} />
        {baselines.length > 0 && <p>Baselines: {baselines.map((baseline, index) => display(asRecord(baseline)?.baseline_id ?? index)).join(", ")}</p>}
      </Section>
      <Section title="Diagnostics and shift">
        {!diagnostics ? <p>No predeclared diagnostic release was supplied.</p> : (
          <>
            <ValueList record={{ status: diagnostics.status, plan_hash: diagnostics.plan_hash, plan: diagnostics.plan }} />
            <p>Subgroups: {display(diagnostics.subgroups)}</p>
            <p>Shift: {display(diagnostics.shift)}</p>
          </>
        )}
      </Section>
      <Section title="Controls and comparison">
        <p>{controls.length > 0 ? controls.map((control, index) => display(asRecord(control)?.control_id ?? index)).join(", ") : "No control receipts"}</p>
        <ValueList record={evidence.comparison ? asRecord(evidence.comparison) : null} />
      </Section>
      <Section title="Explanation limits">
        <ValueList record={explanations} />
        {(evidence.warnings ?? []).map((warning) => <p key={warning} style={{ color: "var(--label-tertiary)" }}>{warning}</p>)}
      </Section>
      <Section title="Decision policy and holdout boundary">
        <ValueList record={{ ...policy, holdout_status: holdout?.status, holdout_access_count: holdout?.access_count }} />
      </Section>
      <Section title="Evidence receipt">
        <ValueList record={receipt} />
      </Section>
    </section>
  );
}
