import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ReportClassificationEvidenceMount,
  readTypedClassificationProjection,
} from "./ReportView";

const projectionRef = {
  kind: "projection",
  logical_id: "workbench.classification_ml.report",
  semantic_version: "1.0",
  contract_digest: "5".repeat(64),
};
const rendererRef = {
  kind: "renderer",
  logical_id: "workbench.classification_ml.report",
  semantic_version: "1.0",
  contract_digest: "6".repeat(64),
};
const policyRef = {
  kind: "policy",
  logical_id: "workbench.classification_ml.policy",
  semantic_version: "1.0",
  contract_digest: "7".repeat(64),
};
const providerIdentity = {
  provider_id: "workbench.classification_ml",
  exposure_path: "workbench.classification_ml.direct",
  policy_ref: policyRef,
  catalog_digest: "f59d0cc8c5746f7e8905fa6ff79e31465b11614284bcb9849d1545bfb271c952",
  provider_digest: "f2cd959aae60720574e4687940d562b20ac2ad7afc14d58af423f7a9e9a2b43c",
  coverage_status: "required",
};

const unavailableIdentity = {
  ...providerIdentity,
  projection_ref: projectionRef,
  renderer_ref: rendererRef,
};

function centralProjection(status: "validated" | "degraded" | "unavailable" = "validated") {
  return {
    payload_schema: "workbench.prediction.classification-evidence",
    schema_version: 1,
    status,
    consumer: "report",
    ...providerIdentity,
    projection_ref: projectionRef,
    renderer_ref: rendererRef,
    task: { task_type: "binary", positive_class: "yes", class_support: { no: 3, yes: 2 }, task_hash: "task-1" },
    split: { profile: "sealed_holdout", split_hash: "split-1" },
    metrics: { accuracy: { point_estimate: 0.8, status: "validated", sample_scope: "holdout" } },
    calibration: { status: "descriptive" },
    baselines: [],
    controls: [],
    comparison: { selected_model: "logistic_regression" },
    explanations: { status: "available" },
    stability: { status: "descriptive" },
    shift: { status: "descriptive" },
    decision_policy: { selection_status: "SCENARIOS_ONLY" },
    blocked_reasons: status === "degraded" ? ["provider coverage degraded"] : [],
    evidence_refs: { task: "task:1", split: "split:1", model: "model:1", holdout: "holdout:1", release_plan: "release:1" },
    holdout: { status: "sealed" },
    c0_evidence_envelope: { availability: status === "unavailable" ? "not_available" : "available" },
    c0_consumer_projection: { payload: { projection_status: status === "unavailable" ? "blocked" : "available" } },
    foundation_status: {
      execution_status: status === "unavailable" ? "blocked" : "completed",
      availability: status === "unavailable" ? "not_available" : "available",
      completeness_status: status === "validated" ? "complete" : status === "degraded" ? "degraded" : "insufficient",
      producer_status: status,
    },
  };
}

function centralWrapper(status: "validated" | "degraded" | "unavailable" = "validated") {
  return {
    payload_schema: "workbench.prediction.classification-artifacts-wrapper",
    schema_version: 1,
    status,
    consumer: "report",
    artifact_id: "artifact:classification:1",
    artifact_sha256: "a".repeat(64),
    receipt_digest: "b".repeat(64),
    server_identity: { run_id: "run-1", project_id: "project-1" },
    projection: centralProjection(status),
    source: { artifact_id: "artifact:classification:1", artifact_sha256: "a".repeat(64), receipt_digest: "c".repeat(64) },
    receipt: { payload_schema: "workbench.prediction.classification-consumer-receipt", schema_version: 1, receipt_digest: "b".repeat(64) },
    ...(status === "degraded" ? { reason: ["provider coverage degraded"] } : {}),
  };
}

function centralUnavailable(overrides: Record<string, unknown> = {}) {
  return {
    payload_schema: "workbench.prediction.classification-evidence.unavailable",
    schema_version: 1,
    status: "unavailable",
    consumer: "report",
    ...unavailableIdentity,
    reason: "CLASSIFICATION_EVIDENCE_UNAVAILABLE",
    ...overrides,
  };
}

