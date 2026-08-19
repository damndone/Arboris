import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  buildReportEvidenceFacts,
  unavailableReportEvidence,
  type ReportEvidenceProjection,
} from "./factTable";
import { readReportEvidenceProjection } from "./factTable";
import { FamilyEvidence, type FamilyModelResult } from "./FamilyEvidence";
import { ReportViewContent } from "./ReportView";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockWorkspace = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("../workbench/ForestContext", () => ({
  useForest: () => mockForest.current,
}));
vi.mock("../workbench/WorkbenchStateProvider", () => ({
  useWorkbenchOptional: () => null,
}));
vi.mock("./ReportWorkspaceContext", () => ({
  ReportWorkspaceProvider: ({ children }: { children: unknown }) => children,
  useReportWorkspace: () => mockWorkspace.current,
  useReportWorkspaceOptional: () => mockWorkspace.current,
}));

const rawFamilyResult = {
  model_id: "ordinal_logit_1",
  model_type: "ordinal_logit",
  odds_ratios: { leaked_scalar: 9.9 },
} as unknown as FamilyModelResult;

const rawRegressionResult = {
  model_id: "raw_ols_1",
  model_type: "ols",
  coefficients: {
    leaked_term: {
      estimate: 123.456,
      std_error: 0.1,
      p_value: 0.01,
      ci_lower: 123.2,
      ci_upper: 123.7,
    },
  },
} as unknown as FamilyModelResult;

const committedProjection: ReportEvidenceProjection = {
  schemaVersion: 1,
  projectionId: "report:evidence-commit-1",
  consumerId: "report",
  consumerVersion: "1.0",
  actorRef: "actor:1",
  projectRef: "project:1",
  sessionRef: "session:1",
  scopeRef: "scope:project:1",
  runId: "run-1",
  modelRunId: "run-1",
  confirmationRef: "confirmation:run-1",
  artifactRef: "artifact-1",
  envelopeRef: "evidence-envelope:result-1",
  commitId: "evidence-commit-1",
  envelopeDigest: "a".repeat(64),
  status: "available",
  executionStatus: "completed",
  availability: "available",
  completenessStatus: "complete",
  validationStatus: "met",
  validationSummary: {
    levels_present: ["same_library_regression", "independent_implementation"],
    minimum_required: "same_library_regression",
    requirement_status: "met",
  },
  facts: [{ factId: "fact-mean", statisticId: "sample-mean", value: 2, unit: "outcome-unit" }],
  sections: [],
  provenance: {
    artifactRef: "artifact-1",
    commitId: "evidence-commit-1",
    envelopeRef: "evidence-envelope:result-1",
    lineageRefs: ["operation-1", "artifact-1"],
  },
};

const validatedProjection = {
  ...committedProjection,
  validationStatus: "met",
  validationSummary: {
    levels_present: ["same_library_regression", "independent_implementation"],
    minimum_required: "same_library_regression",
    requirement_status: "met",
  },
} as ReportEvidenceProjection;

