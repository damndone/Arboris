import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportWorkspaceProvider, useReportWorkspace } from "./ReportWorkspaceContext";
import { reportProjectionDigest } from "./factTable";
import { createHash } from "node:crypto";
import { ApiError } from "../api";
import { readClassificationEvidencePacket } from "./ReportWorkspaceContext";

const CLASSIFICATION_ARTIFACTS_SCHEMA = "workbench.prediction.classification-artifacts";
const CLASSIFICATION_ARTIFACTS_WRAPPER_SCHEMA = "workbench.prediction.classification-artifacts-wrapper";
const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockArtifacts = vi.hoisted(() => ({
  current: { groups: [] as Array<{ artifact_type: string; items: Array<Record<string, unknown>> }> },
}));
const mockArtifactsError = vi.hoisted(() => ({ current: null as Error | null }));
const mockArtifactJson = vi.hoisted(() => ({ current: vi.fn() }));
const mockRunDetail = vi.hoisted(() => ({
  current: {
    model_results: [],
    post_estimation_results: [],
    prediction_evidence: null,
  } as Record<string, unknown>,
}));
const mockGenerateRequest = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("../workbench/ForestContext", () => ({
  useForest: () => mockForest.current,
}));

vi.mock("../workbench/WorkbenchStateProvider", () => ({
  useWorkbenchOptional: () => null,
}));

vi.mock("./reportClient", async (importOriginal) => {
  const original = await importOriginal<typeof import("./reportClient")>();
  return {
    ...original,
    fetchAiReports: () => Promise.resolve([]),
    generateReport: (request: unknown) => {
      mockGenerateRequest.current = request;
      return Promise.resolve({ text: "typed report", model: "test-model" });
    },
    saveAiReport: () => Promise.resolve({ record: undefined }),
  };
});

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    fetchRunDetail: () => Promise.resolve(mockRunDetail.current),
    fetchRunArtifacts: () => mockArtifactsError.current
      ? Promise.reject(mockArtifactsError.current)
      : Promise.resolve(mockArtifacts.current),
    fetchArtifactJson: (...args: unknown[]) => mockArtifactJson.current(...args),
  };
});

const CLASSIFICATION_EVIDENCE_SCHEMA = "workbench.prediction.classification-evidence";
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

