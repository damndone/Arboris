import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DecisionCard } from "./DecisionCard";
import type { DecisionPoint } from "../types";

const baseDP: DecisionPoint = {
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

describe("DecisionCard", () => {
  it("renders user-friendly title from registry", () => {
    render(<DecisionCard dp={baseDP} expanded={false} onToggle={() => {}} />);
    expect(screen.getByText("Model type")).toBeInTheDocument();
  });

  it("shows displaySelected output", () => {
    render(<DecisionCard dp={baseDP} expanded={false} onToggle={() => {}} />);
    expect(screen.getByText(/Selected:/)).toBeInTheDocument();
    expect(screen.getByText("OLS")).toBeInTheDocument();
  });

  it("shows ⚠ icon when review_status=needed", () => {
    render(<DecisionCard dp={baseDP} expanded={false} onToggle={() => {}} />);
    expect(screen.getByText(/⚠/)).toBeInTheDocument();
  });

  it("omits ⚠ icon when review_status=not_needed", () => {
    const dp: DecisionPoint = {
      ...baseDP,
      contestability: { ...baseDP.contestability, review_status: "not_needed" },
    };
    const { container } = render(
      <DecisionCard dp={dp} expanded={false} onToggle={() => {}} />,
    );
    expect(container.querySelector('[data-testid="dp-warn-icon"]')).toBeNull();
  });

  it("calls onToggle when clicked", () => {
    const onToggle = vi.fn();
    render(<DecisionCard dp={baseDP} expanded={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalled();
  });
});
