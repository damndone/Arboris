import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { IVControls } from "./IVControls";

const cols = ["age", "educ", "dist", "momeduc"];

describe("IVControls", () => {
  it("fires onChange with endog/instruments when roles are assigned", () => {
    const onChange = vi.fn();
    render(<IVControls columns={cols} value={{ endog: [], instruments: [] }} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("role-educ"), { target: { value: "endog" } });
    expect(onChange).toHaveBeenLastCalledWith({ endog: ["educ"], instruments: [] });
  });

  it("reflects existing value as the column's role and never overlaps", () => {
    const onChange = vi.fn();
    render(<IVControls columns={cols} value={{ endog: ["educ"], instruments: ["dist"] }} onChange={onChange} />);
    expect((screen.getByLabelText("role-educ") as HTMLSelectElement).value).toBe("endog");
    expect((screen.getByLabelText("role-dist") as HTMLSelectElement).value).toBe("instrument");
    // moving educ to instrument removes it from endog
    fireEvent.change(screen.getByLabelText("role-educ"), { target: { value: "instrument" } });
    expect(onChange).toHaveBeenLastCalledWith({ endog: [], instruments: ["dist", "educ"] });
  });

  it("shows identification status", () => {
    const { rerender } = render(<IVControls columns={cols} value={{ endog: ["educ"], instruments: ["dist"] }} onChange={() => {}} />);
    expect(screen.getByText(/just-identified/i)).toBeInTheDocument();
    rerender(<IVControls columns={cols} value={{ endog: ["educ", "age"], instruments: ["dist"] }} onChange={() => {}} />);
    expect(screen.getByText(/Under-identified/i)).toBeInTheDocument();
    rerender(<IVControls columns={cols} value={{ endog: ["educ"], instruments: ["dist", "momeduc"] }} onChange={() => {}} />);
    expect(screen.getByText(/Over-identified/i)).toBeInTheDocument();
  });

  it("reassigning a column back to exog removes it from both buckets", () => {
    const onChange = vi.fn();
    render(<IVControls columns={cols} value={{ endog: ["educ"], instruments: ["dist"] }} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("role-educ"), { target: { value: "exog" } });
    expect(onChange).toHaveBeenLastCalledWith({ endog: [], instruments: ["dist"] });
  });

  it("shows the neutral hint when no endogenous variable is assigned", () => {
    render(<IVControls columns={cols} value={{ endog: [], instruments: [] }} onChange={() => {}} />);
    expect(screen.getByText(/Assign at least one endogenous variable/i)).toBeInTheDocument();
  });
});
