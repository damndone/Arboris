import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClassificationEvidence } from "./ClassificationEvidence";

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
    model_id: "random_forest",
    model_hash: modelHash,
    holdout_hash: releasePlanHash,
    release_plan_hash: releasePlanHash,
  },
};

const packet = {
  payload_schema: "workbench.prediction.classification-evidence",
  schema_version: 1,
  status: "validated",
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 4, yes: 4 }, task_hash: taskHash },
  split: { profile: "temporal_rolling", split_hash: splitHash },
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
    model_id: "random_forest",
    release_plan_hash: releasePlanHash,
    release_count: 0,
    release_plan: {
      plan_hash: releasePlanHash,
      task_hash: taskHash,
      split_hash: splitHash,
      model_id: "random_forest",
      model_hash: modelHash,
      calibration_hash: "sha256:calibration",
      policy_hash: "sha256:policy",
    },
  },
  evidence_refs: {
    task: `classification-task:${taskHash}`,
    split: `classification-split:${splitHash}`,
    model: `classification-model:random_forest:${modelHash}`,
    holdout: `classification-holdout:${releasePlanHash}`,
    release_plan: `classification-release-plan:${releasePlanHash}`,
  },
  c0_evidence_envelope: {
    result_identity: {
      result_ref: classificationResultRef,
      task_hash: taskHash,
      split_hash: splitHash,
      holdout_hash: releasePlanHash,
      release_plan_hash: releasePlanHash,
    },
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
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent(`classification-holdout:${releasePlanHash}`);
  });

  it("shows blocked reasons instead of rendering a synthetic metric", () => {
    render(<ClassificationEvidence evidence={{ ...packet, metrics: {}, blocked_reasons: ["CLASSIFICATION_INFORMATION_SET_INCOMPLETE"] }} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Blocked");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("CLASSIFICATION_INFORMATION_SET_INCOMPLETE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("0.00");
  });

  it("discloses an unavailable renderer when the C0 envelope is not typed", () => {
    render(<ClassificationEvidence evidence={{ ...packet, c0_evidence_envelope: {} }} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("Binary classification");
  });

  it.each(["issuer", "producer", "method", "identity"])("rejects forged classification family %s semantics", (field) => {
    const forgedFamily = { ...classificationFamilyEvidence, [field]: field === "identity" ? { ...classificationFamilyEvidence.identity, task_hash: "sha256:stale" } : "forged" };
    render(<ClassificationEvidence evidence={{ ...packet, c0_evidence_envelope: { ...packet.c0_evidence_envelope, family_evidence: { classification: forgedFamily } } }} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
  });
});
