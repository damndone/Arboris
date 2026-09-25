import { fireEvent, render, screen, within } from "@testing-library/react";
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

function sectionEvidence() {
  return {
    ...evidence,
    facts: [{ factId: "tiny:p", statisticId: "p_value", value: 1.25e-24 }],
    structuredResults: { schema_version: 1, contract_digest: "9ac17e068d3d718e6cb09a938e2d373db3c43d49b11ca6b7ac6df76897732ab6", sections: [1, 2].map((i) => ({
      section_id: `tests:${i}`, section_type: "statistical_tests", schema_version: 1,
      status: "available", reason_codes: [], fact_refs: ["tiny:p"], dependency_refs: ["source:1"],
      content: { kind: "object", fields: { results: { kind: "list", items: [{ kind: "object", fields: {
        p_value: { kind: "fact", fact_id: "tiny:p", representation: "number" },
        label: { kind: "text", value: "<img src=x onerror=alert(1)>" },
      } }] } } },
    })) },
    resolvedSections: [1, 2].map((i) => ({ sectionId: `tests:${i}`, sectionType: "statistical_tests", status: "available", reasonCodes: [],
      content: { results: [{ p_value: 1.25e-24, label: "<img src=x onerror=alert(1)>" }] } })),
  };
}

describe("FamilyEvidence structured sections", () => {
  it.each(["unavailable", "not_applicable"])("renders ARMA explicit %s without substituting a number", (status) => {
    const missing = { status, reason: "ARMA_SOURCE_MISSING" };
    const wire = {
      ...sectionEvidence(),
      structuredResults: { ...sectionEvidence().structuredResults, sections: [{
        section_id: "arma:1", section_type: "model_family_evidence", schema_version: 1,
        status: "available", reason_codes: [], fact_refs: ["tiny:p"], dependency_refs: ["source:1"],
        content: { kind: "object", fields: {
          model_family: { kind: "text", value: "time_series.arma_garch" },
          results: { kind: "object", fields: { model: { kind: "object", fields: { report: { kind: "object", fields: {
            metrics: { kind: "object", fields: { rmse: { kind: "missing", ...missing } } },
            diagnostics: { kind: "object", fields: { adf: { kind: "object", fields: {
              p_value: { kind: "fact", fact_id: "tiny:p", representation: "number" },
            } } } },
            warnings: { kind: "list", items: [{ kind: "text", value: "末行🧪" }] },
          } } } } } },
        } },
      }] },
      resolvedSections: [{ sectionId: "arma:1", sectionType: "model_family_evidence", status: "available", reasonCodes: [],
        content: { model_family: "time_series.arma_garch", results: { model: { report: {
          metrics: { rmse: missing }, diagnostics: { adf: { p_value: 1.25e-24 } }, warnings: ["末行🧪"],
        } } } } }],
    };
    const { rerender } = render(<FamilyEvidence evidence={wire as EvidenceViewModel} />);
    const details = screen.getByLabelText("model_family_evidence arma:1");
    expect(details).toHaveTextContent("ARMA_SOURCE_MISSING");
    expect(details).toHaveTextContent("1.25e-24");
    expect(details).toHaveTextContent("末行🧪");
    // Keep both trees in sync so this is an ARMA shape rejection.
    Object.assign(wire.structuredResults.sections[0].content.fields.results.fields.model.fields.report.fields,
      { undeclared: { kind: "text", value: "hidden-arma" } });
    Object.assign(wire.resolvedSections[0].content.results.model.report, { undeclared: "hidden-arma" });
    rerender(<FamilyEvidence evidence={wire as EvidenceViewModel} />);
    expect(screen.getByTestId("typed-evidence-unavailable")).toBeInTheDocument();
    expect(screen.queryByText("hidden-arma")).not.toBeInTheDocument();
  });

  it("renders each partition as accessible details without rounding or HTML execution", () => {
    const { container } = render(<FamilyEvidence evidence={sectionEvidence() as EvidenceViewModel} />);
    for (const id of ["tests:1", "tests:2"]) {
      const details = screen.getByLabelText(`statistical_tests ${id}`);
      expect(details.tagName).toBe("DETAILS");
      fireEvent.click(within(details).getByText(`statistical_tests · ${id} · AVAILABLE`));
      expect(details).toHaveAttribute("open");
      expect(within(details).getByText("1.25e-24")).toBeInTheDocument();
      expect(within(details).getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    }
    expect(container.querySelector("img, script")).toBeNull();
  });

  it("rejects mutated resolved statistics without rendering either facts or sections", () => {
    const wire = sectionEvidence(); wire.resolvedSections[0].content.results[0].p_value = 123456789;
    render(<FamilyEvidence evidence={wire as EvidenceViewModel} />);
    expect(screen.getByTestId("typed-evidence-unavailable")).toBeInTheDocument();
    expect(screen.queryByText("123456789")).not.toBeInTheDocument();
    expect(screen.queryByText("1.25e-24")).not.toBeInTheDocument();
  });

  it("shows explicit unavailable reasons in the section details", () => {
    const wire = { ...sectionEvidence(), structuredResults: { ...sectionEvidence().structuredResults, sections: [{
      section_id: "survey:1", section_type: "survey_design", schema_version: 1, status: "unavailable",
      reason_codes: ["SOURCE_MISSING"], fact_refs: [], dependency_refs: [], content: { kind: "null" },
    }] }, resolvedSections: [{ sectionId: "survey:1", sectionType: "survey_design", status: "unavailable", reasonCodes: ["SOURCE_MISSING"], content: null }] };
    render(<FamilyEvidence evidence={wire as EvidenceViewModel} />);
    const details = screen.getByLabelText("survey_design survey:1");
    fireEvent.click(within(details).getByText("survey_design · survey:1 · UNAVAILABLE"));
    expect(details).toHaveTextContent("SOURCE_MISSING");
  });
});
