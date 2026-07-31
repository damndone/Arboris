import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OptionCard } from "./OptionCard";
import type { ArtifactContractOutcome, NotebookOptionRevision } from "./contracts";
import { canonicalOptionRevision } from "./fixtures/canonicalMocks";

function option(overrides: Partial<NotebookOptionRevision> = {}): NotebookOptionRevision {
  return { ...canonicalOptionRevision(), ...overrides };
}

describe("OptionCard — the canonical option, rendered as the packet states it", () => {
  it.each([
    ["low", "Low risk"],
    ["medium", "Medium risk"],
    ["high", "High risk"],
  ] as const)("exposes %s risk as text and a semantic styling hook", (risk, label) => {
    render(<OptionCard option={option({ risk_level: risk })} />);

    expect(screen.getByTestId("option-risk")).toHaveTextContent(label);
    expect(screen.getByTestId("option-risk")).toHaveAttribute("data-risk", risk);
  });

  it("renders the packet's own rationale, assumptions and pinned revisions", () => {
    render(<OptionCard option={option()} />);

    expect(screen.getByTestId("option-rationale")).toHaveTextContent(
      "The residual ACF from the ARMA fit still shows structure at lag 12",
    );
    expect(screen.getByTestId("option-assumptions")).toHaveTextContent(
      "the series is observed on a regular calendar",
    );
    expect(screen.getByTestId("option-assumptions")).toHaveTextContent(
      "no interior gaps after complete-case filtering",
    );
    expect(screen.getByTestId("option-pins")).toHaveTextContent("option opt_7f3a1c rev 2");
    expect(screen.getByTestId("option-pins")).toHaveTextContent("proposal prop_51de90 rev 1");
    expect(screen.getByTestId("option-pins")).toHaveTextContent("context ctx_9c21ab");
    expect(screen.getByTestId("option-pins")).toHaveTextContent("supersedes rev 1");
  });

  it("uses the batch decision instead of display rank for recommendation styling", () => {
    const v11 = (overrides: Partial<NotebookOptionRevision> = {}) =>
      option({
        contract_version: "1.1",
        lifecycle_projection: "proposed",
        materializable: true,
        evidence_refs: [],
        comparative_claims: [],
        recommendation_decision_id: "rec_1",
        recommendation_status: "recommended",
        ...overrides,
      });
    const { unmount } = render(<OptionCard option={v11({ rank: 2 })} />);
    expect(screen.getByTestId("option-rank")).toHaveTextContent("Recommended");
    expect(screen.getByTestId("option-card-opt_7f3a1c")).toHaveAttribute(
      "data-recommended",
      "true",
    );
    unmount();

    render(<OptionCard option={v11({ rank: 1, recommendation_status: "tied" })} />);
    expect(screen.getByTestId("option-rank")).toHaveTextContent("Near-equivalent candidates");
    expect(screen.getByTestId("option-card-opt_7f3a1c")).toHaveAttribute(
      "data-recommended",
      "false",
    );
  });

  it("does not use recommendation vocabulary for an Action-mode Draft", () => {
    const specified = option({
      contract_version: "1.1",
      lifecycle_projection: "proposed",
      materializable: true,
      evidence_refs: [],
      comparative_claims: [],
      recommendation_decision_id: "rec_3",
      recommendation_status: "recommended",
    });

    // Action mode returns one Draft built from what the user specified. Calling
    // it "Recommended" claims the agent preferred it over alternatives it was
    // never asked to weigh.
    const { unmount } = render(<OptionCard option={specified} interactionMode="action" />);
    expect(screen.getByTestId("option-rank")).toHaveTextContent(
      "Prepared from your specification",
    );
    expect(screen.getByTestId("option-rank")).not.toHaveTextContent("Recommended");
    expect(screen.getByTestId("option-card-opt_7f3a1c")).toHaveAttribute(
      "data-recommended",
      "false",
    );
    unmount();

    // Ineligibility belongs to the Draft, not to a ranking, so it survives.
    render(
      <OptionCard
        option={{ ...specified, validation_status: "invalid" }}
        interactionMode="action"
      />,
    );
    expect(screen.getByTestId("option-rank")).toHaveTextContent("Not eligible");
  });

  it("does not create a primary recommendation when evidence is insufficient", () => {
    render(
      <OptionCard
        option={option({
          contract_version: "1.1",
          lifecycle_projection: "proposed",
          materializable: true,
          evidence_refs: [],
          comparative_claims: [],
          recommendation_decision_id: "rec_2",
          recommendation_status: "insufficient_evidence",
        })}
      />,
    );
    expect(screen.getByTestId("option-rank")).toHaveTextContent("More evidence required");
    expect(screen.getByTestId("option-card-opt_7f3a1c")).toHaveAttribute(
      "data-recommended",
      "false",
    );
  });
});

