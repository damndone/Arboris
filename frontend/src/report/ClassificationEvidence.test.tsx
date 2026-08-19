import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClassificationEvidence } from "./ClassificationEvidence";

const packet = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 4, yes: 4 } },
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
  evidence_refs: { holdout: "holdout-1" },
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
