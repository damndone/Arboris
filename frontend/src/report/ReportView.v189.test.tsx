import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportClassificationEvidenceMount, readTypedClassificationEvidence } from "./ReportView";

const taskHash = "sha256:" + "t".repeat(64);
const splitHash = "sha256:split";
const releasePlanHash = "sha256:" + "c".repeat(64);
const modelHash = "sha256:model";
const classificationResultRef = `classification-evidence:${taskHash}:${splitHash}:${releasePlanHash}`;
const classificationFacets = ["classification", "task", "split", "holdout", "release_plan"];
const classificationFamilyEvidence = {
  status: "validated",
  issuer: "workbench.server",
  producer: "workbench.prediction.run_classification_model_v189",
  method: { id: "classification-production-v1", version: "1.0" },
  identity: {
    result_ref: classificationResultRef,
    task_hash: taskHash,
    split_hash: splitHash,
    model_id: "logistic_regression",
    model_hash: modelHash,
    holdout_hash: releasePlanHash,
    release_plan_hash: releasePlanHash,
  },
};

const packet = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
  status: "validated",
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 3, yes: 2 }, task_hash: taskHash },
  split: { profile: "sealed_holdout", split_hash: splitHash },
  metrics: { accuracy: { point_estimate: 0.8, status: "computed", sample_scope: "holdout" } },
  calibration: { status: "descriptive" },
  baselines: [],
  controls: [],
  comparison: { selected_model: "logistic_regression", secret: "raw-secret" },
  explanations: { status: "available" },
  stability: { status: "descriptive" },
  shift: { status: "descriptive" },
  blocked_reasons: [],
  decision_policy: { selection_status: "SCENARIOS_ONLY", holdout: "sealed" },
  evidence_refs: {
    task: `classification-task:${taskHash}`,
    split: `classification-split:${splitHash}`,
    model: `classification-model:logistic_regression:${modelHash}`,
    holdout: `classification-holdout:${releasePlanHash}`,
    release_plan: `classification-release-plan:${releasePlanHash}`,
  },
  holdout: {
    status: "sealed",
    model_id: "logistic_regression",
    release_plan_hash: releasePlanHash,
    release_count: 0,
    release_plan: {
      plan_hash: releasePlanHash,
      task_hash: taskHash,
      split_hash: splitHash,
      model_id: "logistic_regression",
      model_hash: modelHash,
      calibration_hash: "sha256:calibration",
      policy_hash: "sha256:policy",
    },
  },
  c0_evidence_envelope: {
    result_identity: { result_ref: classificationResultRef, task_hash: taskHash, split_hash: splitHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash },
    execution_status: "completed",
    availability: "available",
    completeness_status: "complete",
    input_provenance: { task_hash: taskHash, split_hash: splitHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash },
    family_evidence: { classification: classificationFamilyEvidence },
  },
  c0_consumer_projection: {
    contract: "consumer-projection",
    contract_version: "1.0",
    producer_version: "1.8.9",
    payload: {
      projection_id: classificationResultRef,
      projection_ref: "classification-consumer:test",
      projection_status: "available",
      slots: ["agent", "notebook", "report"].map((consumer) => ({ consumer, artifact_facets: classificationFacets, payload_schema_ref: "workbench.prediction.classification-evidence", source_eligible: true })),
      not_applicable_projection: { status: "not_applicable", reason: "classification evidence is applicable to this result" },
    },
  },
  foundation_status: {
    execution_status: "completed",
    availability: "available",
    completeness_status: "complete",
    producer_status: "validated",
  },
} as const;

const persistedPacket = {
  payload_schema: "workbench.prediction.classification-artifacts",
  schema_version: 1,
  artifact_id: "sha256:" + "a".repeat(64),
  server_identity: {
    schema_version: 1,
    project_id: "project:test",
    run_id: "run:test",
    namespace: "workbench.prediction.classification-artifacts.v1",
    digest: "sha256:" + "b".repeat(64),
  },
  identity: {
    schema_version: 1,
    artifact_id: "sha256:" + "a".repeat(64),
    task_hash: taskHash,
    split_hash: splitHash,
    model_id: "logistic_regression",
    model_hash: modelHash,
    holdout_hash: releasePlanHash,
    release_plan_hash: releasePlanHash,
    server_identity: {
      schema_version: 1,
      project_id: "project:test",
      run_id: "run:test",
      namespace: "workbench.prediction.classification-artifacts.v1",
      digest: "sha256:" + "b".repeat(64),
    },
    parts: { task_hash: taskHash, split_hash: splitHash, model_hash: modelHash, evaluation_hash: "e", policy_hash: "p", server_identity_digest: "sha256:" + "b".repeat(64) },
    fit_digest: "sha256:" + "f".repeat(64),
    evaluation_digest: "sha256:" + "e".repeat(64),
  },
  models: {
    logistic_regression: {
      oof_metrics: {},
      holdout: {},
      preprocessing: {
        folds: [{
          fold: 0,
          training_row_refs: ["r1", "r2"],
          validation_row_refs: ["r3", "r4"],
          receipt: { schema_version: 1, split_hash: splitHash, fit_row_refs: ["r1", "r2"], class_support: { class_labels: ["no", "yes"], training: { no: 1, yes: 1 }, validation: { no: 1, yes: 1 } } },
        }],
      },
    },
  },
  fit: {
    schema_version: 1,
    digest: "sha256:" + "f".repeat(64),
    identity: { task_hash: taskHash, split_hash: splitHash, model_id: "logistic_regression", model_hash: modelHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash, server_identity: { schema_version: 1, project_id: "project:test", run_id: "run:test", namespace: "workbench.prediction.classification-artifacts.v1", digest: "sha256:" + "b".repeat(64) } },
    models: { logistic_regression: { fold_receipts: [{ fold: 0, training_row_refs: ["r1", "r2"], validation_row_refs: ["r3", "r4"], receipt: { schema_version: 1, split_hash: splitHash, fit_row_refs: ["r1", "r2"], class_support: { class_labels: ["no", "yes"], training: { no: 1, yes: 1 }, validation: { no: 1, yes: 1 } } } }] } },
  },
  evaluation: {
    schema_version: 1,
    digest: "sha256:" + "e".repeat(64),
    identity: { task_hash: taskHash, split_hash: splitHash, model_id: "logistic_regression", model_hash: modelHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash, server_identity: { schema_version: 1, project_id: "project:test", run_id: "run:test", namespace: "workbench.prediction.classification-artifacts.v1", digest: "sha256:" + "b".repeat(64) } },
    metrics: { oof: {}, holdout: {} },
    comparison: packet.comparison,
  },
  evidence: packet,
};

describe("ReportView v1.8.9 evidence mounts", () => {
  it("accepts only the typed classification evidence schema", () => {
    expect(readTypedClassificationEvidence(packet)).toBeNull();
    expect(readTypedClassificationEvidence(persistedPacket)).toEqual(persistedPacket);
    expect(readTypedClassificationEvidence({ metrics: { accuracy: 0.8 } })).toBeNull();
  });

  it("mounts the typed packet without recalculating or dumping unknown payloads", () => {
    render(<ReportClassificationEvidenceMount evidence={persistedPacket} />);

    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("Binary classification");
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("Accuracy");
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("SCENARIOS_ONLY");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("undefined");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("raw-secret");
  });

  it("discloses an unavailable or unsupported packet", () => {
    render(<ReportClassificationEvidenceMount evidence={{ artifact_id: "classification:bad", raw: { secret: "x" } }} />);

    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("secret");
  });
});
