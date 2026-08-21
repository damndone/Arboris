import { useMemo } from "react";
import { sha256CanonicalV1 } from "./factTable";

type EvidenceRecord = Record<string, unknown>;
type DataConsumerStatus = "available" | "unavailable";

export interface DataConsumerReportEvidenceValue {
  readonly status: DataConsumerStatus;
  readonly reasonCode: string | null;
  readonly authority: "server-owned";
  readonly projectionDigest: string | null;
  readonly catalogDigest: string | null;
  readonly runId: string | null;
  readonly factCount: number;
  readonly lineageRefs: readonly string[];
}

const DATA_CONSUMER_SCHEMA = "workbench.data.consumer-evidence.v1";
const DATA_CONSUMER_RECEIPT = "evidence.data-consumer.server-receipt.v1";
const SHA256 = /^[0-9a-f]{64}$/;

function asRecord(value: unknown): EvidenceRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as EvidenceRecord
    : null;
}

function unavailable(reasonCode: string): DataConsumerReportEvidenceValue {
  return {
    status: "unavailable",
    reasonCode,
    authority: "server-owned",
    projectionDigest: null,
    catalogDigest: null,
    runId: null,
    factCount: 0,
    lineageRefs: [],
  };
}

export function unavailableDataConsumerReportEvidence(reasonCode: string): EvidenceRecord {
  return {
    schema_version: 1,
    payload_schema: DATA_CONSUMER_SCHEMA,
    consumer_id: "report",
    status: "unavailable",
    authority: "server-owned",
    reason_code: reasonCode,
    facts: [],
    projection_digest: null,
    catalog_digest: null,
    receipt: null,
  };
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function opaqueIdentity(value: unknown): value is string {
  return nonEmptyString(value)
    && value === value.trim()
    && !value.includes("/")
    && !value.includes("\\")
    && !value.includes("..")
    && !value.includes("\u0000");
}

const DATA_FACT_FIELDS = new Set([
  "fact_id",
  "kind",
  "operation_id",
  "operation_version",
  "record_id",
  "execution_key",
  "child_node_id",
  "artifact_ids",
  "evidence_digest",
  "catalog_digest",
  "run_id",
  "source_run_id",
  "source_node_id",
  "source_artifact_id",
  "data_snapshot_ref",
  "data_snapshot_digest",
  "method",
]);

function readDataFact(value: unknown, catalogDigest: string, runId: string): EvidenceRecord | null {
  const fact = asRecord(value);
  if (fact === null) return null;
  const keys = new Set(Object.keys(fact));
  for (const key of DATA_FACT_FIELDS) {
    if (key === "method") continue;
    if (!keys.has(key)) return null;
  }
  for (const key of keys) {
    if (!DATA_FACT_FIELDS.has(key)) return null;
  }
  const textFields = [
    "fact_id",
    "kind",
    "operation_id",
    "operation_version",
    "record_id",
    "execution_key",
    "child_node_id",
    "run_id",
    "source_run_id",
    "source_node_id",
    "source_artifact_id",
    "data_snapshot_ref",
  ];
  if (textFields.some((key) => !opaqueIdentity(fact[key]))) return null;
  const operationId = fact.operation_id;
  if (fact.fact_id !== `data-operation:${fact.record_id}`
    || fact.run_id !== runId
    || fact.source_run_id !== runId
    || !nonEmptyString(operationId)
    || !/^data\.[A-Za-z0-9_.-]+$/.test(operationId)) return null;
  if (fact.method !== undefined && !nonEmptyString(fact.method)) return null;
  if (!Array.isArray(fact.artifact_ids)
    || fact.artifact_ids.length === 0
    || fact.artifact_ids.some((item) => !opaqueIdentity(item))
    || new Set(fact.artifact_ids).size !== fact.artifact_ids.length) return null;
  for (const key of ["evidence_digest", "catalog_digest", "data_snapshot_digest"]) {
    if (!SHA256.test(String(fact[key]))) return null;
  }
  if (fact.catalog_digest !== catalogDigest) return null;
  return {
    ...fact,
    artifact_ids: [...fact.artifact_ids],
  };
}

/**
 * Parse only the bounded server-owned identity.  Data rows, operation output,
 * and unknown payload fields intentionally never cross this boundary.
 */
export function readDataConsumerReportEvidence(
  value: unknown,
  expectedRunId?: string,
): DataConsumerReportEvidenceValue {
  const record = asRecord(value);
  if (
    record === null
    || record.payload_schema !== DATA_CONSUMER_SCHEMA
    || record.schema_version !== 1
    || record.consumer_id !== "report"
    || record.authority !== "server-owned"
    || (record.status !== "available" && record.status !== "unavailable")
  ) return unavailable("DATA_CONSUMER_SCHEMA_INVALID");

  if (record.status === "unavailable") {
    const reason = record.reason_code ?? record.reason;
    return unavailable(nonEmptyString(reason) ? reason : "DATA_CONSUMER_PROJECTION_UNAVAILABLE");
  }

  if (
    !nonEmptyString(record.run_id)
    || (expectedRunId !== undefined && record.run_id !== expectedRunId)
    || !nonEmptyString(record.projection_digest)
    || !SHA256.test(record.projection_digest)
    || !nonEmptyString(record.catalog_digest)
    || !SHA256.test(record.catalog_digest)
    || !nonEmptyString(record.scope_digest)
    || !SHA256.test(record.scope_digest)
    || !Array.isArray(record.facts)
    || record.facts.length > 64
    || record.source !== "persisted-data-operation-output"
    || record.availability !== "available"
    || record.execution_status !== "completed"
    || record.completeness_status !== "complete"
    || record.reason_code !== null
  ) return unavailable(
    expectedRunId !== undefined && record.run_id !== expectedRunId
      ? "DATA_CONSUMER_SCOPE_MISMATCH"
      : "DATA_CONSUMER_PROJECTION_INVALID",
  );

  const facts = record.facts.map((fact) => readDataFact(fact, record.catalog_digest as string, record.run_id as string));
  if (facts.some((fact): fact is null => fact === null)) {
    return unavailable("DATA_CONSUMER_FACT_INVALID");
  }
  const validFacts = facts.filter((fact): fact is EvidenceRecord => fact !== null);
  let computedProjectionDigest: string;
  try {
    computedProjectionDigest = sha256CanonicalV1({
      schema_version: 1,
      payload_schema: DATA_CONSUMER_SCHEMA,
      scope_digest: record.scope_digest,
      facts: validFacts,
      catalog_digest: record.catalog_digest,
    });
  } catch {
    return unavailable("DATA_CONSUMER_PROJECTION_DIGEST_INVALID");
  }
  if (record.projection_digest !== computedProjectionDigest) {
    return unavailable("DATA_CONSUMER_PROJECTION_DIGEST_INVALID");
  }

  const receipt = asRecord(record.receipt);
  const receiptIdentity = asRecord(receipt?.identity);
  if (
    receipt === null
    || receipt.schemaVersion !== 1
    || receipt.kind !== DATA_CONSUMER_RECEIPT
    || receipt.projectionDigest !== record.projection_digest
    || receiptIdentity === null
    || receiptIdentity.consumerId !== "report"
    || receiptIdentity.runId !== record.run_id
    || receiptIdentity.scopeDigest !== record.scope_digest
    || receiptIdentity.catalogDigest !== record.catalog_digest
  ) return unavailable("DATA_CONSUMER_RECEIPT_INVALID");

  const lineageRefs: string[] = [];
  for (const factRecord of validFacts) {
    for (const key of ["source_node_id", "source_artifact_id"]) {
      const ref = factRecord[key];
      if (nonEmptyString(ref) && !lineageRefs.includes(ref)) lineageRefs.push(ref);
    }
  }
  return {
    status: "available",
    reasonCode: null,
    authority: "server-owned",
    projectionDigest: record.projection_digest,
    catalogDigest: record.catalog_digest,
    runId: record.run_id,
    factCount: record.facts.length,
    lineageRefs,
  };
}

export function DataConsumerReportEvidence({
  evidence,
  expectedRunId,
}: {
  evidence: unknown;
  expectedRunId?: string;
}) {
  const parsed = useMemo(
    () => readDataConsumerReportEvidence(evidence, expectedRunId),
    [evidence, expectedRunId],
  );
  const status = parsed.status.toUpperCase();
  return (
    <section
      aria-label="Data consumer evidence"
      data-testid="report-data-consumer-evidence"
      style={{ marginBottom: 16 }}
    >
      <div className="report-evidence-card__heading">Data-operation evidence</div>
      <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 }}>
        <dt>Status</dt>
        <dd data-testid="report-data-consumer-status" style={{ margin: 0 }}>{status}</dd>
        <dt>Authority</dt>
        <dd style={{ margin: 0 }}>{parsed.authority}</dd>
        {parsed.runId && (
          <>
            <dt>Run</dt>
            <dd style={{ margin: 0 }}><code>{parsed.runId}</code></dd>
          </>
        )}
        {parsed.status === "available" && (
          <>
            <dt>Facts</dt>
            <dd style={{ margin: 0 }}>{parsed.factCount}</dd>
            <dt>Projection receipt</dt>
            <dd data-testid="report-data-consumer-projection-digest" style={{ margin: 0 }}><code>{parsed.projectionDigest}</code></dd>
            <dt>Lineage</dt>
            <dd data-testid="report-data-consumer-lineage" style={{ margin: 0 }}>{parsed.lineageRefs.join(", ") || "UNAVAILABLE"}</dd>
          </>
        )}
      </dl>
      {parsed.reasonCode && (
        <p data-testid="report-data-consumer-reason" style={{ fontSize: 12, color: "var(--label-tertiary)", margin: "6px 0 0" }}>
          Reason: {parsed.reasonCode}
        </p>
      )}
    </section>
  );
}
