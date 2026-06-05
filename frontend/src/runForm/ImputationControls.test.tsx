import { expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ImputationControls } from "./ImputationControls";
import type { Capabilities } from "../capabilities/types";

const caps_one: Capabilities = {
  schema_version: 1,
  model_types: [],
  imputation_methods: [
    { key: "mice", label: "MICE (Multiple Imputation)" },
  ],
};

const caps_two: Capabilities = {
  schema_version: 1,
  model_types: [],
  imputation_methods: [
    { key: "mice", label: "MICE" },
    { key: "knn", label: "KNN" },
  ],
};

test("with exactly one imputation method renders a checkbox", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={null} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: /mice/i })).toBeInTheDocument();
});

test("with two+ methods renders a select", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_two} value={null} onChange={onChange} />);
  expect(screen.getByRole("combobox")).toBeInTheDocument();
});

test("checkbox emits the method key on change", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={null} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /mice/i }));
  expect(onChange).toHaveBeenCalledWith("mice");
});

test("checkbox emits null when unchecked", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={"mice"} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /mice/i }));
  expect(onChange).toHaveBeenCalledWith(null);
});

test("renders nothing when capabilities undefined or imputation_methods empty", () => {
  const { container, rerender } = render(
    <ImputationControls capabilities={undefined} value={null} onChange={() => {}} />,
  );
  expect(container.firstChild).toBeNull();

  rerender(
    <ImputationControls
      capabilities={{ schema_version: 1, model_types: [], imputation_methods: [] }}
      value={null}
      onChange={() => {}}
    />,
  );
  expect(container.firstChild).toBeNull();
});
