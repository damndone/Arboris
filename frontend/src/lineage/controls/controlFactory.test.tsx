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

  it("renders a compact scrollable checkbox grid", () => {
    const control: EditableControl = {
      kind: "columns", key: "x", label: "Covariates",
      options: ["age", "income", "region", "sales"], value: ["age"],
    };
    render(<>{renderControl(control, vi.fn())}</>);
    const list = screen.getByTestId("control-columns");
    expect(list).toHaveStyle("display: grid; max-height: 180px; overflow-y: auto;");
    expect(list.style.gridTemplateColumns).toContain("repeat(2");
    expect(screen.getByLabelText("income")).toHaveStyle(
      "width: 14px; height: 14px; min-height: 0;",
    );
  });

  it("renders every kind with an identifiable control element", () => {
    for (const kind of CONTROL_KINDS) {
      const control = { kind, key: `k_${kind}`, label: kind } as EditableControl;
      const { unmount } = render(<>{renderControl(control, vi.fn())}</>);
      expect(screen.getByTestId(`control-${kind}`)).toBeTruthy();
      unmount();
    }
  });

  it("edits select, multiselect, columns, text and toggle in place; shows the rest read-only", () => {
    expect([...ENABLED_CONTROL_KINDS].sort()).toEqual(["columns", "multiselect", "select", "text", "toggle"]);
    for (const kind of CONTROL_KINDS.filter((item) => !ENABLED_CONTROL_KINDS.has(item))) {
      const { unmount } = render(<>{renderControl({ kind, key: "k", label: "Tau", value: 0.5 }, vi.fn())}</>);
      const placeholder = screen.getByTestId(`control-${kind}`);
      expect(placeholder).toHaveAttribute("aria-disabled", "true");
      expect(placeholder).toHaveTextContent("Tau: 0.5");
      unmount();
    }
  });
  it("shows a structured read-only value without object coercion", () => {
    render(<>{renderControl({ kind: "json", key: "options", label: "Options", value: { fit_method: "reml" } }, vi.fn())}</>);
    expect(screen.getByTestId("control-json")).toHaveTextContent('Options: {"fit_method":"reml"}');
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });
  it("toggle reflects boolean value and flips it on click", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "toggle", key: "robust", label: "Robust SE", value: true,
    };
    render(<>{renderControl(control, onChange)}</>);
    const box = screen.getByRole("checkbox") as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(onChange).toHaveBeenCalledWith("robust", false);
  });

  it("text emits the string value on change", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "text", key: "title", label: "Title", value: "hi",
    };
    render(<>{renderControl(control, onChange)}</>);
    const input = screen.getByLabelText("Title") as HTMLInputElement;
    expect(input.value).toBe("hi");
    fireEvent.change(input, { target: { value: "hello" } });
    expect(onChange).toHaveBeenCalledWith("title", "hello");
  });
});
