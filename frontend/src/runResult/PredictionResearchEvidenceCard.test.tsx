import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PredictionResearchEvidenceCard } from "./PredictionResearchEvidenceCard";

describe("PredictionResearchEvidenceCard", () => {
  it("shows the validated structure, OOS baseline, and control receipts", () => {
    render(<PredictionResearchEvidenceCard evidence={{
      status: "validated",
      model_id: "prediction_ridge_1",
      structure: { kind: "grouped" },
      split_parameters: { random_seed: 7 },
      oos: { n: 4, metrics: { r2: 0.42, rmse: 1.25 } },
      baseline: { metrics: { r2: 0.10 } },
      controls: [{ control: "permuted_target" }, { control: "seeded_noise_features" }],
      limits: ["final holdout is not sealed across reruns"],
    }} />);
    expect(screen.getByText("grouped")).toBeInTheDocument();
    expect(screen.getByText("0.420")).toBeInTheDocument();
    expect(screen.getByText("2 receipt(s)")).toBeInTheDocument();
    expect(screen.getByText(/final holdout is not sealed/i)).toBeInTheDocument();
  });

  it("does not present unavailable packets as model evidence", () => {
    render(<PredictionResearchEvidenceCard evidence={{ status: "unavailable" }} />);
    expect(screen.getByText(/failed contract validation/i)).toBeInTheDocument();
  });
});
