import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DecisionExpanded } from "./DecisionExpanded";
import type { DecisionPoint } from "./types";

const dp: DecisionPoint = {
  decision_id: "model_type_auto_select",
  decision_id_alias: [],
  selected: "continuous",
  candidates: ["ols", "logit", "poisson"],
  source: "data_driven_default",
  contestability: {
    is_contestable: true,
    assumption_checks_needed: ["variable_role_inference"],
    warnings: [],
    review_status: "needed",
  },
  reason: {
    reason_type: "data_driven_default",
    explanation: null,
    chosen_params_schema: null,
    chosen_params: { y_unique: 32, y_dtype: "float64" },
  },
};

describe("DecisionExpanded", () => {
  it("renders all 6 sections", () => {
    render(<DecisionExpanded dp={dp} />);
    expect(screen.getByText(/Selected choice/i)).toBeInTheDocument();
    expect(screen.getByText(/Why this was chosen/i)).toBeInTheDocument();
    expect(screen.getByText(/What to confirm/i)).toBeInTheDocument();
    expect(screen.getByText(/Alternatives/i)).toBeInTheDocument();
    expect(screen.getByText(/Evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Technical/i)).toBeInTheDocument();
    expect(screen.getByText("OLS")).toBeInTheDocument();
    expect(screen.getByText(/ID: model_type_auto_select/)).toBeInTheDocument();
  });
});
