import {
  readReportEvidence,
  type EvidenceViewModel,
  type EvidenceFactViewModel,
  type EvidenceValidationProvenance,
} from "./reportEvidence";

const tableStyle = { fontSize: 12, borderCollapse: "collapse" as const };
const cellStyle = { padding: "2px 10px 2px 0", textAlign: "left" as const };

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function displayMetadata(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(displayMetadata).join(" · ");
  return "UNAVAILABLE";
}

function validationLabel(value: EvidenceValidationProvenance | undefined): string {
  if (typeof value === "string") return value;
  if (record(value)) {
    for (const key of ["validatorRef", "level", "validationLevel", "status"]) {
      if (value[key] !== undefined) return displayMetadata(value[key]);
    }
  }
  return "UNAVAILABLE";
}

function factInterval(fact: EvidenceFactViewModel) {
  return fact.interval ?? fact.confidenceInterval;
}

function factValidationLabel(fact: EvidenceFactViewModel): string {
  return validationLabel(fact.validationProvenance);
}

function projectionLineage(evidence: EvidenceViewModel): string {
  const refs = evidence.lineageRefs ?? evidence.provenance?.lineageRefs ?? [];
  return refs.length > 0 ? refs.join(" · ") : "UNAVAILABLE";
}

function projectionIdentity(evidence: EvidenceViewModel): string {
  const identity = evidence.identity ?? evidence.resultIdentity ?? evidence.provenance?.resultIdentity;
  const persistedIdentity = [
    ["project", evidence.projectRef],
    ["session", evidence.sessionRef],
    ["scope", evidence.scopeRef],
    ["run", evidence.runId],
    ["modelRun", evidence.modelRunId],
    ["commit", evidence.commitId],
  ]
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `${key}=${displayMetadata(value)}`);
  const resultIdentity = record(identity)
    ? ["contract", "result_id", "schema_version"]
      .filter((key) => identity[key] !== undefined)
      .map((key) => `${key}=${displayMetadata(identity[key])}`)
    : [];
  return [...persistedIdentity, ...resultIdentity].join(" · ") || "UNAVAILABLE";
}

function projectionValidationProvenance(evidence: EvidenceViewModel): string {
  return validationLabel(
    evidence.validationProvenance
      ?? evidence.provenance?.validatorRef
      ?? evidence.validationSummary,
  );
}

