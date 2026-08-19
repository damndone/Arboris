import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportClassificationEvidenceMount, readTypedClassificationEvidence } from "./ReportView";

const packet = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
  status: "validated",
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 3, yes: 2 }, task_hash: "sha256:" + "t".repeat(64) },
  split: { profile: "sealed_holdout", split_hash: "sha256:split" },
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
    task: "classification-task:sha256:" + "t".repeat(64),
    split: "classification-split:sha256:split",
    holdout: "classification-holdout:sha256:" + "c".repeat(64),
    release_plan: "classification-release-plan:sha256:" + "c".repeat(64),
  },
  holdout: {
    status: "sealed",
    release_plan_hash: "sha256:" + "c".repeat(64),
    release_count: 0,
    release_plan: {
      plan_hash: "sha256:" + "c".repeat(64),
      task_hash: "sha256:" + "t".repeat(64),
      split_hash: "sha256:split",
      model_id: "logistic_regression",
      calibration_hash: "sha256:calibration",
      policy_hash: "sha256:policy",
    },
  },
  c0_evidence_envelope: {},
  c0_consumer_projection: {},
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
