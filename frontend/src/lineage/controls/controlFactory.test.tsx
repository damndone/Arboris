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

  it("preserves visible_when (rendered, not hidden, day-1 not enforced)", () => {
    const control: EditableControl = {
      kind: "select", key: "covariance", label: "Covariance",
      options: ["robust"], value: "robust",
      visible_when: { model_type: "ols" },
    };
    render(<>{renderControl(control, vi.fn())}</>);
    expect(screen.getByRole("combobox")).toBeTruthy();
  });

  it("all 8 control kinds are enabled (v1.6.6: radio/slider/text/textarea/toggle made interactive)", () => {
    expect([...ENABLED_CONTROL_KINDS].sort()).toEqual([...CONTROL_KINDS].sort());
  });

  // ── v1.6.6: the 5 previously read-only controls are now interactive ──

  it("radio renders options and emits onChange with the picked value", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "radio", key: "method", label: "Method",
      options: ["twfe", "cs", "sa"], value: "twfe",
    };
    render(<>{renderControl(control, onChange)}</>);
    const cs = screen.getByLabelText("cs") as HTMLInputElement;
    expect(cs.checked).toBe(false);
    fireEvent.click(cs);
    expect(onChange).toHaveBeenCalledWith("method", "cs");
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

  it("slider reads min/max/step and emits a number", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "slider", key: "alpha", label: "Alpha",
      min: 0, max: 1, step: 0.05, value: 0.1, unit: "",
    };
    render(<>{renderControl(control, onChange)}</>);
    const range = screen.getByRole("slider") as HTMLInputElement;
    expect(range.value).toBe("0.1");
    expect(range.min).toBe("0");
    expect(range.max).toBe("1");
    expect(range.step).toBe("0.05");
    fireEvent.change(range, { target: { value: "0.25" } });
    expect(onChange).toHaveBeenCalledWith("alpha", 0.25);
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

  it("textarea emits the string value on change", () => {
    const onChange = vi.fn();
    const control: EditableControl = {
      kind: "textarea", key: "notes", label: "Notes", value: "a",
    };
    render(<>{renderControl(control, onChange)}</>);
    const area = screen.getByLabelText("Notes") as HTMLTextAreaElement;
    expect(area.value).toBe("a");
    fireEvent.change(area, { target: { value: "ab" } });
    expect(onChange).toHaveBeenCalledWith("notes", "ab");
  });
});
