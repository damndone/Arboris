import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  buildFigureFacts,
  buildPostEstimationFacts,
  buildReportEvidenceFacts,
  buildTimeSeriesFacts,
  reportProjectionDigest,
  sha256CanonicalV1,
  unavailableReportEvidence,
  type ReportEvidenceProjection,
  type ReportEvidenceServerReceipt,
} from "./factTable";
import { readReportEvidenceProjection } from "./factTable";
import { FamilyEvidence } from "./FamilyEvidence";
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
  readClassificationEvidencePacket: () => null,
}));

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
};

const dataConsumerFact = {
  fact_id: "data-operation:record-data",
  kind: "data_operation",
  operation_id: "data.subset",
  operation_version: "1.0",
  record_id: "record-data",
  execution_key: "execution-data",
  child_node_id: "child-data",
  artifact_ids: ["artifact-data"],
  evidence_digest: "d".repeat(64),
  catalog_digest: "b".repeat(64),
  run_id: "run-1",
  source_run_id: "run-1",
  source_node_id: "node-data",
  source_artifact_id: "artifact-data",
  data_snapshot_ref: "snapshot-data",
  data_snapshot_digest: "e".repeat(64),
};
const dataConsumerProjectionDigest = sha256CanonicalV1({
  schema_version: 1,
  payload_schema: "workbench.data.consumer-evidence.v1",
  scope_digest: "c".repeat(64),
  facts: [dataConsumerFact],
  catalog_digest: "b".repeat(64),
});

const surveyReportEvidence = {
  payload_schema: "workbench.survey.report-evidence.v1",
  schema_version: 1,
  provider_id: "workbench.survey",
  consumer: "report",
  status: "validated",
  authority: "server-owned",
  model_family: "ols",
  survey_design: { variance_method: "linearization" },
  source: {
    artifact_id: "ols-1",
    artifact_sha256: "d".repeat(64),
    receipt_digest: "e".repeat(64),
    server_identity: { run_id: "run-1", model_id: "ols-1" },
  },
  catalog: {
    digest: "1".repeat(64),
    provider_id: "workbench.survey",
    path_id: "workbench.survey.central_source",
    projection_ref: { kind: "projection", logical_id: "survey.report", semantic_version: "1.0", contract_digest: "2".repeat(64) },
    evidence_contract_refs: [{ kind: "evidence", logical_id: "survey.evidence", semantic_version: "1.0", contract_digest: "3".repeat(64) }],
    policy_ref: { kind: "policy", logical_id: "survey.policy", semantic_version: "1.0", contract_digest: "4".repeat(64) },
    renderer_ref: { kind: "renderer", logical_id: "survey.renderer", semantic_version: "1.0", contract_digest: "5".repeat(64) },
  },
  receipt: {
    schemaVersion: 1,
    kind: "evidence.survey.server-receipt.v1",
    projectionDigest: "",
    identity: {
      consumerId: "report",
      runId: "run-1",
      artifactId: "ols-1",
      artifactSha256: "d".repeat(64),
      sourceReceiptDigest: "e".repeat(64),
      catalogDigest: "1".repeat(64),
    },
  },
};
const { consumer: _surveyConsumer, receipt: _surveyReceipt, ...surveyReceiptPayload } = surveyReportEvidence;
surveyReportEvidence.receipt.projectionDigest = sha256CanonicalV1(surveyReceiptPayload);