describe("Workbench v1.8.9 central classification Report projection", () => {
  it("accepts the server-owned central Report projection through its typed parser", () => {
    expect(readTypedClassificationProjection(centralWrapper())).toMatchObject({
      status: "validated",
      consumer: "report",
      projection: { projection_ref: projectionRef, renderer_ref: rendererRef },
    });
  });

  it.each([
    ["unknown renderer", { renderer_ref: { ...rendererRef, logical_id: "attacker.raw" } }],
    ["mismatched projection", { projection_ref: { ...projectionRef, contract_digest: "9".repeat(64) } }],
  ])("rejects %s without rendering raw JSON", (_label, override) => {
    const value = centralWrapper();
    value.projection = { ...value.projection, ...override };
    (value.projection as Record<string, unknown>).raw_secret = "RAW_CLASSIFICATION_JSON";

    expect(readTypedClassificationProjection(value)).toBeNull();
    render(<ReportClassificationEvidenceMount evidence={value} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("RAW_CLASSIFICATION_JSON");
  });

  it.each([
    ["wrong provider", { provider_id: "attacker.provider" }],
    ["wrong exposure path", { exposure_path: "workbench.classification_ml.raw" }],
    ["wrong policy", { policy_ref: { ...policyRef, contract_digest: "8".repeat(64) } }],
    ["wrong catalog digest", { catalog_digest: "0".repeat(64) }],
    ["wrong provider digest", { provider_digest: "1".repeat(64) }],
    ["non-required coverage", { coverage_status: "exempt" }],
  ])("rejects %s identity without rendering raw JSON", (_label, override) => {
    const value = centralWrapper();
    value.projection = { ...value.projection, ...override };
    (value.projection as Record<string, unknown>).raw_secret = "RAW_CLASSIFICATION_JSON";

    expect(readTypedClassificationProjection(value)).toBeNull();
    render(<ReportClassificationEvidenceMount evidence={value} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("RAW_CLASSIFICATION_JSON");
  });

  it.each(["validated", "degraded", "unavailable"] as const)("keeps %s status and reason readable", (status) => {
    const value = centralWrapper(status);
    if (status === "unavailable") {
      value.projection.blocked_reasons = ["central projection unavailable"];
      value.reason = ["central projection unavailable"];
    }

    expect(readTypedClassificationProjection(value)).toMatchObject({ status });
    render(<ReportClassificationEvidenceMount evidence={value} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent(status.toUpperCase());
    if (status !== "validated") {
      expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent(
        status === "degraded" ? "provider coverage degraded" : "central projection unavailable",
      );
    }
  });

  it("rejects a bare unavailable payload instead of treating it as central evidence", () => {
    const value = {
      payload_schema: "workbench.prediction.classification-evidence.unavailable",
      schema_version: 1,
      status: "unavailable",
      consumer: "report",
      reason: "FORGED_REASON",
      raw_secret: "RAW_CLASSIFICATION_JSON",
    };

    expect(readTypedClassificationProjection(value)).toBeNull();
    render(<ReportClassificationEvidenceMount evidence={value} allowLegacyCompatibility={false} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("FORGED_REASON");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("RAW_CLASSIFICATION_JSON");
  });

  it.each([
    ["provider", { provider_id: "attacker.provider" }],
    ["path", { exposure_path: "workbench.classification_ml.raw" }],
    ["policy", { policy_ref: { ...policyRef, contract_digest: "8".repeat(64) } }],
    ["catalog", { catalog_digest: "0".repeat(64) }],
    ["coverage", { coverage_status: "exempt" }],
  ])("rejects forged unavailable %s identity", (_label, override) => {
    const value = centralUnavailable(override);

    expect(readTypedClassificationProjection(value)).toBeNull();
    render(<ReportClassificationEvidenceMount evidence={value} allowLegacyCompatibility={false} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("CLASSIFICATION_EVIDENCE_LOAD_FAILED");
  });

  it("accepts a fully server-bound unavailable payload and renders only its reason", () => {
    const value = centralUnavailable();

    expect(readTypedClassificationProjection(value)).toMatchObject({
      status: "unavailable",
      provider_id: providerIdentity.provider_id,
      projection_ref: projectionRef,
    });
    render(<ReportClassificationEvidenceMount evidence={value} allowLegacyCompatibility={false} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("CLASSIFICATION_EVIDENCE_UNAVAILABLE");
  });

  it("accepts only a fully server-bound unavailable projection", () => {
    const value = centralUnavailable();

    expect(readTypedClassificationProjection(value)).toMatchObject({
      payload_schema: "workbench.prediction.classification-evidence.unavailable",
      provider_id: providerIdentity.provider_id,
      exposure_path: providerIdentity.exposure_path,
      policy_ref: providerIdentity.policy_ref,
      catalog_digest: providerIdentity.catalog_digest,
      provider_digest: providerIdentity.provider_digest,
      projection_ref: projectionRef,
      renderer_ref: rendererRef,
      coverage_status: "required",
    });
  });

  it.each([
    ["missing provider identity", { provider_id: undefined }],
    ["forged policy", { policy_ref: { ...policyRef, contract_digest: "8".repeat(64) } }],
    ["forged projection ref", { projection_ref: { ...projectionRef, contract_digest: "9".repeat(64) } }],
    ["non-required coverage", { coverage_status: "exempt" }],
  ])("rejects %s unavailable identity without rendering raw JSON", (_label, override) => {
    const value = centralUnavailable(override);
    (value as Record<string, unknown>).raw_secret = "RAW_CLASSIFICATION_UNAVAILABLE_JSON";

    expect(readTypedClassificationProjection(value)).toBeNull();
    render(<ReportClassificationEvidenceMount evidence={value} allowLegacyCompatibility={false} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("RAW_CLASSIFICATION_UNAVAILABLE_JSON");
  });
});
