import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportWorkspaceProvider, useReportWorkspace } from "./ReportWorkspaceContext";
import { reportProjectionDigest } from "./factTable";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockArtifacts = vi.hoisted(() => ({
  current: { groups: [] as Array<{ artifact_type: string; items: Array<Record<string, unknown>> }> },
}));
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
    fetchRunArtifacts: () => Promise.resolve(mockArtifacts.current),
    fetchArtifactJson: (...args: unknown[]) => mockArtifactJson.current(...args),
  };
});

const CLASSIFICATION_EVIDENCE_SCHEMA = "workbench.prediction.classification-evidence";

const evidencePacket = {
  payload_schema: CLASSIFICATION_EVIDENCE_SCHEMA,
  schema_version: 1,
  task: { task_type: "binary", positive_class: "yes", class_support: { no: 4, yes: 4 } },
  split: { profile: "iid_stratified", split_hash: "sha256:split" },
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
  evidence_refs: { holdout: "classification-holdout:1" },
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

function indexedClassificationItem(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    artifact_id: "classification_evidence",
    path: "classification/classification_evidence.json",
    artifact_type: "classification_evidence",
    step: "classification",
    sha256: "a".repeat(64),
    payload_contract: {
      payload_schema: CLASSIFICATION_EVIDENCE_SCHEMA,
      schema_version: 1,
    },
    payload_schema: CLASSIFICATION_EVIDENCE_SCHEMA,
    schema_version: 1,
    ...overrides,
  };
}

function WorkspaceProbe() {
  const workspace = useReportWorkspace();
  const packet = workspace.familyEvidenceArtifacts.classification_evidence;
  const isTypedPacket = Boolean(
    packet
    && typeof packet === "object"
    && (packet as Record<string, unknown>).payload_schema === CLASSIFICATION_EVIDENCE_SCHEMA
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
    </>
  );
}

function renderWorkspace() {
  return render(
    <ReportWorkspaceProvider projectRoot="/tmp/report-project">
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
    mockArtifactJson.current.mockReset();
    mockGenerateRequest.current = null;
    mockRunDetail.current = {
      model_results: [],
      post_estimation_results: [],
      prediction_evidence: null,
    };
  });

  it("loads only a server-indexed typed classification artifact", async () => {
    mockArtifacts.current = {
      groups: [{
        artifact_type: "classification_evidence",
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
    mockArtifactJson.current.mockResolvedValue(evidencePacket);

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("present"));
    expect(mockArtifactJson.current).toHaveBeenCalledWith(
      "/tmp/report-project",
      "run-classification",
      "classification_evidence",
    );
    expect(mockArtifactJson.current).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("classification-context")).toHaveTextContent(CLASSIFICATION_EVIDENCE_SCHEMA);
  });

  it("keeps the classification projection unavailable when no indexed artifact exists", async () => {
    renderWorkspace();

    await waitFor(() => expect(mockArtifactJson.current).not.toHaveBeenCalled());
    expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE");
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("secret");
  });

  it.each([
    ["malformed packet", { ...evidencePacket, metrics: "not-an-object", secret: "malformed-secret" }],
    ["unsupported schema version", { ...evidencePacket, schema_version: 2, secret: "unsupported-secret" }],
  ])("does not expose %s", async (_label, packet) => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_evidence", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue(packet);

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("secret");
  });

  it("treats a failed artifact download as unavailable without surfacing the error payload", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_evidence", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockRejectedValue(new Error("download-secret"));

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("download-secret");
  });

  it("keeps raw classification JSON display-only and out of selected facts and LLM context", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_evidence", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...evidencePacket,
      raw_classification_secret: "RAW_CLASSIFICATION_SECRET",
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
