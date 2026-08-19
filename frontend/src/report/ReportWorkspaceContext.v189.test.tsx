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