function TypedEvidenceProjection({ evidence }: { evidence: EvidenceViewModel }) {
  const hasReportProvenance = evidence.provenance !== undefined;
  const lineageRefs = evidence.provenance?.lineageRefs ?? [];
  const bundleDigests = evidence.provenance?.envelopeDigests ?? [];
  return (
    <section
      aria-label={`${evidence.consumerId} persisted evidence`}
      data-testid={`typed-evidence-${evidence.projectionId}`}
      style={{ marginBottom: 16 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Persisted evidence <span data-testid={`typed-evidence-status-${evidence.status}`}>{evidence.status.toUpperCase()}</span>
      </div>
      <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: "0 0 8px", fontSize: 12 }}>
        <dt>Artifact</dt><dd style={{ margin: 0 }}>{evidence.artifactRef}</dd>
        <dt>Envelope</dt><dd style={{ margin: 0 }}>{evidence.envelopeRef}</dd>
        <dt>Envelope digest</dt><dd style={{ margin: 0, wordBreak: "break-all" }}>{evidence.envelopeDigest}</dd>
        {evidence.dataSnapshotRef && evidence.dataSnapshotDigest && (
          <>
            <dt>Data snapshot</dt>
            <dd data-testid="typed-evidence-data-snapshot" style={{ margin: 0, wordBreak: "break-all" }}>
              {evidence.dataSnapshotRef} · {evidence.dataSnapshotDigest}
            </dd>
          </>
        )}
        <dt>Availability</dt><dd style={{ margin: 0 }}>{evidence.availability.toUpperCase()}</dd>
        <dt>Completeness</dt><dd style={{ margin: 0 }}>{evidence.completenessStatus.toUpperCase()}</dd>
        {evidence.validationStatus && evidence.validationSummary && (
          <>
            <dt>Validation</dt>
            <dd style={{ margin: 0 }}>{evidence.validationStatus.toUpperCase()}</dd>
            <dt>Validation summary</dt>
            <dd style={{ margin: 0 }}>
              {String(evidence.validationSummary.requirement_status ?? evidence.validationSummary.status ?? "UNAVAILABLE").toUpperCase()}
            </dd>
          </>
        )}
        {evidence.commitId && <><dt>Commit</dt><dd style={{ margin: 0 }}>{evidence.commitId}</dd></>}
        {hasReportProvenance && (
          <>
            <dt>Provenance</dt>
            <dd data-testid="typed-evidence-provenance" style={{ margin: 0 }}>
              {lineageRefs.length > 0
                ? lineageRefs.join(" · ")
                : bundleDigests.length > 0
                  ? bundleDigests.join(" · ")
                  : evidence.provenance?.artifactType ?? "UNAVAILABLE"}
            </dd>
          </>
        )}
        <dt>Validation provenance</dt>
        <dd data-testid="typed-evidence-validation-provenance" style={{ margin: 0 }}>
          {projectionValidationProvenance(evidence)}
        </dd>
        <dt>Lineage</dt>
        <dd data-testid="typed-evidence-lineage" style={{ margin: 0 }}>
          {projectionLineage(evidence)}
        </dd>
        <dt>Identity</dt>
        <dd data-testid="typed-evidence-identity" style={{ margin: 0 }}>
          {projectionIdentity(evidence)}
        </dd>
      </dl>
      {evidence.reasonCode && (
        <p data-testid="typed-evidence-reason" style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "0 0 6px" }}>
          Reason: {evidence.reasonCode}
        </p>
      )}
      {evidence.facts.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
          {evidence.status.toUpperCase()}: no persisted facts were supplied by this projection.
        </p>
      ) : (
        <table style={tableStyle}>
          <thead><tr><th style={cellStyle}>Fact</th><th style={cellStyle}>Statistic</th><th style={cellStyle}>Value</th><th style={cellStyle}>Unit</th><th style={cellStyle}>Interval</th><th style={cellStyle}>Caveat</th><th style={cellStyle}>Availability</th><th style={cellStyle}>Validation</th></tr></thead>
          <tbody>{evidence.facts.map((fact) => (
            <tr key={fact.factId} data-testid={`typed-evidence-fact-${fact.factId}`}>
              <td style={cellStyle}>{fact.factId}</td>
              <td style={cellStyle}>{fact.statisticId}</td>
              <td style={cellStyle}>{fact.value}</td>
              <td style={cellStyle}>{fact.unit ?? "UNAVAILABLE"}</td>
              <td style={cellStyle}>{factInterval(fact) ? `[${factInterval(fact)!.lower}, ${factInterval(fact)!.upper}]` : "UNAVAILABLE"}</td>
              <td style={cellStyle}>{fact.caveat ?? "UNAVAILABLE"}</td>
              <td style={cellStyle}>{(fact.availability ?? evidence.availability).toUpperCase()}</td>
              <td style={cellStyle}>{factValidationLabel(fact)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {evidence.sections.map((section) => (
        <p key={section.key} style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "6px 0 0" }}>
          {section.label}: {section.status.toUpperCase()}
        </p>
      ))}
    </section>
  );
}

function TypedEvidenceUnavailable() {
  return (
    <section
      aria-label="report persisted evidence unavailable"
      data-testid="typed-evidence-unavailable"
      style={{ marginBottom: 16 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Persisted evidence <span>UNAVAILABLE</span>
      </div>
      <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
        UNAVAILABLE: the server did not provide a typed evidence projection.
      </p>
    </section>
  );
}

/** Report family evidence is typed-only; raw model/artifact packets are never presentation inputs. */
export function FamilyEvidence({
  evidence,
}: {
  evidence?: EvidenceViewModel | null;
}) {
  const parsedEvidence = evidence === undefined || evidence === null
    ? null
    : readReportEvidence(evidence);
  return parsedEvidence
    ? <TypedEvidenceProjection evidence={parsedEvidence} />
    : <TypedEvidenceUnavailable />;
}
