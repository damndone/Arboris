import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportWorkspaceProvider, useReportWorkspace } from "./ReportWorkspaceContext";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockArtifacts = vi.hoisted(() => ({
  current: { groups: [] as Array<{ artifact_type: string; items: Array<Record<string, unknown>> }> },
}));
const mockArtifactJson = vi.hoisted(() => ({ current: vi.fn() }));

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
  };
});

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    fetchRunDetail: () => Promise.resolve({
      model_results: [],
      post_estimation_results: [],
      prediction_evidence: null,
    }),
    fetchRunArtifacts: () => Promise.resolve(mockArtifacts.current),
    fetchArtifactJson: (...args: unknown[]) => mockArtifactJson.current(...args),
  };
});

const CLASSIFICATION_EVIDENCE_SCHEMA = "workbench.prediction.classification-evidence";
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

  it("rejects a stale C0 envelope identity instead of exposing the packet", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_evidence", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
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
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("sha256:stale");
  });

  it("rejects unavailable C0 evidence when the projection claims available", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_evidence", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...evidencePacket,
      c0_evidence_envelope: { availability: "not_available" },
      c0_consumer_projection: { payload: { projection_status: "available" } },
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
  });

  it("rejects a forged classification family before ReportWorkspaceContext exposes it", async () => {
    mockArtifacts.current = {
      groups: [{ artifact_type: "classification_evidence", items: [indexedClassificationItem()] }],
    };
    mockArtifactJson.current.mockResolvedValue({
      ...evidencePacket,
      c0_evidence_envelope: {
        ...evidencePacket.c0_evidence_envelope,
        family_evidence: { classification: { ...classificationFamilyEvidence, producer: "forged-producer" } },
      },
    });

    renderWorkspace();

    await waitFor(() => expect(screen.getByTestId("classification-state")).toHaveTextContent("UNAVAILABLE"));
    expect(screen.getByTestId("classification-context")).not.toHaveTextContent("forged-producer");
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
});