const evidencePacket = {
  payload_schema: CLASSIFICATION_EVIDENCE_SCHEMA,
  schema_version: 1,
  status: "validated",
  task: {
    task_type: "binary",
    positive_class: "yes",
    class_support: { no: 4, yes: 4 },
    task_hash: taskHash,
  },
  split: { profile: "iid_stratified", split_hash: splitHash },
  metrics: { accuracy: { point_estimate: 0.75, validation_level: "validated" } },
  calibration: { status: "descriptive" },
  baselines: [{ model_id: "majority", accuracy: 0.5 }],
  controls: [{ control: "permuted_target", status: "computed" }],
  comparison: { selected_model: "logistic_regression" },
  explanations: { status: "available" },
  stability: { folds: 2 },
  shift: { status: "descriptive" },
  decision_policy: { selection_status: "SCENARIOS_ONLY" },
  blocked_reasons: [],
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
      slots: ["agent", "notebook", "report"].map((consumer) => ({ consumer, artifact_facets: classificationFacets, payload_schema_ref: CLASSIFICATION_EVIDENCE_SCHEMA, source_eligible: true })),
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

const typedReportEvidence = {
  schemaVersion: 1,
  projectionId: "report:commit-1",
  consumerId: "report",
  consumerVersion: "1.0",
  actorRef: "actor:1",
  projectRef: "project:1",
  sessionRef: "session:1",
  scopeRef: "scope:project:1",
  runId: "run-classification",
  modelRunId: "run-classification",
  artifactRef: "artifact-1",
  commitId: "commit-1",
  confirmationRef: "confirmation:run-classification",
  envelopeRef: "evidence-envelope:1",
  envelopeDigest: "a".repeat(64),
  status: "available",
  executionStatus: "completed",
  availability: "available",
  completenessStatus: "complete",
  validationStatus: "met",
  validationSummary: { requirement_status: "met" },
  facts: [{ factId: "fact-typed", statisticId: "typed-estimate", value: 7 }],
  sections: [],
  provenance: {
    artifactRef: "artifact-1",
    artifactType: "post_estimation",
    scopeRef: "scope:project:1",
    contentHash: "b".repeat(64),
    sourceRef: "source:run-classification",
    validatorRef: {
      kind: "validator",
      logical_id: "evidence.validator.v1",
      semantic_version: "1.0",
      contract_digest: "c".repeat(64),
    },
    executionRef: "execution:run-classification",
    contractDigest: "d".repeat(64),
    commitId: "commit-1",
    envelopeRef: "evidence-envelope:1",
    envelopeDigest: "a".repeat(64),
    lineageRefs: ["lineage:classification"],
    projectionRef: {
      kind: "projection",
      logical_id: "workbench.consumer_projection.report",
      semantic_version: "1.0",
      contract_digest: "e".repeat(64),
    },
    resultIdentity: {
      contract: "evidence-envelope",
      result_id: "result-1",
      schema_version: "1.0",
    },
  },
  projectionDigest: "",
} as Record<string, unknown>;
typedReportEvidence.projectionDigest = reportProjectionDigest(typedReportEvidence);
const typedReportEvidenceReceipt = {
  schemaVersion: 1,
  kind: "evidence.report.server-receipt.v1",
  projectionDigest: typedReportEvidence.projectionDigest,
  identity: {
    actorRef: typedReportEvidence.actorRef,
    projectRef: typedReportEvidence.projectRef,
    sessionRef: typedReportEvidence.sessionRef,
    scopeRef: typedReportEvidence.scopeRef,
    runId: typedReportEvidence.runId,
    modelRunId: typedReportEvidence.modelRunId,
    artifactRef: typedReportEvidence.artifactRef,
    commitId: typedReportEvidence.commitId,
    confirmationRef: typedReportEvidence.confirmationRef,
  },
  provenance: typedReportEvidence.provenance,
};

const persistedClassificationArtifact = {
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
          receipt: { schema_version: 1, split_hash: splitHash, fit_row_refs: ["r1", "r2"], class_support: { class_labels: ["no", "yes"], training: { no: 1, yes: 1 }, validation: { no: 1, yes: 1 } },
          },
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
    comparison: evidencePacket.comparison,
  },
  evidence: evidencePacket,
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
    payload_contract: { payload_schema: CLASSIFICATION_ARTIFACTS_SCHEMA, schema_version: 1 },
    server_identity: persistedClassificationArtifact.server_identity,
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
    index: { artifact_id: artifact.artifact_id, path: "classification_artifacts.json", artifact_type: "classification_artifacts", sha256: "a".repeat(64), receipt_path: "classification_receipt.json", receipt_sha256: "c".repeat(64), payload_contract: { payload_schema: CLASSIFICATION_ARTIFACTS_SCHEMA, schema_version: 1 }, server_identity: persistedClassificationArtifact.server_identity },
    artifact,
    receipt_path: "classification_receipt.json",
    receipt_sha256: "c".repeat(64),
    receipt: { ...receipt, receipt_digest: receiptDigest },
    receipt_digest: receiptDigest,
    content_digests: contentDigests,
    server_identity: persistedClassificationArtifact.server_identity,
  };
}

const persistedClassificationArtifactsWrapper = sharedClassificationArtifactsWrapper(persistedClassificationArtifact);

function indexedClassificationItem(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    artifact_id: "sha256:" + "a".repeat(64),
    path: "classification_artifacts.json",
    artifact_type: "classification_artifacts",
    step: "classification",
    sha256: "a".repeat(64),
    payload_contract: {
      payload_schema: CLASSIFICATION_ARTIFACTS_SCHEMA,
      schema_version: 1,
    },
    payload_schema: CLASSIFICATION_ARTIFACTS_SCHEMA,
    schema_version: 1,
    receipt_path: "classification_receipt.json",
    receipt_sha256: "c".repeat(64),
    server_identity: persistedClassificationArtifact.server_identity,
    ...overrides,
  };
}

function WorkspaceProbe() {
  const workspace = useReportWorkspace();
  const packet = workspace.familyEvidenceArtifacts.classification_evidence;
  const isTypedPacket = Boolean(
    packet
    && typeof packet === "object"
    && (packet as Record<string, unknown>).payload_schema === CLASSIFICATION_ARTIFACTS_WRAPPER_SCHEMA
    && (packet as Record<string, unknown>).schema_version === 1,
  );
  return (
    <>
      <output data-testid="classification-state">
        {isTypedPacket ? "present" : "UNAVAILABLE"}
      </output>
      <output data-testid="classification-context">
        {packet === undefined ? "" : JSON.stringify(packet)}
      </output>
      <output data-testid="report-selected-facts">
        {JSON.stringify(workspace.includedFacts)}
      </output>
      <output data-testid="report-llm-context">
        {workspace.reportContextDetails.join(" | ")}
      </output>
      <button type="button" data-testid="report-generate-probe" onClick={() => void workspace.generateReport()}>
        Generate probe
      </button>
      <output data-testid="artifact-inventory-error">{workspace.figureInventoryError ?? ""}</output>
    </>
  );
}

