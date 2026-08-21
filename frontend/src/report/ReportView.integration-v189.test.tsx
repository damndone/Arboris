import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportClassificationEvidenceMount, readTypedClassificationProjection } from "./ReportView";

const projection = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
  status: "validated",
  consumer: "report",
  provider_id: "workbench.classification_ml",
  exposure_path: "workbench.classification_ml.direct",
  policy_ref: {
    kind: "policy",
    logical_id: "workbench.classification_ml.policy",
    semantic_version: "1.0",
    contract_digest: "7".repeat(64),
  },
  catalog_digest: "f59d0cc8c5746f7e8905fa6ff79e31465b11614284bcb9849d1545bfb271c952",
  provider_digest: "f2cd959aae60720574e4687940d562b20ac2ad7afc14d58af423f7a9e9a2b43c",
  coverage_status: "required",
  projection_ref: {
    kind: "projection",
    logical_id: "workbench.classification_ml.report",
    semantic_version: "1.0",
    contract_digest: "5".repeat(64),
  },
  renderer_ref: {
    kind: "renderer",
    logical_id: "workbench.classification_ml.report",
    semantic_version: "1.0",
    contract_digest: "6".repeat(64),
  },
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 3, yes: 2 } },
  split: { profile: "sealed_holdout", split_hash: "sha256:split" },
  metrics: { accuracy: { point_estimate: 0.8, status: "computed", sample_scope: "holdout" } },
  calibration: { status: "descriptive" },
  baselines: [],
  controls: [],
  comparison: { selected_model: "logistic_regression" },
  explanations: { status: "available" },
  stability: { status: "descriptive" },
  shift: { status: "descriptive" },
  blocked_reasons: [],
  decision_policy: { selection_status: "SCENARIOS_ONLY", holdout: "sealed" },
  evidence_refs: { holdout: "classification-holdout:1" },
  holdout: { status: "sealed" },
  c0_evidence_envelope: { availability: "available" },
  c0_consumer_projection: { payload: { projection_status: "available" } },
  foundation_status: {
    execution_status: "completed",
    availability: "available",
    completeness_status: "complete",
    producer_status: "validated",
  },
} as const;

const evidence = {
  payload_schema: "workbench.prediction.classification-artifacts-wrapper",
  schema_version: 1,
  status: "validated",
  consumer: "report",
  artifact_id: "artifact:central-classification",
  artifact_sha256: "a".repeat(64),
  receipt_digest: "b".repeat(64),
  server_identity: { project_id: "project:1", run_id: "run-1" },
  projection,
  source: { artifact_id: "artifact:central-classification" },
  receipt: {
    payload_schema: "workbench.prediction.classification-consumer-receipt",
    schema_version: 1,
  },
} as const;

describe("v1.8.9 integrated typed Report acceptance", () => {
  it("accepts and renders only the typed evidence projection", () => {
    expect(readTypedClassificationProjection(evidence)).toMatchObject({
      status: "validated",
      consumer: "report",
      projection: expect.objectContaining({
        projection_ref: evidence.projection.projection_ref,
        renderer_ref: evidence.projection.renderer_ref,
      }),
    });
    render(<ReportClassificationEvidenceMount evidence={evidence} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("Binary classification");
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("VALIDATED");
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("logistic_regression");
  });

  it("renders an unavailable state instead of exposing an unknown payload", () => {
    render(<ReportClassificationEvidenceMount evidence={{ raw: { secret: "should-not-render" } }} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("secret");
  });
});
