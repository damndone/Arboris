import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClassificationEvidence } from "./ClassificationEvidence";

const packet = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
  status: "validated",
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 4, yes: 4 }, task_hash: "sha256:" + "t".repeat(64) },
  split: { profile: "temporal_rolling", split_hash: "sha256:split" },
  metrics: { accuracy: { point_estimate: 0.75 }, log_loss: { point_estimate: 0.4 } },
  calibration: { status: "descriptive", brier: 0.19 },
  baselines: [{ model_id: "majority", accuracy: 0.5 }],
  controls: [{ control: "permuted_target", status: "computed" }],
  comparison: { selected_model: "random_forest", same_split: true },
  explanations: { permutation_importance: [{ feature: "balance", importance: 0.2 }] },
  stability: { folds: 3 },
  shift: { status: "descriptive" },
  decision_policy: { selection_status: "SCENARIOS_ONLY", holdout: "sealed" },
  blocked_reasons: [],
  holdout: {
    status: "sealed",
    release_plan_hash: "sha256:" + "c".repeat(64),
    release_count: 0,
    release_plan: {
      plan_hash: "sha256:" + "c".repeat(64),
      task_hash: "sha256:" + "t".repeat(64),
      split_hash: "sha256:split",
      model_id: "random_forest",
      calibration_hash: "sha256:calibration",
      policy_hash: "sha256:policy",
    },
  },
  evidence_refs: {
    task: "classification-task:sha256:" + "t".repeat(64),
    split: "classification-split:sha256:split",
    holdout: "holdout-1",
    release_plan: "classification-release-plan:sha256:" + "c".repeat(64),
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

describe("ClassificationEvidence", () => {
  it("renders typed classification evidence sections without recomputing statistics", () => {
    render(<ClassificationEvidence evidence={packet} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Binary classification");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Class support");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Accuracy");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Calibration");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Baselines and controls");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Decision policy");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("SCENARIOS_ONLY");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("holdout-1");
  });

  it("shows blocked reasons instead of rendering a synthetic metric", () => {
    render(<ClassificationEvidence evidence={{ ...packet, metrics: {}, blocked_reasons: ["CLASSIFICATION_INFORMATION_SET_INCOMPLETE"] }} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Blocked");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("CLASSIFICATION_INFORMATION_SET_INCOMPLETE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("0.00");
  });
});
