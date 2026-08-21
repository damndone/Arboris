import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  SurveyReportEvidence,
  readSurveyReportEvidence,
} from "./SurveyReportEvidence";
import { sha256CanonicalV1 } from "./factTable";

const available = {
  payload_schema: "workbench.survey.report-evidence.v1",
  schema_version: 1,
  provider_id: "workbench.survey",
  consumer: "report",
  status: "validated",
  authority: "server-owned",
  model_family: "ols",
  survey_design: {
    projection_status: "validated",
    variance_method: "linearization",
    strata: "stratum",
    psu: "psu",
    weight: "weight",
  },
  source: {
    artifact_id: "ols_1",
    artifact_sha256: "a".repeat(64),
    receipt_digest: "b".repeat(64),
    server_identity: { run_id: "run-survey", model_id: "ols_1" },
  },
  catalog: {
    digest: "d".repeat(64),
    provider_id: "workbench.survey",
    path_id: "workbench.survey.central_source",
    projection_ref: {
      kind: "projection",
      logical_id: "workbench.survey.report",
      semantic_version: "1.0",
      contract_digest: "e".repeat(64),
    },
    evidence_contract_refs: [{
      kind: "evidence",
      logical_id: "workbench.survey.evidence",
      semantic_version: "1.0",
      contract_digest: "f".repeat(64),
    }],
    policy_ref: {
      kind: "policy",
      logical_id: "workbench.survey.policy",
      semantic_version: "1.0",
      contract_digest: "1".repeat(64),
    },
    renderer_ref: {
      kind: "renderer",
      logical_id: "workbench.survey.renderer",
      semantic_version: "1.0",
      contract_digest: "2".repeat(64),
    },
  },
  receipt: {
    schemaVersion: 1,
    kind: "evidence.survey.server-receipt.v1",
    projectionDigest: "c".repeat(64),
    identity: {
      consumerId: "report",
      runId: "run-survey",
      artifactId: "ols_1",
      artifactSha256: "a".repeat(64),
      sourceReceiptDigest: "b".repeat(64),
      catalogDigest: "d".repeat(64),
    },
  },
};

const { consumer: _consumer, receipt: _receipt, ...surveyReceiptPayload } = available;
(available.receipt as { projectionDigest: string }).projectionDigest = sha256CanonicalV1(
  surveyReceiptPayload,
);

describe("Report Survey evidence boundary", () => {
  it("accepts only the server-owned Survey projection", () => {
    expect(readSurveyReportEvidence(available, "run-survey")).toMatchObject({
      status: "validated",
      modelFamily: "ols",
      runId: "run-survey",
      artifactId: "ols_1",
      varianceMethod: "linearization",
    });
  });

  it("turns missing or raw-shaped Survey data into unavailable", () => {
    const parsed = readSurveyReportEvidence(
      { raw_survey_secret: "DO_NOT_RENDER" },
      "run-survey",
    );
    expect(parsed.status).toBe("unavailable");
    expect(parsed.reasonCode).toBe("SURVEY_EVIDENCE_SCHEMA_INVALID");
  });

  it("rejects a receipt that is not bound to the complete projection", () => {
    const parsed = readSurveyReportEvidence(
      {
        ...available,
        receipt: {
          ...available.receipt,
          projectionDigest: "3".repeat(64),
        },
      },
      "run-survey",
    );
    expect(parsed.status).toBe("unavailable");
    expect(parsed.reasonCode).toBe("SURVEY_EVIDENCE_PROJECTION_DIGEST_INVALID");
  });

  it("does not invent a model family when the producer omits it", () => {
    const missingFamily = { ...available } as Record<string, unknown>;
    delete missingFamily.model_family;
    const parsed = readSurveyReportEvidence(missingFamily, "run-survey");
    expect(parsed.status).toBe("unavailable");
    expect(parsed.reasonCode).toBe("SURVEY_EVIDENCE_RECEIPT_INVALID");
  });

  it("renders bounded design identity and no raw artifact JSON", () => {
    render(<SurveyReportEvidence evidence={available} expectedRunId="run-survey" />);
    expect(screen.getByTestId("report-survey-evidence")).toHaveTextContent("VALIDATED");
    expect(screen.getByTestId("report-survey-evidence")).toHaveTextContent("linearization");
    expect(screen.getByTestId("report-survey-evidence")).not.toHaveTextContent("DO_NOT_RENDER");
  });
});
