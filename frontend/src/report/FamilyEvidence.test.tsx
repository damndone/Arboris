import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { toNotebookEvidenceContract } from "../notebook/evidenceContracts";
import { FamilyEvidence } from "./FamilyEvidence";
import type { EvidenceViewModel } from "./reportEvidence";

const evidence: EvidenceViewModel = {
  projectionId: "projection:report:result-1",
  consumerId: "report",
  consumerVersion: "1.0",
  artifactRef: "artifact-1",
  envelopeRef: "evidence-envelope:result-1",
  envelopeDigest: "a".repeat(64),
  rendererKey: "workbench.consumer_projection.report",
  status: "degraded",
  executionStatus: "completed",
  availability: "available",
  completenessStatus: "degraded",
  validationStatus: "met",
  validationSummary: { requirement_status: "met" },
  facts: [{ factId: "fact-mean", statisticId: "sample-mean", value: 2, unit: "outcome-unit" }],
  sections: [{ key: "missing-interval", label: "Confidence interval", status: "unavailable" }],
};

describe("FamilyEvidence", () => {
  it("returns an explicit unavailable state when typed evidence is absent", () => {
    render(<FamilyEvidence />);

    expect(screen.getByTestId("typed-evidence-unavailable")).toHaveTextContent("UNAVAILABLE");
    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
  });

  it("renders only the typed projection facts and status", () => {
    render(<FamilyEvidence evidence={evidence} />);

    const projection = screen.getByTestId("typed-evidence-projection:report:result-1");
    expect(projection).toHaveTextContent("DEGRADED");
    expect(projection).toHaveTextContent("2");
    expect(projection).toHaveTextContent("UNAVAILABLE");
  });

  it("fails closed for an unknown renderer instead of rendering untrusted facts", () => {
    const unknownRenderer = {
      ...evidence,
      rendererKey: "unknown.renderer.v1",
      facts: [{ ...evidence.facts[0], value: "untrusted-fact" }],
    } as EvidenceViewModel;

    render(<FamilyEvidence evidence={unknownRenderer} />);

    expect(screen.getByTestId("typed-evidence-unavailable")).toHaveTextContent("UNAVAILABLE");
    expect(screen.queryByText("untrusted-fact")).not.toBeInTheDocument();
  });

  it("fails closed when a persisted projection omits its renderer declaration", () => {
    const { rendererKey: _rendererKey, ...missingRenderer } = evidence;

    render(<FamilyEvidence evidence={missingRenderer as EvidenceViewModel} />);

    expect(screen.getByTestId("typed-evidence-unavailable")).toHaveTextContent("UNAVAILABLE");
  });

  it("renders persisted fact and projection provenance without recomputing it", () => {
    const richEvidence = {
      ...evidence,
      runId: "run-1",
      projectRef: "project-1",
      validationProvenance: { validatorRef: "validator:independent", level: "independent" },
      provenance: {
        lineageRefs: ["operation-1", "artifact-1"],
        resultIdentity: { contract: "evidence-envelope", result_id: "result-1", schema_version: "1.0" },
        validatorRef: "validator:independent",
      },
      facts: [{
        ...evidence.facts[0],
        interval: { lower: 1.5, upper: 2.5, method: "wald" },
        caveat: "bounded sample",
        availability: "available",
        validationProvenance: { level: "independent" },
      }],
    } as EvidenceViewModel;

    render(<FamilyEvidence evidence={richEvidence} />);

    expect(screen.getByTestId("typed-evidence-fact-fact-mean")).toHaveTextContent("1.5");
    expect(screen.getByTestId("typed-evidence-fact-fact-mean")).toHaveTextContent("2.5");
    expect(screen.getByTestId("typed-evidence-fact-fact-mean")).toHaveTextContent("bounded sample");
    expect(screen.getByTestId("typed-evidence-validation-provenance")).toHaveTextContent("validator:independent");
    expect(screen.getByTestId("typed-evidence-lineage")).toHaveTextContent("operation-1");
    expect(screen.getByTestId("typed-evidence-identity")).toHaveTextContent("result-1");
    expect(screen.getByTestId("typed-evidence-identity")).toHaveTextContent("run-1");
  });

  it("keeps the input data snapshot identity visible in the typed projection", () => {
    render(<FamilyEvidence evidence={{
      ...evidence,
      dataSnapshotRef: "dataset-1",
      dataSnapshotDigest: "b".repeat(64),
    } as EvidenceViewModel} />);

    expect(screen.getByTestId("typed-evidence-data-snapshot")).toHaveTextContent("dataset-1");
    expect(screen.getByTestId("typed-evidence-data-snapshot")).toHaveTextContent("b".repeat(64));
  });

  it("fails closed for a malformed data snapshot digest", () => {
    render(<FamilyEvidence evidence={{
      ...evidence,
      dataSnapshotRef: "dataset-1",
      dataSnapshotDigest: "not-a-digest",
    } as EvidenceViewModel} />);

    expect(screen.getByTestId("typed-evidence-unavailable")).toHaveTextContent("UNAVAILABLE");
  });

  it("rejects a report projection carrying a notebook contract", () => {
    render(<FamilyEvidence evidence={{
      ...evidence,
      contract: "workbench.notebook.evidence.v1",
    } as EvidenceViewModel} />);

    expect(screen.getByTestId("typed-evidence-unavailable")).toHaveTextContent("UNAVAILABLE");
    expect(screen.queryByText("2")).not.toBeInTheDocument();
  });

  it.each(["unavailable", "degraded", "blocked"] as const)(
    "exposes %s as a distinct projection status",
    (status) => {
      render(<FamilyEvidence evidence={{ ...evidence, status, facts: status === "degraded" ? evidence.facts : [] }} />);

      expect(screen.getByTestId(`typed-evidence-status-${status}`)).toHaveTextContent(status.toUpperCase());
    },
  );

  it("wraps the server notebook projection without dropping its evidence semantics", () => {
    const notebookEvidence = {
      ...evidence,
      consumerId: "notebook",
      rendererKey: "workbench.consumer_projection.notebook",
      validationProvenance: "validator:independent",
      lineageRefs: ["operation-1"],
      resultIdentity: { contract: "evidence-envelope", result_id: "result-1" },
      provenance: { lineageRefs: ["operation-1"], resultIdentity: { result_id: "result-1" } },
    } as EvidenceViewModel;

    const contract = toNotebookEvidenceContract(notebookEvidence);

    expect(contract).toMatchObject({
      contract: "workbench.notebook.evidence.v1",
      consumerId: "notebook",
      validationProvenance: "validator:independent",
      lineageRefs: ["operation-1"],
      resultIdentity: { result_id: "result-1" },
      provenance: notebookEvidence.provenance,
    });
    expect(contract?.facts).toEqual(notebookEvidence.facts);
    expect(toNotebookEvidenceContract({
      ...notebookEvidence,
      payload: { raw: "must-not-cross" },
    } as EvidenceViewModel)).toBeNull();
    expect(toNotebookEvidenceContract({ ...notebookEvidence, consumerId: "report" })).toBeNull();
  });
});
