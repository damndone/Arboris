import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportClassificationEvidenceMount, readTypedClassificationEvidence } from "./ReportView";

const evidence = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
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
} as const;

describe("v1.8.9 integrated typed Report acceptance", () => {
  it("accepts and renders only the typed evidence projection", () => {
    expect(readTypedClassificationEvidence(evidence)).toEqual(evidence);
    render(<ReportClassificationEvidenceMount evidence={evidence} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("Binary classification");
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("SCENARIOS_ONLY");
  });

  it("renders an unavailable state instead of exposing an unknown payload", () => {
    render(<ReportClassificationEvidenceMount evidence={{ raw: { secret: "should-not-render" } }} />);
    expect(screen.getByTestId("report-classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("report-classification-evidence")).not.toHaveTextContent("secret");
  });
});