function renderWorkspace() {
  return render(
    <ReportWorkspaceProvider projectRoot="/private/tmp/report-project">
      <WorkspaceProbe />
    </ReportWorkspaceProvider>,
  );
}

describe("ReportWorkspaceContext v1.8.9 classification consumer", () => {
  beforeEach(() => {
    mockForest.current = {
      activeRunId: "run-classification",
      forest: { nodes: [], edges: [], heads: [] },
    };
    mockArtifacts.current = { groups: [] };
    mockArtifactsError.current = null;
    mockArtifactJson.current.mockReset();
    mockGenerateRequest.current = null;
    mockRunDetail.current = {
      model_results: [],
      post_estimation_results: [],
      prediction_evidence: null,
    };
  });

  it("requires an indexed artifact for classification provenance", () => {
    expect(readClassificationEvidencePacket(persistedClassificationArtifactsWrapper)).toBeNull();
  });

  it("accepts only the active project/run identity and rejects run:test fixtures", () => {
    expect(readClassificationEvidencePacket(
      persistedClassificationArtifactsWrapper,
      indexedClassificationItem(),
      { projectRoot: "/private/tmp/report-project", runId: "run-classification" },
    )).not.toBeNull();
    expect(readClassificationEvidencePacket(
      persistedClassificationArtifactsWrapper,
      indexedClassificationItem(),
      { projectRoot: "/private/tmp/report-project", runId: "run:test" },
    )).toBeNull();
  });

  it("rejects an indexed artifact whose receipt binding is stale", () => {
    expect(readClassificationEvidencePacket(
      persistedClassificationArtifactsWrapper,
      { ...persistedClassificationArtifactsWrapper.index, receipt_sha256: "d".repeat(64) },
    )).toBeNull();
  });

  it("loads only a server-indexed typed classification artifact", async () => {
    mockArtifacts.current = {
      groups: [{
        artifact_type: "classification_artifacts",
        items: [
          indexedClassificationItem(),
          indexedClassificationItem({
            artifact_id: "classification-looking-title",
            artifact_type: "figure",
            payload_contract: undefined,
            payload_schema: undefined,
            schema_version: undefined,
          }),
        ],
      }],
    };
    mockArtifactJson.current.mockResolvedValue(persistedClassificationArtifactsWrapper);

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("present"));
    expect(mockArtifactJson.current).toHaveBeenCalledWith(
      "/private/tmp/report-project",
      "run-classification",
      "sha256:" + "a".repeat(64),
    );
    expect(mockArtifactJson.current).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("classification-context")).toHaveTextContent(CLASSIFICATION_EVIDENCE_SCHEMA);
  });

  it("accepts a canonical formal_output inventory without blocking ReportWorkspace", async () => {
    mockArtifacts.current = {
      groups: [{
        artifact_type: "formal_output",
        items: [{
          artifact_id: "artifact:formal-output",
          path: "formal_output.json",
          artifact_type: "formal_output",
          step: "formal_output",
          sha256: "a".repeat(64),
        }],
      }],
    };

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("artifact-inventory-error")).toHaveTextContent(""));
    expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE");
    expect(mockArtifactJson.current).not.toHaveBeenCalled();
  });

  it("marks an indexed classification artifact unavailable when persisted fold receipts are missing", async () => {
    mockArtifacts.current = {
      groups: [{
        artifact_type: "classification_artifacts",
        items: [indexedClassificationItem({
          artifact_id: "sha256:" + "a".repeat(64),
          artifact_type: "classification_artifacts",
          payload_contract: { payload_schema: "workbench.prediction.classification-artifacts", schema_version: 1 },
          payload_schema: "workbench.prediction.classification-artifacts",
        })],
      }],
    };
    mockArtifactJson.current.mockResolvedValue({
      payload_schema: "workbench.prediction.classification-artifacts",
      schema_version: 1,
      artifact_id: "sha256:" + "a".repeat(64),
      models: { logistic_regression: { preprocessing: { folds: [] } } },
      fit: { schema_version: 1, models: { logistic_regression: { fold_receipts: [] } } },
      evaluation: {},
      evidence: evidencePacket,
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).toHaveTextContent("classification-evidence.unavailable");
  });

  it("keeps the classification projection unavailable when no indexed artifact exists", async () => {
    renderWorkspace();

    await waitFor(() => expect(mockArtifactJson.current).not.toHaveBeenCalled());
    expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("secret");
  });

  it.each([
    ["ARTIFACTS_INDEX_UNAVAILABLE", 503],
    ["ARTIFACTS_INDEX_INVALID", 500],
  ])("preserves a typed artifact-list failure and blocks Report continuation (%s)", async (code, status) => {
    mockArtifactsError.current = new ApiError(status, "server artifact inventory unavailable", code);

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("artifact-inventory-error")).toHaveTextContent(code));
    expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("secret");
  });

  it("does not continue when the backend rejects a forged artifact type", async () => {
    mockArtifactsError.current = new ApiError(
      500,
      "artifact inventory rejected forged_type",
      "ARTIFACTS_INDEX_INVALID",
      { artifact_type: "forged_type" },
    );

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("artifact-inventory-error")).toHaveTextContent("ARTIFACTS_INDEX_INVALID"));
    expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("forged_type");
  });

  it.each([
    ["malformed packet", { ...evidencePacket, metrics: "not-an-object", secret: "malformed-secret" }],
    ["unsupported schema version", { ...evidencePacket, schema_version: 2, secret: "unsupported-secret" }],
  ])("does not expose %s", async (_label, packet) => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_artifacts", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({ ...persistedClassificationArtifactsWrapper, artifact: { ...persistedClassificationArtifactsWrapper.artifact, evidence: packet } });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("secret");
  });

  it("rejects a stale C0 envelope identity instead of exposing the packet", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_artifacts", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...persistedClassificationArtifactsWrapper,
      artifact: { ...persistedClassificationArtifactsWrapper.artifact, evidence: {
        ...evidencePacket,
      c0_evidence_envelope: {
        result_identity: {
          result_ref: "classification-evidence:stale",
          task_hash: "sha256:stale",
          split_hash: evidencePacket.split.split_hash,
          holdout_hash: evidencePacket.holdout.release_plan_hash,
          release_plan_hash: evidencePacket.holdout.release_plan_hash,
        },
      },
      } },
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("sha256:stale");
  });

  it("rejects unavailable C0 evidence when the projection claims available", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_artifacts", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...persistedClassificationArtifactsWrapper,
      artifact: { ...persistedClassificationArtifactsWrapper.artifact, evidence: {
        ...evidencePacket,
      c0_evidence_envelope: { availability: "not_available" },
      c0_consumer_projection: { payload: { projection_status: "available" } },
      } },
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
  });

  it("rejects a forged classification family before ReportWorkspaceContext exposes it", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_artifacts", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...persistedClassificationArtifactsWrapper,
      artifact: { ...persistedClassificationArtifactsWrapper.artifact, evidence: {
        ...evidencePacket,
      c0_evidence_envelope: {
        ...evidencePacket.c0_evidence_envelope,
        family_evidence: { classification: { ...classificationFamilyEvidence, producer: "forged-producer" } },
      },
      } },
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("forged-producer");
  });

  it("treats a failed artifact download as unavailable without surfacing the error payload", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_artifacts", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockRejectedValue(new Error("download-secret"));

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("download-secret");
  });

  it("keeps raw classification JSON display-only and out of selected facts and LLM context", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_artifacts", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...persistedClassificationArtifactsWrapper,
      artifact: {
        ...persistedClassificationArtifactsWrapper.artifact,
        raw_classification_secret: "RAW_CLASSIFICATION_SECRET",
      },
    });
    mockRunDetail.current = {
      ...mockRunDetail.current,
      report_evidence: typedReportEvidence,
      report_evidence_receipt: typedReportEvidenceReceipt,
    };

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("present"));
    await waitFor(() => expect(screen.getByTestId("report-selected-facts")).toHaveTextContent("typed-estimate"));
    expect(screen.getByTestId("report-selected-facts")).not.toHaveTextContent("RAW_CLASSIFICATION_SECRET");
    expect(screen.getByTestId("report-llm-context")).toHaveTextContent(/typed-estimate/i);
    expect(screen.getByTestId("report-llm-context")).not.toHaveTextContent("RAW_CLASSIFICATION_SECRET");
    fireEvent.click(screen.getByTestId("report-generate-probe"));
    await waitFor(() => expect(mockGenerateRequest.current).not.toBeNull());
    expect(JSON.stringify(mockGenerateRequest.current)).toContain("typed-estimate");
    expect(JSON.stringify(mockGenerateRequest.current)).not.toContain("RAW_CLASSIFICATION_SECRET");
  });
});