const centralClassificationEvidence = {
  payload_schema: "workbench.prediction.classification-artifacts-wrapper",
  schema_version: 1,
  status: "validated",
  consumer: "report",
  artifact_id: "artifact:central-classification",
  artifact_sha256: "a".repeat(64),
  receipt_digest: "b".repeat(64),
  server_identity: { project_id: "project:1", run_id: "run-1" },
  projection: {
    payload_schema: "workbench.prediction.classification-evidence",
    schema_version: 1,
    status: "validated",
    consumer: "report",
    provider_id: "workbench.classification_ml",
    exposure_path: "workbench.classification_ml.direct",
    policy_ref: { kind: "policy", logical_id: "workbench.classification_ml.policy", semantic_version: "1.0", contract_digest: "7".repeat(64) },
    catalog_digest: "f59d0cc8c5746f7e8905fa6ff79e31465b11614284bcb9849d1545bfb271c952",
    provider_digest: "f2cd959aae60720574e4687940d562b20ac2ad7afc14d58af423f7a9e9a2b43c",
    coverage_status: "required",
    projection_ref: { kind: "projection", logical_id: "workbench.classification_ml.report", semantic_version: "1.0", contract_digest: "5".repeat(64) },
    renderer_ref: { kind: "renderer", logical_id: "workbench.classification_ml.report", semantic_version: "1.0", contract_digest: "6".repeat(64) },
    task: { task_type: "binary", positive_class: "yes", class_support: { no: 2, yes: 2 } },
    split: { profile: "sealed_holdout", split_hash: "split-1" },
    metrics: { accuracy: { point_estimate: 0.5, status: "validated" } },
    calibration: { status: "descriptive" },
    baselines: [],
    controls: [],
    comparison: { selected_model: "logistic_regression" },
    explanations: { status: "available" },
    stability: { status: "descriptive" },
    shift: { status: "descriptive" },
    decision_policy: { selection_status: "SCENARIOS_ONLY" },
    blocked_reasons: [],
    evidence_refs: { task: "task-1", split: "split-1", model: "model-1", holdout: "holdout-1", release_plan: "release-1" },
    holdout: { status: "sealed" },
    c0_evidence_envelope: { availability: "available" },
    c0_consumer_projection: { payload: { projection_status: "available" } },
    foundation_status: { execution_status: "completed", availability: "available", completeness_status: "complete", producer_status: "validated" },
  },
  source: { artifact_id: "artifact:central-classification" },
  receipt: { payload_schema: "workbench.prediction.classification-consumer-receipt", schema_version: 1 },
};

const committedProjection: ReportEvidenceProjection = {
  schemaVersion: 1,
  projectionId: "report:evidence-commit-1",
  consumerId: "report",
  consumerVersion: "1.0",
  rendererKey: "workbench.consumer_projection.report",
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
  projectionDigest: "",
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
    artifactType: "post_estimation",
    scopeRef: "scope:project:1",
    contentHash: "b".repeat(64),
    sourceRef: "source:run-1",
    validatorRef: {
      kind: "validator",
      logical_id: "evidence.validator.v1",
      semantic_version: "1.0",
      contract_digest: "c".repeat(64),
    },
    executionRef: "execution:run-1",
    contractDigest: "d".repeat(64),
    commitId: "evidence-commit-1",
    envelopeRef: "evidence-envelope:result-1",
    envelopeDigest: "a".repeat(64),
    lineageRefs: ["operation-1", "artifact-1"],
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
};

(committedProjection as unknown as Record<string, unknown>).projectionDigest = reportProjectionDigest(
  committedProjection as unknown as Record<string, unknown>,
);

