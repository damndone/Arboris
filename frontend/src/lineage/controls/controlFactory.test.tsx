import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { EditableControl } from "../api/graphViewTypes";
import {
  renderControl,
  CONTROL_REGISTRY,
  CONTROL_KINDS,
  ENABLED_CONTROL_KINDS,
} from "./controlFactory";

describe("controlFactory", () => {
  it("registry covers every EditableControl kind (no kind switch needed)", () => {
    for (const kind of CONTROL_KINDS) {
      expect(CONTROL_REGISTRY[kind]).toBeTypeOf("function");
    }
  });

  it("renders a select and emits onChange by key", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "select", key: "covariance", label: "Covariance",
      options: ["robust", "clustered", "unadjusted"], value: "robust",
    };
    render(<>{renderControl(control, onChange)}</>);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("robust");
    fireEvent.change(select, { target: { value: "unadjusted" } });
    expect(onChange).toHaveBeenCalledWith("covariance", "unadjusted");
  });

  it("renders a columns multi-picker and toggles values", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "columns", key: "x", label: "Covariates",
      options: ["age", "income"], value: ["age"],
    };
    render(<>{renderControl(control, onChange)}</>);
    const income = screen.getByLabelText("income") as HTMLInputElement;
    expect(income.checked).toBe(false);
    fireEvent.click(income);
    expect(onChange).toHaveBeenCalledWith("x", ["age", "income"]);
  });

  it("renders every kind with an identifiable control element", () => {
    for (const kind of CONTROL_KINDS) {
      const control = { kind, key: `k_${kind}`, label: kind } as EditableControl;
      const { unmount } = render(<>{renderControl(control, vi.fn())}</>);
      expect(screen.getByTestId(`control-${kind}`)).toBeTruthy();
      unmount();
    }
  });

  it("preserves visible_when (rendered, not hidden, day-1 not enforced)", () => {
    const control: EditableControl = {
      kind: "select", key: "covariance", label: "Covariance",
      options: ["robust"], value: "robust",
      visible_when: { model_type: "ols" },
    };
    render(<>{renderControl(control, vi.fn())}</>);
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("only select + columns are day-1 enabled", () => {
    expect([...ENABLED_CONTROL_KINDS].sort()).toEqual(["columns", "select"]);
  });
});