describe("Report evidence boundary v1.8.9", () => {
  it("rejects malformed, stale, and identity-inconsistent projections before rendering facts", () => {
    expect(readReportEvidenceProjection({ ...committedProjection, schemaVersion: 2 })).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      schemaVersion: 1,
      projectRef: "project:foreign",
      sessionRef: "session:foreign",
      scopeRef: "scope:foreign",
      runId: "run-foreign",
      modelRunId: "model-foreign",
      artifactRef: "artifact-foreign",
      commitId: "commit-foreign",
      status: "available",
    }, {
      projectRef: "project:1",
      sessionRef: "session:1",
      scopeRef: "scope:project:1",
      runId: "run-1",
      modelRunId: "run-1",
      artifactRef: "artifact-1",
      commitId: "evidence-commit-1",
    })).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      schemaVersion: 1,
      status: "degraded",
      availability: "available",
      validationStatus: "met",
    })).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      schemaVersion: 1,
      status: "available",
      availability: "unavailable",
    })).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      provenance: { ...committedProjection.provenance, commitId: "commit-foreign" },
    })).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      provenance: {
        ...committedProjection.provenance,
        resultIdentity: { runId: "run-foreign", modelRunId: "run-1" },
      },
    })).toBeNull();
  });

  it("does not make an indexed uncommitted result citable", () => {
    const unavailable = unavailableReportEvidence(
      "EVIDENCE_COMMIT_BINDING_REQUIRED",
      "workflow_model_quadratic_stationary_point_1",
    );
    const rawResult = {
      artifact_id: "workflow_model_quadratic_stationary_point_1",
      result: { stationary_point: 211.59338521178753, nested: { secret_scalar: 99 } },
    };

    expect(buildReportEvidenceFacts(unavailable)).toEqual([]);
    render(
      <FamilyEvidence
        modelResults={[rawFamilyResult]}
        artifacts={{ raw: { leaked_scalar: 9.9 } }}
        evidence={unavailable}
      />,
    );

    const projection = screen.getByTestId(`typed-evidence-${unavailable.projectionId}`);
    expect(projection).toHaveTextContent("UNAVAILABLE");
    expect(projection).toHaveTextContent("EVIDENCE_COMMIT_BINDING_REQUIRED");
    expect(projection).not.toHaveTextContent("211.59338521178753");
    expect(projection).not.toHaveTextContent("secret_scalar");
    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
    void rawResult;
  });

  it("does not render raw family packets when the typed report boundary is omitted", () => {
    render(
      <FamilyEvidence
        modelResults={[rawFamilyResult]}
        artifacts={{ raw: { leaked_scalar: 9.9 } }}
      />,
    );

    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
    expect(screen.queryByText(/leaked_scalar/i)).not.toBeInTheDocument();
  });

  it("renders only bounded committed projection facts with digest and provenance", () => {
    const facts = buildReportEvidenceFacts(committedProjection);
    expect(facts).toHaveLength(1);
    expect(facts[0]).toMatchObject({
      value: 2,
      artifact_ids: ["artifact-1"],
      qualifiers: expect.objectContaining({ commit_id: "evidence-commit-1" }),
    });

    render(
      <FamilyEvidence
        modelResults={[rawFamilyResult]}
        artifacts={{ raw: { leaked_scalar: 9.9 } }}
        evidence={committedProjection}
      />,
    );

    const projection = screen.getByTestId(`typed-evidence-${committedProjection.projectionId}`);
    expect(projection).toHaveTextContent("AVAILABLE");
    expect(projection).toHaveTextContent("a".repeat(64));
    expect(projection).toHaveTextContent("operation-1");
    expect(projection).toHaveTextContent("2");
    expect(projection).not.toHaveTextContent("9.9");
    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
  });

  it("parses and renders validation independently from execution and availability", () => {
    const parsed = readReportEvidenceProjection(validatedProjection);
    expect(parsed).toMatchObject({
      validationStatus: "met",
      validationSummary: expect.objectContaining({ requirement_status: "met" }),
      executionStatus: "completed",
      availability: "available",
      completenessStatus: "complete",
    });

    render(
      <FamilyEvidence
        modelResults={[rawFamilyResult]}
        evidence={validatedProjection}
      />,
    );

    expect(screen.getByTestId(`typed-evidence-${validatedProjection.projectionId}`)).toHaveTextContent("Validation");
    expect(screen.getByTestId(`typed-evidence-${validatedProjection.projectionId}`)).toHaveTextContent("MET");
  });

  it("wires the real ReportView path to the typed FamilyEvidence projection", () => {
    mockForest.current = {
      activeRunId: "run-1",
      forest: { heads: [], nodes: [] },
      setActiveRunId: vi.fn(),
    };
    mockWorkspace.current = {
      activeRunId: "run-1",
      table: { scope: { run_id: "run-1", node_count: 0, node_keys: [] }, facts: [], fingerprints: [] },
      current: null,
      currentIsStale: false,
      currentQualityStatus: undefined,
      excludedFactIds: [],
      excludedFigureIds: [],
      allFacts: [],
      includedFacts: [],
      includedFigures: [],
      reportFigures: [],
      reportContextLines: [],
      reportContextDetails: [],
      reportContextUsedTokens: 1,
      instruction: "",
      revisionInstruction: "",
      editing: false,
      error: null,
      figureContextLoading: false,
      figureInventoryError: null,
      generating: false,
      exporting: false,
      resultTableExporting: false,
      postEstimationLoadError: null,
      predictionEvidence: null,
      modelResults: [rawRegressionResult, rawFamilyResult],
      familyEvidenceArtifacts: { raw: { leaked_scalar: 9.9 } },
      reportEvidenceProjection: committedProjection,
      reportExportAllowed: true,
      history: [],
      beginEditing: vi.fn(),
      deleteReport: vi.fn(),
      exportReport: vi.fn(),
      exportResultTable: vi.fn(),
      generateReport: vi.fn(),
      includeAllFigures: vi.fn(),
      onInstructionChange: vi.fn(),
      onRevisionInstructionChange: vi.fn(),
      openReport: vi.fn(),
      reviseReport: vi.fn(),
      startNewReport: vi.fn(),
      toggleFact: vi.fn(),
      toggleFigure: vi.fn(),
      useRecommendedFigures: vi.fn(),
    };

    render(<ReportViewContent />);

    expect(screen.getByTestId(`typed-evidence-${committedProjection.projectionId}`)).toHaveTextContent("AVAILABLE");
    expect(screen.getByTestId("typed-evidence-provenance")).toHaveTextContent("operation-1");
    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
    expect(screen.queryByText("123.456")).not.toBeInTheDocument();
  });
});
