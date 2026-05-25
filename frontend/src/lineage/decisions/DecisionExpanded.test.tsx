import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DecisionExpanded } from "./DecisionExpanded";
import type { DecisionPoint } from "../types";

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

  it("does not render literal 'undefined' when reason is null", () => {
    // Registered DP with evidenceFields=['y_unique','y_dtype'] but
    // reason is null → params is {} → evidence values would be undefined.
    // Before the fix, the UI rendered "y_unique: undefined".
    const dpNoReason: DecisionPoint = {
      ...dp,
      reason: null,
    };
    const { container } = render(<DecisionExpanded dp={dpNoReason} />);
    expect(container.textContent ?? "").not.toMatch(/:\s*undefined/);
  });

  it("omits Evidence section entirely when no evidence values and no checks", () => {
    // assumption_checks_needed empty AND reason null → both inputs empty
    // → Evidence section gate (checks.length > 0 || evidence.length > 0)
    // should evaluate false and the heading should not render.
    const dpEmpty: DecisionPoint = {
      ...dp,
      contestability: { ...dp.contestability, assumption_checks_needed: [] },
      reason: null,
    };
    render(<DecisionExpanded dp={dpEmpty} />);
    expect(screen.queryByText(/^Evidence$/i)).toBeNull();
  });
});