const committedServerReceipt: ReportEvidenceServerReceipt = {
  schemaVersion: 1,
  kind: "evidence.report.server-receipt.v1",
  projectionDigest: committedProjection.projectionDigest,
  identity: {
    actorRef: committedProjection.actorRef,
    projectRef: committedProjection.projectRef,
    sessionRef: committedProjection.sessionRef,
    scopeRef: committedProjection.scopeRef,
    runId: committedProjection.runId,
    modelRunId: committedProjection.modelRunId,
    artifactRef: committedProjection.artifactRef,
    commitId: committedProjection.commitId,
    confirmationRef: committedProjection.confirmationRef,
  },
  provenance: committedProjection.provenance,
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
  it("accepts the server-owned run/model result identity emitted by the backend", () => {
    const serverProjection = {
      ...committedProjection,
      status: "degraded",
      completenessStatus: "degraded",
      validationStatus: "not_applicable",
      validationSummary: {
        levels_present: ["none"],
        minimum_required: "none",
        requirement_status: "not_applicable",
      },
      provenance: {
        ...committedProjection.provenance,
        resultIdentity: {
          result_ref: "result-1",
          run_id: "run-1",
          model_run_id: "run-1",
          schema_version: "1.0",
        },
      },
    } as unknown as Record<string, unknown>;
    serverProjection.projectionDigest = reportProjectionDigest(serverProjection);
    const serverReceipt = {
      ...committedServerReceipt,
      projectionDigest: serverProjection.projectionDigest,
      provenance: serverProjection.provenance,
    } as unknown as ReportEvidenceServerReceipt;

    const parsed = readReportEvidenceProjection(serverProjection, undefined, serverReceipt);
    expect(parsed).not.toBeNull();
    expect(parsed?.status).toBe("degraded");
    expect(parsed?.facts).toHaveLength(1);
    expect(buildReportEvidenceFacts(parsed)).toHaveLength(1);
  });

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
    }, committedServerReceipt)).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      schemaVersion: 1,
      status: "degraded",
      availability: "available",
      validationStatus: "met",
    }, undefined, committedServerReceipt)).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      schemaVersion: 1,
      status: "available",
      availability: "unavailable",
    }, undefined, committedServerReceipt)).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      provenance: { ...committedProjection.provenance, commitId: "commit-foreign" },
    }, undefined, committedServerReceipt)).toBeNull();
    expect(readReportEvidenceProjection({
      ...committedProjection,
      provenance: {
        ...committedProjection.provenance,
        resultIdentity: { runId: "run-foreign", modelRunId: "run-1" },
      },
    }, undefined, committedServerReceipt)).toBeNull();
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

  it("rejects a self-consistent-looking projection with a tampered digest", () => {
    expect(readReportEvidenceProjection({
      ...committedProjection,
      projectionDigest: "b".repeat(64),
    }, undefined, committedServerReceipt)).toBeNull();
  });

  it("rejects a caller-rehashed forged facts pair without a server receipt", () => {
    const forged = {
      ...committedProjection,
      facts: [{ factId: "fact-forged", statisticId: "sample-mean", value: 999 }],
      projectionDigest: "",
    } as Record<string, unknown>;
    forged.projectionDigest = reportProjectionDigest(forged);

    expect(readReportEvidenceProjection(forged, { runId: "run-1" })).toBeNull();
    expect(readReportEvidenceProjection(
      forged,
      { runId: "run-1" },
      committedServerReceipt,
    )).toBeNull();
  });

  it("rejects a self-consistent digest when canonical provenance is incomplete", () => {
    const incomplete = {
      ...committedProjection,
      provenance: { ...committedProjection.provenance },
    } as Record<string, unknown>;
    delete (incomplete.provenance as Record<string, unknown>).commitId;
    incomplete.projectionDigest = reportProjectionDigest(incomplete);
    expect(readReportEvidenceProjection(incomplete, undefined, committedServerReceipt)).toBeNull();
  });

  it("rejects a self-consistent digest when identity and provenance disagree", () => {
    const inconsistent = {
      ...committedProjection,
      provenance: { ...committedProjection.provenance, scopeRef: "scope:foreign" },
    } as Record<string, unknown>;
    inconsistent.projectionDigest = reportProjectionDigest(inconsistent);
    expect(readReportEvidenceProjection(inconsistent, undefined, committedServerReceipt)).toBeNull();
  });

  it("parses and renders validation independently from execution and availability", () => {
    const parsed = readReportEvidenceProjection(validatedProjection, undefined, committedServerReceipt);
    expect(parsed).toMatchObject({
      validationStatus: "met",
      validationSummary: expect.objectContaining({ requirement_status: "met" }),
      executionStatus: "completed",
      availability: "available",
      completenessStatus: "complete",
    });

    render(
      <FamilyEvidence
        evidence={validatedProjection}
      />,
    );

    expect(screen.getByTestId(`typed-evidence-${validatedProjection.projectionId}`)).toHaveTextContent("Validation");
    expect(screen.getByTestId(`typed-evidence-${validatedProjection.projectionId}`)).toHaveTextContent("MET");
  });

  it("accepts server-receipted degraded evidence with bounded facts", () => {
    const degradedProjectionCandidate = {
      ...committedProjection,
      status: "degraded",
      completenessStatus: "degraded",
      validationStatus: "not_applicable",
      validationSummary: {
        levels_present: ["none"],
        minimum_required: "none",
        requirement_status: "not_applicable",
      },
      projectionDigest: "",
    } as Record<string, unknown>;
    degradedProjectionCandidate.projectionDigest = reportProjectionDigest(
      degradedProjectionCandidate,
    );
    const degradedProjection = degradedProjectionCandidate as unknown as ReportEvidenceProjection;
    const degradedReceipt = {
      ...committedServerReceipt,
      projectionDigest: degradedProjection.projectionDigest,
    };

    const parsed = readReportEvidenceProjection(
      degradedProjection,
      { runId: "run-1" },
      degradedReceipt,
    );

    expect(parsed).toMatchObject({
      status: "degraded",
      availability: "available",
      executionStatus: "completed",
      completenessStatus: "degraded",
      validationStatus: "not_applicable",
    });
    expect(parsed?.facts).toHaveLength(1);
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
      predictionEvidence: {
        status: "validated",
        split_plan_hash: "split-plan-1",
        development: { cv: [] },
        oos: { n: 4, metrics: { r2: 0.91, rmse: 1.2 } },
        controls: [],
        limits: ["display-only compatibility evidence"],
      },
      modelResults: [rawRegressionResult],
      classificationEvidence: centralClassificationEvidence,
      familyEvidenceArtifacts: {
        raw: { leaked_scalar: 9.9 },
        classification_evidence: { raw_classification_secret: "RAW_CLASSIFICATION_SECRET" },
      },
      dataConsumerEvidence: {
        schema_version: 1,
        payload_schema: "workbench.data.consumer-evidence.v1",
        consumer_id: "report",
        status: "available",
        authority: "server-owned",
        run_id: "run-1",
        scope_digest: "c".repeat(64),
        projection_digest: dataConsumerProjectionDigest,
        catalog_digest: "b".repeat(64),
        source: "persisted-data-operation-output",
        availability: "available",
        execution_status: "completed",
        completeness_status: "complete",
        reason_code: null,
        facts: [dataConsumerFact],
        receipt: {
          schemaVersion: 1,
          kind: "evidence.data-consumer.server-receipt.v1",
          projectionDigest: dataConsumerProjectionDigest,
          identity: { consumerId: "report", runId: "run-1", scopeDigest: "c".repeat(64), catalogDigest: "b".repeat(64) },
        },
      },
      surveyEvidence: surveyReportEvidence,
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
    expect(screen.getByTestId("report-classification-evidence-central")).toHaveTextContent("central classification projection");
    expect(screen.getByTestId("report-data-consumer-evidence")).toHaveTextContent("AVAILABLE");
    expect(screen.getByTestId("report-data-consumer-lineage")).toHaveTextContent("node-data");
    expect(screen.getByTestId("report-survey-evidence")).toHaveTextContent("VALIDATED");
    expect(screen.getByTestId("report-survey-evidence")).toHaveTextContent("linearization");
    expect(screen.queryByText("RAW_CLASSIFICATION_SECRET")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
    expect(screen.queryByText("123.456")).not.toBeInTheDocument();
    expect(screen.getByTestId("report-prediction-evidence-non-citable")).toHaveTextContent(/non-citable/i);
  });

  it("does not use a legacy classification artifact when the central projection is absent", () => {
    const previousWorkspace = mockWorkspace.current as Record<string, unknown>;
    mockWorkspace.current = {
      ...previousWorkspace,
      classificationEvidence: undefined,
      familyEvidenceArtifacts: {
        classification_evidence: { raw_classification_secret: "RAW_CLASSIFICATION_SECRET" },
      },
    };

    render(<ReportViewContent />);

    expect(screen.queryByText("RAW_CLASSIFICATION_SECRET")).not.toBeInTheDocument();
    expect(screen.queryByTestId("report-classification-evidence")).not.toBeInTheDocument();
  });

  it("fail-closes every legacy raw fact helper instead of feeding the Report writer", () => {
    expect(buildFigureFacts([{
      artifact_id: "figure-raw",
      chart_type: "raw",
      source: { preview_json: JSON.stringify({ leaked_scalar: 9.9 }) },
    }])).toEqual([]);
    expect(buildPostEstimationFacts([{
      artifact_id: "post-raw",
      artifact_type: "post_estimation",
      operation_id: "model.quadratic_stationary_point",
      run_id: "run-1",
      model_run_id: "run-1",
      workflow_id: "workflow-1",
      workflow_step_id: "step-1",
      result: { stationary_point: 211.5 },
    }])).toEqual([]);
    expect(buildTimeSeriesFacts({
      "ts.final_model": { payload: { validation_fit: { rmse: 7.4 } } },
    })).toEqual([]);
  });
});
