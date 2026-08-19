import type { ReportEvidenceProjection } from "./factTable";
import type { EvidenceViewModel } from "./reportEvidence";

type TypedEvidence = EvidenceViewModel | ReportEvidenceProjection;

const tableStyle = { fontSize: 12, borderCollapse: "collapse" as const };
const cellStyle = { padding: "2px 10px 2px 0", textAlign: "left" as const };

function TypedEvidenceProjection({ evidence }: { evidence: TypedEvidence }) {
  const hasReportProvenance = "provenance" in evidence;
  const reportEvidence = hasReportProvenance ? evidence as ReportEvidenceProjection : null;
  const lineageRefs = reportEvidence?.provenance.lineageRefs ?? [];
  const bundleDigests = reportEvidence?.provenance.envelopeDigests ?? [];
  return (
    <section
      aria-label={`${evidence.consumerId} persisted evidence`}
      data-testid={`typed-evidence-${evidence.projectionId}`}
      style={{ marginBottom: 16 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Persisted evidence <span>{evidence.status.toUpperCase()}</span>
      </div>
      <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: "0 0 8px", fontSize: 12 }}>
        <dt>Artifact</dt><dd style={{ margin: 0 }}>{evidence.artifactRef}</dd>
        <dt>Envelope</dt><dd style={{ margin: 0 }}>{evidence.envelopeRef}</dd>
        <dt>Envelope digest</dt><dd style={{ margin: 0, wordBreak: "break-all" }}>{evidence.envelopeDigest}</dd>
        <dt>Availability</dt><dd style={{ margin: 0 }}>{evidence.availability.toUpperCase()}</dd>
        <dt>Completeness</dt><dd style={{ margin: 0 }}>{evidence.completenessStatus.toUpperCase()}</dd>
        {reportEvidence && (
          <>
            <dt>Validation</dt>
            <dd style={{ margin: 0 }}>{reportEvidence.validationStatus.toUpperCase()}</dd>
            <dt>Validation summary</dt>
            <dd style={{ margin: 0 }}>
              {String(reportEvidence.validationSummary.requirement_status ?? reportEvidence.validationSummary.status ?? "UNAVAILABLE").toUpperCase()}
            </dd>
          </>
        )}
        {reportEvidence?.commitId && <><dt>Commit</dt><dd style={{ margin: 0 }}>{reportEvidence.commitId}</dd></>}
        {hasReportProvenance && (
          <>
            <dt>Provenance</dt>
            <dd data-testid="typed-evidence-provenance" style={{ margin: 0 }}>
              {lineageRefs.length > 0
                ? lineageRefs.join(" · ")
                : bundleDigests.length > 0
                  ? bundleDigests.join(" · ")
                  : reportEvidence?.provenance.artifactType ?? "UNAVAILABLE"}
            </dd>
          </>
        )}
      </dl>
      {reportEvidence?.reasonCode && (
        <p data-testid="typed-evidence-reason" style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "0 0 6px" }}>
          Reason: {reportEvidence.reasonCode}
        </p>
      )}
      {evidence.facts.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
          UNAVAILABLE: no persisted facts were supplied by this projection.
        </p>
      ) : (
        <table style={tableStyle}>
          <thead><tr><th style={cellStyle}>Fact</th><th style={cellStyle}>Statistic</th><th style={cellStyle}>Value</th><th style={cellStyle}>Unit</th></tr></thead>
          <tbody>{evidence.facts.map((fact) => (
            <tr key={fact.factId}>
              <td style={cellStyle}>{fact.factId}</td>
              <td style={cellStyle}>{fact.statisticId}</td>
              <td style={cellStyle}>{fact.value}</td>
              <td style={cellStyle}>{fact.unit ?? "UNAVAILABLE"}</td>
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
  evidence?: TypedEvidence | null;
}) {
  return evidence
    ? <TypedEvidenceProjection evidence={evidence} />
    : <TypedEvidenceUnavailable />;
}
