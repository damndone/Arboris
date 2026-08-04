import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PredictionResearchReportSections } from "./PredictionResearchReportSections";


describe("PredictionResearchReportSections", () => {
  it("renders typed evidence in the four required report sections", () => {
    render(<PredictionResearchReportSections evidence={{
      status: "validated",
      model_id: "prediction_ridge_1",
      split_plan_hash: "sha256:split",
      split_parameters: { cv_folds: 3, final_holdout_fraction: 0.2 },
      development: { cv: [{ fold: 1 }, { fold: 2 }] },
      oos: { n: 4, metrics: { r2: 0.42, rmse: 1.25 } },
      controls: [{ control: "permuted_target" }],
      limits: ["final holdout is not sealed across reruns"],
    }} />);

    expect(screen.getByRole("region", { name: "Development evidence" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Final holdout evidence" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Negative-control evidence" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Known limitations" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Development evidence" })).toHaveTextContent("2 development fold record(s)");
    expect(screen.getByText("0.420")).toBeInTheDocument();
    expect(screen.getByText("permuted_target")).toBeInTheDocument();
  });

  it("keeps legacy report evidence readable but explicitly non-comparable", () => {
    render(<PredictionResearchReportSections evidence={{
      status: "legacy",
      protocol: "legacy_random_split_v0",
      validation: "payload_not_evaluated",
      comparability: "legacy_only",
      message: "Legacy evaluation — split protocol was not persisted. The result remains readable but is not comparable with v1.8.6 predictive-research results.",
    }} />);

    expect(screen.getByText(/Legacy evaluation — split protocol was not persisted/)).toBeInTheDocument();
    expect(screen.getByText("legacy_only")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Known limitations" })).toBeInTheDocument();
  });
});
