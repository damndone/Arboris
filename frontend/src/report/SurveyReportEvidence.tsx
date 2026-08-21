import { useMemo } from "react";
import { sha256CanonicalV1 } from "./factTable";

type EvidenceRecord = Record<string, unknown>;
type SurveyStatus = "validated" | "degraded" | "unavailable";

export interface SurveyReportEvidenceValue {
  readonly status: SurveyStatus;
  readonly reasonCode: string | null;
  readonly authority: "server-owned";
  readonly modelFamily: string | null;
  readonly varianceMethod: string | null;
  readonly runId: string | null;
  readonly artifactId: string | null;
}

const SURVEY_SCHEMA = "workbench.survey.report-evidence.v1";
const SURVEY_RECEIPT = "evidence.survey.server-receipt.v1";
const SHA256 = /^[0-9a-f]{64}$/;

function asRecord(value: unknown): EvidenceRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as EvidenceRecord
    : null;
}

function unavailable(reasonCode: string): SurveyReportEvidenceValue {
  return {
    status: "unavailable",
    reasonCode,
    authority: "server-owned",
    modelFamily: null,
    varianceMethod: null,
    runId: null,
    artifactId: null,
  };
}

export function unavailableSurveyReportEvidence(reasonCode: string): EvidenceRecord {
  return {
    payload_schema: SURVEY_SCHEMA,
    schema_version: 1,
    provider_id: "workbench.survey",
    consumer: "report",
    status: "unavailable",
    authority: "server-owned",
    reason: reasonCode,
    survey_design: null,
    source: null,
    receipt: null,
  };
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function contractRef(value: unknown, expectedKind: string): value is EvidenceRecord {
  const ref = asRecord(value);
  return ref !== null
    && ref.kind === expectedKind
    && nonEmptyString(ref.logical_id)
    && nonEmptyString(ref.semantic_version)
    && SHA256.test(String(ref.contract_digest));
}

function exactKeys(value: EvidenceRecord, allowed: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  return keys.every((key) => allowed.includes(key))
    && allowed.every((key) => key === "reason" || key === "receipt" || key === "model_family"
      ? true
      : Object.prototype.hasOwnProperty.call(value, key));
}

/** Normalize only bounded Survey design identity; never render raw artifact JSON. */
export function readSurveyReportEvidence(
  value: unknown,
  expectedRunId?: string,
): SurveyReportEvidenceValue {
  const record = asRecord(value);
  if (
    record === null
    || record.payload_schema !== SURVEY_SCHEMA
    || record.schema_version !== 1
    || record.provider_id !== "workbench.survey"
    || record.consumer !== "report"
    || record.authority !== "server-owned"
    || (record.status !== "validated" && record.status !== "degraded" && record.status !== "unavailable")
  ) return unavailable("SURVEY_EVIDENCE_SCHEMA_INVALID");

  if (record.status === "unavailable") {
    const reason = record.reason ?? record.reason_code;
    return unavailable(nonEmptyString(reason) ? reason : "SURVEY_EVIDENCE_UNAVAILABLE");
  }

  const source = asRecord(record.source);
  const serverIdentity = asRecord(source?.server_identity);
  const design = asRecord(record.survey_design);
  const catalog = asRecord(record.catalog);
  const receipt = asRecord(record.receipt);
  const receiptIdentity = asRecord(receipt?.identity);
  const runId = serverIdentity?.run_id;
  const artifactId = source?.artifact_id;
  const artifactSha256 = source?.artifact_sha256;
  const receiptDigest = source?.receipt_digest;
  const varianceMethod = design?.variance_method;
  const modelFamily = record.model_family;
  if (
    !exactKeys(record, [
      "authority",
      "catalog",
      "consumer",
      "model_family",
      "payload_schema",
      "provider_id",
      "reason",
      "receipt",
      "schema_version",
      "source",
      "status",
      "survey_design",
    ])
    ||
    !nonEmptyString(runId)
    || (expectedRunId !== undefined && runId !== expectedRunId)
    || !nonEmptyString(artifactId)
    || !nonEmptyString(artifactSha256)
    || !SHA256.test(artifactSha256)
    || !nonEmptyString(receiptDigest)
    || !SHA256.test(receiptDigest)
    || !nonEmptyString(varianceMethod)
    || !nonEmptyString(modelFamily)
    || modelFamily === "unknown"
    || serverIdentity?.model_id !== artifactId
    || catalog === null
    || catalog.provider_id !== "workbench.survey"
    || catalog.path_id !== "workbench.survey.central_source"
    || !nonEmptyString(catalog.digest)
    || !SHA256.test(catalog.digest)
    || !contractRef(catalog.projection_ref, "projection")
    || !Array.isArray(catalog.evidence_contract_refs)
    || catalog.evidence_contract_refs.length === 0
    || catalog.evidence_contract_refs.some((ref) => !contractRef(ref, "evidence"))
    || !contractRef(catalog.policy_ref, "policy")
    || !contractRef(catalog.renderer_ref, "renderer")
    || receipt === null
    || receipt.schemaVersion !== 1
    || receipt.kind !== SURVEY_RECEIPT
    || !nonEmptyString(receipt.projectionDigest)
    || !SHA256.test(receipt.projectionDigest)
    || receiptIdentity === null
    || receiptIdentity.consumerId !== "report"
    || receiptIdentity.runId !== runId
    || receiptIdentity.artifactId !== artifactId
    || receiptIdentity.artifactSha256 !== artifactSha256
    || receiptIdentity.sourceReceiptDigest !== receiptDigest
    || receiptIdentity.catalogDigest !== catalog.digest
  ) {
    return unavailable(
      expectedRunId !== undefined && runId !== expectedRunId
        ? "SURVEY_EVIDENCE_SCOPE_MISMATCH"
        : "SURVEY_EVIDENCE_RECEIPT_INVALID",
    );
  }
  let expectedProjectionDigest: string;
  try {
    const { consumer: _consumer, receipt: _receipt, ...receiptPayload } = record;
    expectedProjectionDigest = sha256CanonicalV1(receiptPayload);
  } catch {
    return unavailable("SURVEY_EVIDENCE_RECEIPT_INVALID");
  }
  if (receipt.projectionDigest !== expectedProjectionDigest) {
    return unavailable("SURVEY_EVIDENCE_PROJECTION_DIGEST_INVALID");
  }
  return {
    status: record.status,
    reasonCode: nonEmptyString(record.reason) ? record.reason : null,
    authority: "server-owned",
    modelFamily,
    varianceMethod,
    runId,
    artifactId,
  };
}

export function SurveyReportEvidence({
  evidence,
  expectedRunId,
}: {
  evidence: unknown;
  expectedRunId?: string;
}) {
  const parsed = useMemo(
    () => readSurveyReportEvidence(evidence, expectedRunId),
    [evidence, expectedRunId],
  );
  return (
    <section
      aria-label="Survey evidence"
      data-testid="report-survey-evidence"
      style={{ marginBottom: 16 }}
    >
      <div className="report-evidence-card__heading">Complex-survey evidence</div>
      <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 }}>
        <dt>Status</dt>
        <dd data-testid="report-survey-status" style={{ margin: 0 }}>{parsed.status.toUpperCase()}</dd>
        <dt>Authority</dt>
        <dd style={{ margin: 0 }}>{parsed.authority}</dd>
        {parsed.modelFamily && (
          <>
            <dt>Model family</dt>
            <dd style={{ margin: 0 }}>{parsed.modelFamily}</dd>
          </>
        )}
        {parsed.varianceMethod && (
          <>
            <dt>Variance method</dt>
            <dd style={{ margin: 0 }}>{parsed.varianceMethod}</dd>
          </>
        )}
        {parsed.runId && (
          <>
            <dt>Run</dt>
            <dd style={{ margin: 0 }}><code>{parsed.runId}</code></dd>
          </>
        )}
      </dl>
      {parsed.reasonCode && (
        <p data-testid="report-survey-reason" style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "6px 0 0" }}>
          Reason: {parsed.reasonCode}
        </p>
      )}
    </section>
  );
}
