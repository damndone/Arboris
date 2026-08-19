import { createHash } from "node:crypto";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportClassificationEvidenceMount, readTypedClassificationEvidence } from "./ReportView";

const taskHash = "sha256:" + "t".repeat(64);
const splitHash = "sha256:split";
const releasePlanHash = "sha256:" + "c".repeat(64);
const modelHash = "sha256:model";
const classificationResultRef = `classification-evidence:${taskHash}:${splitHash}:${releasePlanHash}`;
const serverIdentity = {
  schema_version: 1,
  project_id: "project:sha256:2e976514ddb95c870f6a5cc39ad82b8680258acb017646e385c11137be58514c",
  run_id: "run-classification",
  namespace: "workbench.prediction.classification-artifacts.v1",
  digest: "sha256:320329e552523db557110a09c929a6314932bd072a889491345ea2006785a4f7",
};
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
  server_identity: serverIdentity,
  identity: {
    schema_version: 1,
    artifact_id: "sha256:" + "a".repeat(64),
    task_hash: taskHash,
    split_hash: splitHash,
    model_id: "logistic_regression",
    model_hash: modelHash,
    holdout_hash: releasePlanHash,
    release_plan_hash: releasePlanHash,
    server_identity: serverIdentity,
    parts: { task_hash: taskHash, split_hash: splitHash, model_hash: modelHash, evaluation_hash: "e", policy_hash: "p", server_identity_digest: serverIdentity.digest },
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
    identity: { task_hash: taskHash, split_hash: splitHash, model_id: "logistic_regression", model_hash: modelHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash, server_identity: serverIdentity },
    models: { logistic_regression: { fold_receipts: [{ fold: 0, training_row_refs: ["r1", "r2"], validation_row_refs: ["r3", "r4"], receipt: { schema_version: 1, split_hash: splitHash, fit_row_refs: ["r1", "r2"], class_support: { class_labels: ["no", "yes"], training: { no: 1, yes: 1 }, validation: { no: 1, yes: 1 } } } }] } },
  },
  evaluation: {
    schema_version: 1,
    digest: "sha256:" + "e".repeat(64),
    identity: { task_hash: taskHash, split_hash: splitHash, model_id: "logistic_regression", model_hash: modelHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash, server_identity: serverIdentity },
    metrics: { oof: {}, holdout: {} },
    comparison: packet.comparison,
  },
  evidence: packet,
};

function canonicalJson(value: unknown): string {
  if (value === undefined || value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return JSON.stringify(value === undefined ? null : value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

function digest(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function sharedClassificationArtifactsWrapper(artifact: Record<string, unknown>) {
  const models = artifact.models as Record<string, Record<string, unknown>>;
  const fit = artifact.fit as Record<string, unknown>;
  const serverIdentity = artifact.server_identity;
  const contentDigests = {
    artifact: "a".repeat(64),
    evidence: digest(artifact.evidence),
    "evidence.metrics": digest((artifact.evidence as Record<string, unknown>).metrics),
    evaluation: digest(artifact.evaluation),
    "evaluation.metrics": digest((artifact.evaluation as Record<string, unknown>).metrics),
    models: digest(models),
    "models.metadata": digest(Object.fromEntries(Object.entries(models).map(([modelId, model]) => [modelId, model.metadata ?? null]))),
    "models.warnings": digest(Object.fromEntries(Object.entries(models).map(([modelId, model]) => [modelId, (model.metadata as Record<string, unknown> | undefined)?.warnings ?? null]))),
    fit: digest(fit),
    fold_receipts: digest(Object.fromEntries(Object.entries((fit.models ?? {}) as Record<string, Record<string, unknown>>).map(([modelId, model]) => [modelId, model.fold_receipts ?? null]))),
  };
  const receipt = {
    payload_schema: "workbench.prediction.classification-receipt",
    schema_version: 1,
    receipt_id: "classification-receipt:test",
    artifact_path: "classification_artifacts.json",
    artifact_id: artifact.artifact_id,
    artifact_sha256: "a".repeat(64),
    payload_contract: { payload_schema: "workbench.prediction.classification-artifacts", schema_version: 1 },
    server_identity: serverIdentity,
    content_digests: contentDigests,
    issuer: "workbench.server.classification-persistence",
  };
  const receiptDigest = digest(receipt);
  return {
    payload_schema: "workbench.prediction.classification-artifacts-wrapper",
    schema_version: 1,
    artifact_id: artifact.artifact_id,
    artifact_path: "classification_artifacts.json",
    artifact_sha256: "a".repeat(64),
    index: { artifact_id: artifact.artifact_id, path: "classification_artifacts.json", artifact_type: "classification_artifacts", sha256: "a".repeat(64), receipt_path: "classification_receipt.json", receipt_sha256: "c".repeat(64), payload_contract: { payload_schema: "workbench.prediction.classification-artifacts", schema_version: 1 }, server_identity: serverIdentity },
    artifact,
    receipt_path: "classification_receipt.json",
    receipt_sha256: "c".repeat(64),
    receipt: { ...receipt, receipt_digest: receiptDigest },
    receipt_digest: receiptDigest,
    content_digests: contentDigests,
    server_identity: serverIdentity,
  };
}

const persistedWrapper = sharedClassificationArtifactsWrapper(persistedPacket);

describe("ReportView v1.8.9 evidence mounts", () => {
  it("accepts only the typed classification evidence schema", () => {
    expect(readTypedClassificationEvidence(packet)).toBeNull();
    expect(readTypedClassificationEvidence(persistedWrapper, persistedWrapper.index)).toEqual(persistedWrapper);
    expect(readTypedClassificationEvidence({ metrics: { accuracy: 0.8 } })).toBeNull();
  });

  it("binds the Report consumer to the active project/run identity", () => {
    expect(readTypedClassificationEvidence(
      persistedWrapper,
      persistedWrapper.index,
      { projectRoot: "/private/tmp/report-project", runId: "run-classification" },
    )).toEqual(persistedWrapper);
    expect(readTypedClassificationEvidence(
      persistedWrapper,
      persistedWrapper.index,
      { projectRoot: "/private/tmp/report-project", runId: "run:test" },
    )).toBeNull();
  });

  it("mounts the typed packet without recalculating or dumping unknown payloads", () => {
    render(<ReportClassificationEvidenceMount evidence={persistedWrapper} indexedArtifact={persistedWrapper.index} />);

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
