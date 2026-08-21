import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  DataConsumerReportEvidence,
  readDataConsumerReportEvidence,
} from "./ReportDataConsumerEvidence";
import { sha256CanonicalV1 } from "./factTable";

const available = {
  schema_version: 1,
  payload_schema: "workbench.data.consumer-evidence.v1",
  consumer_id: "report",
  status: "available",
  availability: "available",
  execution_status: "completed",
  completeness_status: "complete",
  authority: "server-owned",
  source: "persisted-data-operation-output",
  facts: [
    {
      fact_id: "data-operation:record-1",
      kind: "data_operation",
      operation_id: "data.subset",
      operation_version: "1.0",
      record_id: "record-1",
      execution_key: "execution-1",
      child_node_id: "child-1",
      artifact_ids: ["artifact-1"],
      evidence_digest: "d".repeat(64),
      catalog_digest: "b".repeat(64),
      run_id: "run-1",
      source_run_id: "run-1",
      source_node_id: "node-1",
      source_artifact_id: "artifact-1",
      data_snapshot_ref: "snapshot-1",
      data_snapshot_digest: "e".repeat(64),
    },
  ],
  projection_digest: "a".repeat(64),
  catalog_digest: "b".repeat(64),
  reason_code: null,
  run_id: "run-1",
  scope_digest: "c".repeat(64),
  receipt: {
    schemaVersion: 1,
    kind: "evidence.data-consumer.server-receipt.v1",
    projectionDigest: "a".repeat(64),
    identity: {
      consumerId: "report",
      runId: "run-1",
      scopeDigest: "c".repeat(64),
      catalogDigest: "b".repeat(64),
    },
  },
};

available.projection_digest = sha256CanonicalV1({
  schema_version: 1,
  payload_schema: available.payload_schema,
  scope_digest: available.scope_digest,
  facts: available.facts,
  catalog_digest: available.catalog_digest,
});
available.receipt.projectionDigest = available.projection_digest;

describe("Report data-consumer evidence boundary", () => {
  it("normalizes only the server-owned evidence identity and lineage", () => {
    const parsed = readDataConsumerReportEvidence(available, "run-1");
    expect(parsed).toMatchObject({
      status: "available",
      projectionDigest: available.projection_digest,
      catalogDigest: "b".repeat(64),
      runId: "run-1",
      factCount: 1,
      lineageRefs: ["node-1", "artifact-1"],
    });
  });

  it("rejects a forged or raw-shaped payload into typed unavailable", () => {
    const parsed = readDataConsumerReportEvidence(
      { ...available, raw: "DO_NOT_RENDER", receipt: null },
      "run-1",
    );
    expect(parsed?.status).toBe("unavailable");
    expect(parsed?.reasonCode).toBe("DATA_CONSUMER_RECEIPT_INVALID");
    expect(parsed).not.toHaveProperty("raw");
  });

  it("rejects a changed projection digest even when the receipt repeats it", () => {
    const parsed = readDataConsumerReportEvidence(
      {
        ...available,
        projection_digest: "f".repeat(64),
        receipt: {
          ...available.receipt,
          projectionDigest: "f".repeat(64),
        },
      },
      "run-1",
    );
    expect(parsed.status).toBe("unavailable");
    expect(parsed.reasonCode).toBe("DATA_CONSUMER_PROJECTION_DIGEST_INVALID");
  });

  it("rejects facts that are not the server-owned identity contract", () => {
    const parsed = readDataConsumerReportEvidence(
      {
        ...available,
        facts: [{ ...available.facts[0], source_node_id: "../../raw" }],
      },
      "run-1",
    );
    expect(parsed.status).toBe("unavailable");
    expect(parsed.reasonCode).toBe("DATA_CONSUMER_FACT_INVALID");
  });

  it("renders status, receipt identity, and lineage without raw payload values", () => {
    render(<DataConsumerReportEvidence evidence={available} expectedRunId="run-1" />);
    expect(screen.getByTestId("report-data-consumer-evidence")).toHaveTextContent("AVAILABLE");
    expect(screen.getByTestId("report-data-consumer-evidence")).toHaveTextContent("run-1");
    expect(screen.getByTestId("report-data-consumer-evidence")).toHaveTextContent("node-1");
    expect(screen.getByTestId("report-data-consumer-evidence")).not.toHaveTextContent("DO_NOT_RENDER");
  });
});
