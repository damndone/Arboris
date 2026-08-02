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
      controls: [
        { control: "permuted_target", status: "CONTROL_BEHAVED_AS_EXPECTED", metrics: { r2: -0.2, rmse: 4.1 } },
        { control: "seeded_noise_features", status: "NOISE_NOT_STABLE", metrics: { r2: 0.41, rmse: 1.3 } },
      ],
      limits: ["final holdout is not sealed across reruns"],
    }} />);
    expect(screen.getByText("grouped")).toBeInTheDocument();
    expect(screen.getByText("0.420")).toBeInTheDocument();
    expect(screen.getByText("2 receipt(s)")).toBeInTheDocument();
    expect(screen.getByText(/CONTROL_BEHAVED_AS_EXPECTED/)).toBeInTheDocument();
    expect(screen.getByText(/NOISE_NOT_STABLE/)).toBeInTheDocument();
    expect(screen.getByText(/final holdout is not sealed/i)).toBeInTheDocument();
  });

  it("does not present unavailable packets as model evidence", () => {
    render(<PredictionResearchEvidenceCard evidence={{ status: "unavailable" }} />);
    expect(screen.getByText(/failed contract validation/i)).toBeInTheDocument();
  });

  it("labels a readable historical result as legacy and not comparable", () => {
    render(<PredictionResearchEvidenceCard evidence={{
      status: "legacy",
      model_id: "prediction_ridge_1",
      protocol: "legacy_random_split_v0",
      validation: "payload_not_evaluated",
      comparability: "legacy_only",
      message: "Legacy evaluation — split protocol was not persisted. The result remains readable but is not comparable with v1.8.6 predictive-research results.",
      legacy_artifacts: [{
        model_id: "prediction_ridge_1",
        metrics: { test_r2: 0.31, test_rmse: 1.4 },
      }],
    }} />);

    expect(screen.getByText(/Legacy evaluation — split protocol was not persisted\./)).toBeInTheDocument();
    expect(screen.getByText("legacy_random_split_v0")).toBeInTheDocument();
    expect(screen.getByText("legacy_only")).toBeInTheDocument();
    expect(screen.queryByText(/Final OOS R²/)).not.toBeInTheDocument();
  });
});
