import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FamilyEvidence } from "./FamilyEvidence";
import type { EvidenceViewModel } from "./reportEvidence";

const evidence: EvidenceViewModel = {
  projectionId: "projection:report:result-1",
  consumerId: "report",
  consumerVersion: "1.0",
  artifactRef: "artifact-1",
  envelopeRef: "evidence-envelope:result-1",
  envelopeDigest: "a".repeat(64),
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
});
