import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PredictionResultCard, type PredictionResultData } from "./PredictionResultCard";

const data: PredictionResultData = {
  schema_version: 1, model_id: "prediction_ridge_1", model_type: "prediction_ridge",
  engine: "scikit-learn", status: "completed", nobs: 60,
  input_columns: { y: "y", x: ["x"] }, cv_folds: 3, sampling_method: null,
  metrics: { test_r2: 0.92, test_rmse: 1.1, cv_r2_mean: 0.9 },
  warnings: ["Prediction results are not causal effects and are not regression inference."],
};

describe("PredictionResultCard", () => {
  it("renders model type, metrics, and the non-causal warning", () => {
    render(<PredictionResultCard result={data} />);
    expect(screen.getByText(/prediction_ridge/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.92/)).toBeInTheDocument();
    expect(screen.getByText(/not causal/i)).toBeInTheDocument();
  });

  it("renders nothing when result is undefined", () => {
    const { container } = render(<PredictionResultCard result={undefined} />);
    expect(container.firstChild).toBeNull();
  });
});
