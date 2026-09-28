import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClassificationEvidence } from "./ClassificationEvidence";

const packet = {
  status: "validated" as const,
  packet_id: "classification-packet-1",
  model_id: "rf-1",
  task: {
    target: "converted",
    class_mapping: { "0": "not_converted", "1": "converted" },
    positive_class: "1",
  },
  split: { profile: "iid_stratified", split_hash: "sha256:split" },
  evaluation: {
    metrics: {
      accuracy: { value: 0.8, source: "holdout-1" },
      roc_auc: { value: 0.84, source: "holdout-1" },
    },
    diagnostics: {
      status: "computed",
      plan_hash: "sha256:diagnostics-plan",
      shift: { status: "descriptive", features: [{ feature: "signal", mean_difference: 0.3 }] },
      subgroups: [{ column: "segment", value: "A", status: "computed" }],
    },
  },
  calibration: { status: "available", brier: { value: 0.16, source: "calibration-1" } },
  baselines: [{ baseline_id: "prevalence", metrics: { accuracy: 0.5 } }],
  controls: [{ control_id: "shuffle_target", status: "pass" }],
  comparison: { selection_status: "selected", comparison_id: "comparison-1" },
  explanations: { status: "available", permutation_importance: [{ feature: "age", value: 0.2 }] },
  decision_policy: { status: "frozen", threshold: 0.5, scope: "development_oof" },
  holdout_boundary: { status: "evaluated_once", access_count: 1 },
  warnings: ["Prediction explanations are descriptive, not causal."],
  evidence_receipt: { receipt_id: "receipt:1", source_artifacts: ["artifact:holdout-1"] },
};

describe("ClassificationEvidence", () => {
  it("renders packet-backed task, metrics, controls, policy, and receipt", () => {
    render(<ClassificationEvidence evidence={packet} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("converted");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("0.8");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("0.84");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("shuffle_target");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("development_oof");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("receipt:1");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("not causal");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("sha256:diagnostics-plan");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("segment");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("descriptive");
  });

  it("renders the formal point estimate without recalculating it", () => {
    render(
      <ClassificationEvidence
        evidence={{
          ...packet,
          evaluation: {
            metrics: {
              roc_auc: {
                point_estimate: 0.91,
                sample_scope: "final_holdout",
              },
            },
          },
        }}
      />,
    );

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("0.91");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("final_holdout");
  });

  it("shows unavailable instead of inventing classification values", () => {
    render(<ClassificationEvidence evidence={{ status: "unavailable", reason: "provider unavailable" }} />);

    expect(screen.getByTestId("classification-evidence-unavailable")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("classification-evidence-unavailable")).toHaveTextContent("provider unavailable");
    expect(screen.getByTestId("classification-evidence-unavailable")).not.toHaveTextContent("accuracy");
  });

  it("renders blocked reasons without treating them as metrics", () => {
    render(
      <ClassificationEvidence
        evidence={{ status: "blocked", blocked_reasons: ["availability could not be proven"] }}
      />,
    );

    expect(screen.getByTestId("classification-evidence-blocked")).toHaveTextContent("availability could not be proven");
    expect(screen.getByTestId("classification-evidence-blocked")).not.toHaveTextContent("ROC AUC");
  });
});
