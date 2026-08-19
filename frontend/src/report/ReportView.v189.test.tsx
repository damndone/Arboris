import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportClassificationEvidenceMount, readTypedClassificationEvidence } from "./ReportView";

const taskHash = "sha256:" + "t".repeat(64);
const splitHash = "sha256:split";
const releasePlanHash = "sha256:" + "c".repeat(64);
const modelHash = "sha256:model";
const classificationResultRef = `classification-evidence:${taskHash}:${splitHash}:${releasePlanHash}`;
const classificationFacets = ["classification", "task", "split", "holdout", "release_plan"];

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

describe("ReportView v1.8.9 evidence mounts", () => {
  it("accepts only the typed classification evidence schema", () => {
    expect(readTypedClassificationEvidence(packet)).toEqual(packet);
    expect(readTypedClassificationEvidence({ artifact_id: "classification:1", payload: packet })).toEqual(packet);
    expect(readTypedClassificationEvidence({ metrics: { accuracy: 0.8 } })).toBeNull();
  });

  it("mounts the typed packet without recalculating or dumping unknown payloads", () => {
    render(<ReportClassificationEvidenceMount evidence={packet} />);

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
