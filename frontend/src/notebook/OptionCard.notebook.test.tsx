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

  it("marks rank 1 as the recommended option and rank 2/3 as alternatives", () => {
    const { unmount } = render(<OptionCard option={option({ rank: 1 })} />);
    expect(screen.getByTestId("option-rank")).toHaveTextContent("rank 1 · recommended");
    expect(screen.getByTestId("option-card-opt_7f3a1c")).toHaveAttribute(
      "data-recommended",
      "true",
    );
    unmount();

    render(<OptionCard option={option({ rank: 2 })} />);
    expect(screen.getByTestId("option-rank")).toHaveTextContent("rank 2 · alternative");
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
    expect(screen.queryByTestId("option-blocked-reason")).toBeNull();
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
