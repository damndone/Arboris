import { render, screen } from "@testing-library/react";
import { createHash } from "node:crypto";
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

const serverIdentity = {
  schema_version: 1,
  project_id: "project:test",
  run_id: "run:test",
  namespace: "workbench.prediction.classification-artifacts.v1",
  digest: "sha256:" + "b".repeat(64),
};
const foldReceipt = {
  fold: 0,
  training_row_refs: ["r1", "r2"],
  validation_row_refs: ["r3", "r4"],
  receipt: {
    schema_version: 1,
    split_hash: splitHash,
    fit_row_refs: ["r1", "r2"],
    class_support: {
      class_labels: ["no", "yes"],
      training: { no: 1, yes: 1 },
      validation: { no: 1, yes: 1 },
    },
  },
};

function persistedClassificationArtifact(
  evidence: Record<string, unknown> = packet as unknown as Record<string, unknown>,
) {
  const comparison = evidence.comparison as { selected_model: string };
  const identity = {
    task_hash: taskHash,
    split_hash: splitHash,
    model_id: comparison.selected_model,
    model_hash: modelHash,
    holdout_hash: releasePlanHash,
    release_plan_hash: releasePlanHash,
    server_identity: serverIdentity,
  };
  const models = {
    [comparison.selected_model]: {
      oof_metrics: {},
      holdout: {},
      preprocessing: { folds: [foldReceipt] },
    },
  };
  return {
    payload_schema: "workbench.prediction.classification-artifacts",
    schema_version: 1,
    artifact_id: "sha256:" + "a".repeat(64),
    server_identity: serverIdentity,
    identity: {
      schema_version: 1,
      artifact_id: "sha256:" + "a".repeat(64),
      ...identity,
      parts: { task_hash: taskHash, split_hash: splitHash, model_hash: modelHash, evaluation_hash: "e", policy_hash: "p", server_identity_digest: serverIdentity.digest },
      fit_digest: "sha256:" + "f".repeat(64),
      evaluation_digest: "sha256:" + "e".repeat(64),
    },
    models,
    fit: { schema_version: 1, digest: "sha256:" + "f".repeat(64), identity, models: Object.fromEntries(Object.keys(models).map((modelId) => [modelId, { fold_receipts: [foldReceipt] }])) },
    evaluation: {
      schema_version: 1,
      digest: "sha256:" + "e".repeat(64),
      identity,
      metrics: { oof: {}, holdout: {} },
      comparison,
    },
    evidence,
  };
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

function digest(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function sharedClassificationArtifactsWrapper(
  artifact: Record<string, unknown> = persistedClassificationArtifact(),
) {
  const models = artifact.models as Record<string, Record<string, unknown>>;
  const fit = artifact.fit as Record<string, unknown>;
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
  const receiptWithDigest = { ...receipt, receipt_digest: receiptDigest };
  return {
    payload_schema: "workbench.prediction.classification-artifacts-wrapper",
    schema_version: 1,
    artifact_id: artifact.artifact_id,
    artifact_path: "classification_artifacts.json",
    artifact_sha256: "a".repeat(64),
    index: {
      artifact_id: artifact.artifact_id,
      path: "classification_artifacts.json",
      sha256: "a".repeat(64),
      receipt_path: "classification_receipt.json",
      receipt_sha256: "c".repeat(64),
      server_identity: serverIdentity,
    },
    artifact,
    receipt_path: "classification_receipt.json",
    receipt_sha256: "c".repeat(64),
    receipt: receiptWithDigest,
    receipt_digest: receiptDigest,
    content_digests: contentDigests,
    server_identity: serverIdentity,
  };
}

describe("ClassificationEvidence", () => {
  it("rejects a raw in-memory classification packet without the persisted wrapper", () => {
    render(<ClassificationEvidence evidence={packet as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("Binary classification");
  });

  it("renders typed classification evidence sections without recomputing statistics", () => {
    render(<ClassificationEvidence evidence={sharedClassificationArtifactsWrapper() as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Binary classification");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Class support");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Accuracy");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Calibration");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Baselines and controls");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Decision policy");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("SCENARIOS_ONLY");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent(`classification-holdout:${releasePlanHash}`);
  });

  it("rejects a complete raw persisted artifact when the shared server receipt wrapper is absent", () => {
    render(<ClassificationEvidence evidence={persistedClassificationArtifact() as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
  });

  it("rejects wrapper metrics tampering when the server receipt digest is stale", () => {
    const wrapper = sharedClassificationArtifactsWrapper();
    const artifact = wrapper.artifact as Record<string, unknown>;
    const tampered = {
      ...wrapper,
      artifact: {
        ...artifact,
        evidence: { ...(artifact.evidence as Record<string, unknown>), metrics: { forged: 1 } },
      },
    };

    render(<ClassificationEvidence evidence={tampered as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
  });

  it.each(["receipt identity", "receipt digest"]) ("rejects a mismatched %s", (kind) => {
    const wrapper = sharedClassificationArtifactsWrapper();
    const mismatched = kind === "receipt identity"
      ? {
        ...wrapper,
        receipt: { ...wrapper.receipt, artifact_id: "sha256:" + "d".repeat(64) },
      }
      : { ...wrapper, receipt_digest: "d".repeat(64) };

    render(<ClassificationEvidence evidence={mismatched as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
  });

  it("shows blocked reasons instead of rendering a synthetic metric", () => {
    render(<ClassificationEvidence evidence={sharedClassificationArtifactsWrapper({ ...persistedClassificationArtifact(), evidence: { ...packet, metrics: {}, blocked_reasons: ["CLASSIFICATION_INFORMATION_SET_INCOMPLETE"] } }) as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Blocked");
    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("CLASSIFICATION_INFORMATION_SET_INCOMPLETE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("0.00");
  });

  it("discloses an unavailable renderer when the C0 envelope is not typed", () => {
    render(<ClassificationEvidence evidence={sharedClassificationArtifactsWrapper({ ...persistedClassificationArtifact(), evidence: { ...packet, c0_evidence_envelope: {} } }) as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("Binary classification");
  });

  it.each(["issuer", "producer", "method", "identity"])("rejects forged classification family %s semantics", (field) => {
    const forgedFamily = { ...classificationFamilyEvidence, [field]: field === "identity" ? { ...classificationFamilyEvidence.identity, task_hash: "sha256:stale" } : "forged" };
    render(<ClassificationEvidence evidence={sharedClassificationArtifactsWrapper({ ...persistedClassificationArtifact(), evidence: { ...packet, c0_evidence_envelope: { ...packet.c0_evidence_envelope, family_evidence: { classification: forgedFamily } } } }) as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
  });

  it("accepts a persisted artifact only when its fold receipt contract is present", () => {
    const foldReceipt = {
      fold: 0,
      training_row_refs: ["r1", "r2", "r3", "r4"],
      validation_row_refs: ["r5", "r6"],
      receipt: {
        schema_version: 1,
        split_hash: splitHash,
        fit_row_refs: ["r1", "r2", "r3", "r4"],
        class_support: {
          class_labels: ["no", "yes"],
          training: { no: 2, yes: 2 },
          validation: { no: 1, yes: 1 },
        },
      },
    };
    const persisted = {
      payload_schema: "workbench.prediction.classification-artifacts",
      schema_version: 1,
      artifact_id: "sha256:" + "a".repeat(64),
      server_identity: serverIdentity,
      identity: {
        schema_version: 1,
        artifact_id: "sha256:" + "a".repeat(64),
        task_hash: taskHash,
        split_hash: splitHash,
        model_id: "random_forest",
        model_hash: modelHash,
        holdout_hash: releasePlanHash,
        release_plan_hash: releasePlanHash,
        server_identity: serverIdentity,
        parts: { task_hash: taskHash, split_hash: splitHash, model_hash: modelHash, evaluation_hash: "e", policy_hash: "p", server_identity_digest: serverIdentity.digest },
        fit_digest: "sha256:" + "f".repeat(64),
        evaluation_digest: "sha256:" + "e".repeat(64),
      },
      models: { random_forest: { oof_metrics: {}, holdout: {}, preprocessing: { folds: [foldReceipt] } } },
      fit: {
        schema_version: 1,
        digest: "sha256:" + "f".repeat(64),
        identity: { task_hash: taskHash, split_hash: splitHash, model_id: "random_forest", model_hash: modelHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash, server_identity: serverIdentity },
        models: {
          random_forest: {
            fold_receipts: [foldReceipt],
          },
        },
      },
      evaluation: {
        schema_version: 1,
        digest: "sha256:" + "e".repeat(64),
        identity: { task_hash: taskHash, split_hash: splitHash, model_id: "random_forest", model_hash: modelHash, holdout_hash: releasePlanHash, release_plan_hash: releasePlanHash, server_identity: serverIdentity },
        metrics: { oof: {}, holdout: {} },
        comparison: packet.comparison,
      },
      evidence: packet,
    };

    render(<ClassificationEvidence evidence={sharedClassificationArtifactsWrapper(persisted) as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("Binary classification");
  });

  it("does not render an in-memory packet when persisted fold receipts are missing", () => {
    const persisted = {
      payload_schema: "workbench.prediction.classification-artifacts",
      schema_version: 1,
      artifact_id: "sha256:" + "a".repeat(64),
      models: { random_forest: { preprocessing: { folds: [] } } },
      fit: { schema_version: 1, models: { random_forest: { fold_receipts: [] } } },
      evaluation: {},
      evidence: packet,
    };

    render(<ClassificationEvidence evidence={persisted as never} />);

    expect(screen.getByTestId("classification-evidence")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-evidence")).not.toHaveTextContent("Binary classification");
  });
});