describe("OptionCard — three orthogonal status axes stay three", () => {
  it("shows lifecycle, freshness and validation as separately named axes", () => {
    render(
      <OptionCard
        option={option({
          lifecycle_status: "deferred",
          freshness_status: "stale",
          validation_status: "valid",
        })}
      />,
    );

    expect(screen.getByTestId("option-axis-lifecycle")).toHaveTextContent("lifecycle deferred");
    expect(screen.getByTestId("option-axis-freshness")).toHaveTextContent("freshness stale");
    expect(screen.getByTestId("option-axis-validation")).toHaveTextContent("validation valid");
  });

  it("keeps validation=valid visible even while the option is stale (it was valid for the old context)", () => {
    render(
      <OptionCard
        option={option({ freshness_status: "stale", validation_status: "valid" })}
      />,
    );
    expect(screen.getByTestId("option-axis-validation")).toHaveTextContent("validation valid");
    expect(screen.getByTestId("option-axis-validation")).toHaveTextContent(
      "valid for the context it was generated against",
    );
  });
});

describe("OptionCard — a stale option is never directly executable", () => {
  it("disables execution and says revalidation is required", () => {
    render(<OptionCard option={option({ freshness_status: "stale" })} />);

    expect(screen.getByTestId("option-execute")).toBeDisabled();
    expect(screen.getByTestId("option-blocked-reason")).toHaveTextContent(
      "Upstream context changed — this option must be revalidated by the agent before it can run",
    );
    expect(screen.getByTestId("option-revalidate")).toBeEnabled();
  });

  it("does not offer execution while revalidating", () => {
    render(<OptionCard option={option({ freshness_status: "revalidating" })} />);
    expect(screen.getByTestId("option-execute")).toBeDisabled();
    expect(screen.getByTestId("option-blocked-reason")).toHaveTextContent(
      "Revalidating against the current context",
    );
  });

  it("blocks an invalid option even when it is fresh", () => {
    render(
      <OptionCard option={option({ freshness_status: "fresh", validation_status: "invalid" })} />,
    );
    expect(screen.getByTestId("option-execute")).toBeDisabled();
    expect(screen.getByTestId("option-blocked-reason")).toHaveTextContent(
      "The proposal validator rejected this option",
    );
  });

  it("allows execution only for a fresh, valid, proposed/selected option", () => {
    render(<OptionCard option={option()} />);
    expect(screen.getByTestId("option-execute")).toBeEnabled();
    expect(screen.getByTestId("option-execute")).toHaveTextContent("Review plan");
    expect(screen.queryByTestId("option-blocked-reason")).toBeNull();
  });

  it("keeps an executed option terminal even when the active head makes its old context stale", () => {
    render(
      <OptionCard
        option={option({ lifecycle_status: "executed", freshness_status: "stale" })}
      />,
    );

    expect(screen.getByTestId("option-execute")).toBeDisabled();
    expect(screen.getByTestId("option-blocked-reason")).toHaveTextContent(
      "This option has already been executed",
    );
    expect(screen.getByTestId("option-revalidate")).toBeDisabled();
  });
});

describe("OptionCard — required artifact expectations", () => {
  it("lists each expected artifact with its id, type, requirement, count and step", () => {
    render(<OptionCard option={option()} />);

    expect(screen.getByTestId("option-expected-ets_1")).toHaveTextContent(
      "ets_1 · model_result · required · count 1 · step estimation",
    );
    expect(screen.getByTestId("option-expected-ts_residual_acf")).toHaveTextContent(
      "ts_residual_acf · figure · optional · count 1 · step diagnostics",
    );
  });

  it("states which dimensions were checked and which were not evaluated", () => {
    render(<OptionCard option={option()} />);
    expect(screen.getByTestId("option-contract-dimensions")).toHaveTextContent(
      "Checked: artifact_id, artifact_type, count, step",
    );
    expect(screen.getByTestId("option-contract-dimensions")).toHaveTextContent(
      "Not checked: payload_schema",
    );
    expect(screen.getByTestId("option-contract-dimensions")).not.toHaveTextContent(
      "fully verified",
    );
  });

  it("reports the backend's contract outcome after execution without recomputing it", () => {
    const outcome: ArtifactContractOutcome = {
      execution_status: "succeeded",
      validation_status: "failed",
      validation_profile: "artifact-identity-type-count/v1",
      checked_dimensions: ["artifact_id", "artifact_type", "count", "step"],
      not_evaluated_dimensions: ["payload_schema"],
      observed: [
        { artifact_id: "ets_1", observed_count: 0, satisfied: false, issue_code: "ARTIFACT_MISSING" },
        { artifact_id: "ts_residual_acf", observed_count: 1, satisfied: true, issue_code: null },
      ],
    };

    render(<OptionCard option={option({ lifecycle_status: "selected" })} outcome={outcome} />);

    expect(screen.getByTestId("option-contract-outcome")).toHaveTextContent(
      "execution succeeded · output contract failed",
    );
    expect(screen.getByTestId("option-observed-ets_1")).toHaveTextContent(
      "ets_1 · expected 1 · observed 0 · not satisfied · ARTIFACT_MISSING",
    );
    expect(screen.getByTestId("option-observed-ts_residual_acf")).toHaveTextContent(
      "ts_residual_acf · expected 1 · observed 1 · satisfied",
    );
    expect(screen.getByTestId("option-contract-outcome")).not.toHaveTextContent("RUN_FAILED");
  });
});
